"""Suite runner for Phase B strategy comparisons."""

from __future__ import annotations

import hashlib
import itertools
import json
import os
from math import isfinite
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

import pandas as pd
import numpy as np

from romulus.backtest.metrics import compute_metrics
from romulus.backtest.progress import ProgressEvent, ProgressReporter, ProgressTracker, RunCancelled
from romulus.backtest.schedule import build_decision_schedule
from romulus.calendar.decision_days import generate_decision_calendar
from romulus.calendar.trading_days import get_trading_days
from romulus.config.schema import SuiteConfig
from romulus.data.ingestion import fetch_daily_data, load_price_data
from romulus.data.external_features import (
    DEFAULT_MACRO_SERIES,
    align_features_to_dates,
    fetch_pytrends_series,
    fetch_quandl_series,
)
from romulus.data.universe import Universe
from romulus.data.coverage import build_coverage_index
from romulus.portfolio.account import Portfolio
from romulus.portfolio.fills import Fill, simulate_fills
from romulus.portfolio.orders import Order, generate_orders
from romulus.runtime import collect_runtime_info
from romulus.strategy.constraints import apply_weight_constraints, compute_current_weights
from romulus.strategy.registry import create_strategy, get_strategy_registry


@dataclass
class StrategyState:
    name: str
    strategy_type: str
    strategy: object
    portfolio: Portfolio
    orders: List[Order] = field(default_factory=list)
    fills: List[Fill] = field(default_factory=list)
    trades: List[Dict[str, object]] = field(default_factory=list)
    decision_log: List[Dict[str, object]] = field(default_factory=list)
    portfolio_values: List[Dict[str, object]] = field(default_factory=list)
    holdings: List[Dict[str, object]] = field(default_factory=list)
    returns: List[float] = field(default_factory=list)
    turnover: List[float] = field(default_factory=list)
    rolling_sharpe: List[Optional[float]] = field(default_factory=list)
    rolling_drawdown: List[Optional[float]] = field(default_factory=list)
    rolling_turnover: List[Optional[float]] = field(default_factory=list)
    cash_pct: List[float] = field(default_factory=list)
    total_costs: float = 0.0
    total_gross: float = 0.0
    forecasts: List[Dict[str, object]] = field(default_factory=list)
    last_fill_value: Optional[float] = None
    interval_records: List[Dict[str, object]] = field(default_factory=list)


@dataclass
class MetaState:
    portfolio: Portfolio
    decision_log: List[Dict[str, object]] = field(default_factory=list)
    trades: List[Dict[str, object]] = field(default_factory=list)
    portfolio_values: List[Dict[str, object]] = field(default_factory=list)
    returns: List[float] = field(default_factory=list)
    turnover: List[float] = field(default_factory=list)
    last_fill_value: Optional[float] = None
    total_costs: float = 0.0
    total_gross: float = 0.0


def _cash_weight(target_weights: Dict[str, float]) -> float:
    return max(0.0, 1.0 - sum(target_weights.values()))


def _value_series(values: List[object]) -> pd.Series:
    """Construct a dated value series from suite records."""
    if not values:
        return pd.Series(dtype=float)
    if isinstance(values[0], dict):
        return pd.Series(
            [entry["total_value"] for entry in values],
            index=pd.to_datetime([entry["date"] for entry in values]),
            dtype=float,
        )
    return pd.Series(values, dtype=float)


def _compute_drawdown(values: List[float]) -> Optional[float]:
    if len(values) < 2:
        return None
    series = pd.Series(values)
    running_max = series.cummax()
    drawdown = (series - running_max) / running_max
    return float(drawdown.min())


def _compute_turnover(turnovers: List[float]) -> Optional[float]:
    if not turnovers:
        return None
    return float(pd.Series(turnovers).mean())


def _decision_counts(decision_log: List[Dict[str, object]]) -> Dict[str, int]:
    executed = sum(1 for entry in decision_log if not entry.get("skipped"))
    skipped = sum(1 for entry in decision_log if entry.get("skipped"))
    return {"executed": executed, "skipped": skipped}


def _returns_to_values(returns: List[float]) -> List[float]:
    values = [1.0]
    for ret in returns:
        values.append(values[-1] * (1 + ret))
    return values


def _compute_win_rate(returns: List[float]) -> float:
    if not returns:
        return 0.0
    wins = sum(1 for value in returns if value > 0)
    return wins / len(returns)


def _rolling_metrics(
    returns: List[float],
    values: List[object],
    turnovers: List[float],
    window: int,
) -> Dict[str, Optional[float]]:
    if not returns:
        return {"sharpe": None, "drawdown": None, "turnover": None}

    window_returns = returns[-window:]
    window_values = values[-(len(window_returns) + 1):]
    window_turnovers = turnovers[-window:]
    series = _value_series(window_values)

    return {
        "sharpe": compute_metrics(series)["sharpe"] if len(series) >= 3 else None,
        "drawdown": _compute_drawdown(series.tolist()),
        "turnover": _compute_turnover(window_turnovers),
    }


def compute_leaderboard_snapshot(
    decision_index: int,
    states: Iterable[StrategyState],
    window: int,
    current_regime: Optional[str] = None,
    regime_min_periods: int = 0,
) -> Dict[str, Dict[str, Optional[float]]]:
    """Return prior-only champion metrics, with guarded regime conditioning.

    Conditional performance is considered only after enough *completed* past
    intervals match the as-of regime. Until then, the global rolling Sharpe is
    retained as the champion score to avoid small-sample regime chasing.
    """
    snapshot: Dict[str, Dict[str, Optional[float]]] = {}
    for state in states:
        metrics = _rolling_metrics(
            state.returns[:decision_index],
            # Portfolio values contain one dated baseline plus one value for
            # each completed decision, so the prior-only slice is index + 1.
            state.portfolio_values[: decision_index + 1],
            state.turnover[:decision_index],
            window,
        )
        regime_returns = [
            float(record.get("net_interval_return", record["interval_return"]))
            for record in state.interval_records[:decision_index]
            if current_regime is not None
            and record.get("market_id") == current_regime
            and record.get("net_interval_return", record.get("interval_return")) is not None
        ]
        regime_observations = len(regime_returns)
        regime_score = (
            float(pd.Series(regime_returns).mean())
            if regime_min_periods > 0 and regime_observations >= regime_min_periods
            else None
        )
        metrics["regime_score"] = regime_score
        metrics["regime_observations"] = regime_observations
        metrics["score_source"] = "composite_pending" if regime_score is not None else "global_sharpe"
        metrics["global_percentile"] = None
        metrics["regime_percentile"] = None
        metrics["champion_score"] = metrics["sharpe"]
        snapshot[state.name] = metrics
    return snapshot


def _write_jsonl(path: Path, rows: List[Dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _hash_dataframe(df: pd.DataFrame) -> str:
    payload = df.to_csv(index=False).encode("utf-8")
    return hashlib.md5(payload).hexdigest()


def _format_date(value: date) -> str:
    return value.isoformat()


def _realized_interval_volatility(
    data: pd.DataFrame, ticker: str, start: date, end: date
) -> Optional[float]:
    try:
        close = pd.to_numeric(data.loc[start:end, (ticker, "Close")], errors="coerce").dropna()
    except KeyError:
        return None
    if len(close) < 2 or (close <= 0).any():
        return None
    log_returns = np.log(close).diff().dropna()
    if log_returns.empty:
        return None
    value = float(np.sqrt(np.square(log_returns).sum()))
    return value if isfinite(value) else None


class SuiteRunner:
    """Runs a strategy suite with shadow portfolios and optional meta-selection."""

    def __init__(self) -> None:
        self._registry = get_strategy_registry()

    def run(
        self,
        config: SuiteConfig,
        progress_callback: Optional[Callable[[ProgressEvent], None]] = None,
        cancel_requested: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, object]:
        start_time = datetime.now(timezone.utc)
        progress_reporter = ProgressReporter(
            progress_callback,
            cancel_requested,
            warmup_enabled=config.warmup.enabled,
        )
        progress_reporter.emit("data", 0, 1, message="Loading price data")

        universe = Universe.load_from_json(config.universe.source)
        tickers = universe.get_all_tickers()

        if config.data.source == "yfinance":
            data = fetch_daily_data(
                tickers=tickers, start=config.backtest.start_date,
                end=config.backtest.end_date, cache_dir=config.data.cache_dir,
            )
        else:
            data = load_price_data(
                tickers=tickers, start=config.backtest.start_date,
                end=config.backtest.end_date, cache_dir=config.data.cache_dir,
                source=config.data.source,
            )
        progress_reporter.emit("data", 1, 1, message="Price data loaded")
        data_by_date = data.copy()
        data_by_date.index = data_by_date.index.date

        external_features: Dict[str, pd.DataFrame] = {}
        alt_keywords_by_ticker: Dict[str, List[str]] = {}
        if config.ml.expanded:
            target_dates = data_by_date.index
            if config.ml.macro_enabled:
                api_key = os.getenv("NASDAQ_DATA_LINK_API_KEY")
                if not api_key:
                    print("Warning: NASDAQ_DATA_LINK_API_KEY not set; skipping macro features.")
                else:
                    macro_series = config.ml.macro_series or DEFAULT_MACRO_SERIES
                    macro_df = fetch_quandl_series(
                        macro_series,
                        api_key=api_key,
                        cache_dir=config.data.cache_dir,
                        start=config.backtest.start_date,
                        end=config.backtest.end_date,
                    )
                    if not macro_df.empty:
                        try:
                            external_features["macro"] = align_features_to_dates(macro_df, target_dates)
                        except ValueError as exc:
                            print(f"Warning: skipping macro features: {exc}")

            if config.ml.alt_enabled:
                keywords: List[str] = []
                for entry in universe.get_entries():
                    ticker_kw = entry.ticker
                    name_kw = entry.name
                    alt_keywords_by_ticker[entry.ticker] = [ticker_kw, name_kw]
                    keywords.extend([ticker_kw, name_kw])
                keywords = sorted(set(keywords))
                if keywords:
                    alt_df = fetch_pytrends_series(
                        keywords=keywords,
                        cache_dir=config.data.cache_dir,
                        start=config.backtest.start_date,
                        end=config.backtest.end_date,
                        sleep_seconds=config.ml.alt_sleep_seconds,
                    )
                    if not alt_df.empty:
                        try:
                            external_features["alt"] = align_features_to_dates(alt_df, target_dates)
                        except ValueError as exc:
                            print(f"Warning: skipping alt features: {exc}")

        warmup_start = config.warmup.start_date or config.backtest.start_date
        backtest_start_date = date.fromisoformat(config.backtest.start_date)
        warmup_start_date = date.fromisoformat(warmup_start)
        calendar_start = config.backtest.start_date
        if config.warmup.enabled and warmup_start_date < backtest_start_date:
            calendar_start = warmup_start

        trading_days = get_trading_days(
            calendar_start,
            config.backtest.end_date,
        )
        decision_calendar = generate_decision_calendar(
            config.backtest.start_date,
            config.backtest.end_date,
            days=config.execution.decision_days,
        )

        if not decision_calendar:
            raise ValueError("No decision dates available for suite run")

        end_date = date.fromisoformat(config.backtest.end_date)
        schedule, skipped = build_decision_schedule(
            decision_calendar,
            trading_days,
            config.execution.decision_time,
            config.execution.fill_time,
            end_date,
        )
        if skipped is not None:
            message = (
                f"Skipping decision {skipped['decision_date']} because no fill date is available "
                f"before end_date {config.backtest.end_date}."
            )
            print(message)

        if not schedule:
            raise ValueError("No decision dates available for suite run")
        progress_reporter.emit("validation", 1, 1, message="Configuration and schedule validated")

        first_scored_decision = schedule[0]["decision_date"]
        warmup_decisions: List[date] = []
        if config.warmup.enabled and warmup_start_date < backtest_start_date:
            warmup_end = (datetime.fromisoformat(config.backtest.start_date).date() - timedelta(days=1)).isoformat()
            warmup_decisions = generate_decision_calendar(
                warmup_start,
                warmup_end,
                days=config.execution.decision_days,
            )

        output_root = Path(config.output.run_dir)
        run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{self._hash_config(config)[:6]}"
        run_path = output_root / run_id
        run_path.mkdir(parents=True, exist_ok=True)

        progress = None if progress_callback is not None else ProgressTracker(
            start_date=date.fromisoformat(config.backtest.start_date),
            end_date=end_date,
            label="Suite",
            total_units=len(schedule),
        )

        strategy_specs = self._expand_strategy_specs(config.strategies, config.ml)
        states = self._initialize_states(strategy_specs, config)
        for state in states.values():
            state.portfolio_values.append(
                {"date": schedule[0]["decision_date"], "total_value": state.portfolio.cash}
            )

        decision_index_map = {
            entry["decision_date"]: idx for idx, entry in enumerate(schedule)
        }
        decision_field = "Open" if config.execution.decision_time == "open" else "Close"
        fill_field = "Open" if config.execution.fill_time == "open" else "Close"
        context = {
            "decision_schedule": schedule,
            "decision_index_map": decision_index_map,
            "universe": universe,
            "data_by_date": data_by_date,
            "costs": config.costs,
            "fill_field": fill_field,
            "external_features": external_features,
            "alt_keywords_by_ticker": alt_keywords_by_ticker,
            "ml_config": config.ml.model_dump(),
        }
        self._context = context
        for state in states.values():
            state.strategy.set_context(context)

        skip_record: Optional[Dict[str, object]] = None
        if skipped is not None:
            skip_record = {
                "decision_date": skipped["decision_date"].isoformat(),
                "skipped": True,
                "reason": skipped["reason"],
                "message": (
                    "Skipped final decision because fill date was unavailable before end_date."
                ),
            }
            for state in states.values():
                state.decision_log.append(dict(skip_record))

        warmup_weights: Dict[str, Dict[str, float]] = {}
        cancelled = False
        if config.warmup.enabled:
            try:
                warmup_weights = self._run_warmup(
                    config=config,
                    states=states,
                    decisions=warmup_decisions,
                    data_by_date=data_by_date,
                    trading_days=trading_days,
                    run_path=run_path,
                    first_scored_decision=first_scored_decision,
                    universe=universe,
                    progress_reporter=progress_reporter,
                )
            except RunCancelled:
                cancelled = True
        else:
            progress_reporter.emit("warmup", 1, 1, message="Warmup disabled")

        initialization_trades: Dict[str, List[Dict[str, object]]] = {}
        if not cancelled and config.warmup.enabled and config.warmup.rebase:
            initialization_trades = self._apply_rebase(
                config=config,
                states=states,
                warmup_weights=warmup_weights,
                data_by_date=data_by_date,
                run_path=run_path,
                decision_date=first_scored_decision,
                fill_date=schedule[0]["fill_date"],
            )

        leaderboard_rows: List[Dict[str, object]] = []
        meta_state: Optional[MetaState] = None
        if config.meta.enabled:
            meta_state = MetaState(portfolio=Portfolio(cash=config.backtest.initial_cash, positions={}))
            meta_state.portfolio_values.append(
                {"date": schedule[0]["decision_date"], "total_value": meta_state.portfolio.cash}
            )

        if skip_record is not None and meta_state is not None:
            meta_state.decision_log.append(dict(skip_record))

        incumbent = config.meta.baseline_strategy if config.meta.enabled else None
        for decision_index, entry in enumerate(schedule):
            if cancelled or (cancel_requested is not None and cancel_requested()):
                cancelled = True
                break
            decision_date = entry["decision_date"]
            fill_date = entry["fill_date"]
            eligible_tickers = universe.get_eligible_tickers(decision_date)
            if not eligible_tickers:
                continue

            tickers_for_regime = list(data_by_date.columns.get_level_values(0).unique())
            regime_proxy = "SPY" if "SPY" in tickers_for_regime else (tickers_for_regime[0] if tickers_for_regime else None)
            regime_details = self._market_snapshot_for_date(data_by_date, decision_date, regime_proxy)
            current_regime = str(regime_details["market_regime"])

            snapshot = compute_leaderboard_snapshot(
                decision_index,
                states.values(),
                config.leaderboard.window,
                current_regime=current_regime,
                regime_min_periods=config.leaderboard.regime_min_periods,
            )

            ranking = self._rank_strategies(
                snapshot,
                config.leaderboard.dd_limit,
                config.leaderboard.turnover_limit,
                global_weight=config.leaderboard.global_weight,
                regime_weight=config.leaderboard.regime_weight,
            )

            for name, metrics in snapshot.items():
                row = {
                    "decision_date": _format_date(decision_date),
                    "strategy": name,
                    "score": ranking["scores"].get(name),
                    "score_source": metrics["score_source"],
                    "market_regime": current_regime,
                    "regime_score": metrics["regime_score"],
                    "regime_observations": metrics["regime_observations"],
                    "global_percentile": ranking["global_percentiles"].get(name),
                    "regime_percentile": ranking["regime_percentiles"].get(name),
                    "rolling_sharpe": metrics["sharpe"],
                    "rolling_drawdown": metrics["drawdown"],
                    "rolling_turnover": metrics["turnover"],
                    "eligible": ranking["eligibility"].get(name, False),
                    "rank": ranking["ranks"].get(name),
                }
                leaderboard_rows.append(row)

            selected_strategy_name = None
            selection_info: Dict[str, object] = {
                "incumbent": incumbent,
                "challenger": ranking["top"],
                "switch_reason": "meta_disabled",
                "score_margin": None,
                "switched": False,
            }
            if config.meta.enabled:
                if decision_index < config.meta.min_periods_before_selection:
                    selected_strategy_name = config.meta.baseline_strategy
                    incumbent = selected_strategy_name
                    selection_info["switch_reason"] = "initialization_baseline"
                else:
                    is_selection_day = decision_date.strftime("%A").lower() == config.meta.selection_day.lower()
                    challenger = ranking["top"]
                    if not is_selection_day:
                        selected_strategy_name = incumbent or config.meta.baseline_strategy
                        selection_info["switch_reason"] = "incumbent_held_until_selection_day"
                    elif challenger is None:
                        selected_strategy_name = config.meta.baseline_strategy
                        selection_info["switch_reason"] = "no_eligible_candidate"
                    elif incumbent is None or not ranking["eligibility"].get(incumbent, False):
                        selected_strategy_name = challenger
                        selection_info["switch_reason"] = "incumbent_ineligible"
                    elif challenger == incumbent:
                        selected_strategy_name = incumbent
                        selection_info["switch_reason"] = "incumbent_ranked_first"
                    else:
                        margin = float(ranking["scores"][challenger]) - float(ranking["scores"][incumbent])
                        selection_info["score_margin"] = margin
                        if margin >= config.meta.switch_margin:
                            selected_strategy_name = challenger
                            selection_info["switch_reason"] = "challenger_exceeded_margin"
                        else:
                            selected_strategy_name = incumbent
                            selection_info["switch_reason"] = "challenger_below_margin"
                    selection_info["switched"] = incumbent is not None and selected_strategy_name != incumbent
                    incumbent = selected_strategy_name

            if decision_date not in data_by_date.index or fill_date not in data_by_date.index:
                message = (
                    f"Skipping decision {decision_date} because price data is missing for "
                    f"decision or fill date."
                )
                print(message)
                for state in states.values():
                    state.decision_log.append(
                        {
                            "decision_date": decision_date.isoformat(),
                            "skipped": True,
                            "reason": "missing_price_data",
                            "message": message,
                        }
                    )
                break

            decision_prices = self._get_prices(
                data_by_date,
                decision_date,
                eligible_tickers,
                decision_field,
            )
            eligible_with_prices = [t for t in eligible_tickers if t in decision_prices]
            if not eligible_with_prices:
                continue

            for state in states.values():
                raw_weights = self._compute_target_weights(
                    config=config,
                    state=state,
                    decision_date=decision_date,
                    eligible_tickers=eligible_with_prices,
                    data_by_date=data_by_date,
                    override_weights=None,
                )

                self._process_decision(
                    config=config,
                    state=state,
                    decision_date=decision_date,
                    fill_date=fill_date,
                    decision_prices=decision_prices,
                    eligible_tickers=eligible_with_prices,
                    data_by_date=data_by_date,
                    fill_field=fill_field,
                    raw_weights=raw_weights,
                    initialization=False,
                    market_id=current_regime,
                )

            if config.meta.enabled and meta_state is not None:
                if selected_strategy_name is None:
                    selected_strategy_name = config.meta.baseline_strategy

                if selected_strategy_name in states:
                    selected_weights = states[selected_strategy_name].decision_log[-1]["target_weights"]
                else:
                    selected_weights = self._compute_target_weights(
                        config=config,
                        state=states[next(iter(states))],
                        decision_date=decision_date,
                        eligible_tickers=eligible_with_prices,
                        data_by_date=data_by_date,
                        override_weights=None,
                        strategy_override=selected_strategy_name,
                    )

                meta_state.trades.extend(
                    self._process_meta_decision(
                        config=config,
                        meta_state=meta_state,
                        decision_date=decision_date,
                        fill_date=fill_date,
                        decision_prices=decision_prices,
                        eligible_tickers=eligible_with_prices,
                        data_by_date=data_by_date,
                        fill_field=fill_field,
                        raw_weights=selected_weights,
                        selected_strategy=selected_strategy_name,
                        leaderboard_snapshot=ranking,
                        market_id=current_regime,
                        regime_details=regime_details,
                        selection_info=selection_info,
                    )
                )
            if progress is not None:
                progress.update(fill_date)
            progress_reporter.emit(
                "simulation",
                decision_index + 1,
                len(schedule),
                current_date=decision_date,
                fill_date=fill_date,
                active_strategy=selected_strategy_name,
                message=f"Decision {decision_index + 1} of {len(schedule)}",
            )

        if progress is not None:
            progress.finish()
        progress_reporter.emit("artifacts", 0, 1, message="Writing audit artifacts")

        leaderboard_df = pd.DataFrame(leaderboard_rows)
        leaderboard_path = run_path / "leaderboard.csv"
        leaderboard_df.to_csv(leaderboard_path, index=False)

        reliability_report = self._build_reliability_report(
            states,
            leaderboard_df,
        )
        with (run_path / "reliability_report.json").open("w", encoding="utf-8") as handle:
            json.dump(reliability_report, handle, indent=2, sort_keys=True)

        if config.meta.enabled and meta_state is not None:
            meta_path = run_path / "meta"
            meta_path.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(meta_state.trades).to_csv(meta_path / "trades.csv", index=False)
            pd.DataFrame(meta_state.portfolio_values).to_csv(
                meta_path / "portfolio_values.csv", index=False
            )
            _write_jsonl(meta_path / "decision_log.jsonl", meta_state.decision_log)
            pd.DataFrame(meta_state.decision_log).to_csv(
                run_path / "champion_timeline.csv", index=False
            )

        self._write_strategy_artifacts(states, run_path)

        forecast_rows: List[Dict[str, object]] = []
        schedule_index = {entry["decision_date"].isoformat(): idx for idx, entry in enumerate(schedule)}
        for state in states.values():
            if not state.forecasts:
                continue
            for row in state.forecasts:
                enriched = dict(row)
                enriched["strategy"] = state.name
                enriched["model_family"] = getattr(state.strategy, "model_family", None)
                decision_index = schedule_index.get(str(enriched.get("decision_date")))
                if decision_index is not None and decision_index + 1 < len(schedule):
                    start = schedule[decision_index]["fill_date"]
                    end = schedule[decision_index + 1]["fill_date"]
                    try:
                        start_price = float(data_by_date.loc[start, (enriched["ticker"], fill_field)])
                        end_price = float(data_by_date.loc[end, (enriched["ticker"], fill_field)])
                        if isfinite(start_price) and isfinite(end_price) and start_price > 0 and end_price > 0:
                            enriched["target_fill_date"] = end.isoformat()
                            enriched["actual_return"] = end_price / start_price - 1.0
                            actual_volatility = _realized_interval_volatility(
                                data_by_date, str(enriched["ticker"]), start, end
                            )
                            enriched["actual_volatility"] = actual_volatility
                            expected_cost = float(enriched.get("expected_cost") or 0.0)
                            if actual_volatility is not None and actual_volatility > 0:
                                enriched["actual_rar"] = (
                                    float(enriched["actual_return"]) - expected_cost
                                ) / actual_volatility
                    except KeyError:
                        pass
                forecast_rows.append(enriched)
        if forecast_rows:
            pd.DataFrame(forecast_rows).to_csv(run_path / "forecasts.csv", index=False)
        ml_evaluation = self._build_ml_evaluation(forecast_rows)
        with (run_path / "ml_evaluation.json").open("w", encoding="utf-8") as handle:
            json.dump(ml_evaluation, handle, indent=2, sort_keys=True)

        suite_summary = self._build_suite_summary(states, meta_state, config)
        with (run_path / "suite_summary.json").open("w", encoding="utf-8") as handle:
            json.dump(suite_summary, handle, indent=2, sort_keys=True)

        regime_df = self._build_regime_leaderboard(
            states=states,
            schedule=schedule,
            data_by_date=data_by_date,
            config=config,
        )
        regime_path = run_path / "regime_leaderboard.csv"
        regime_df.to_csv(regime_path, index=False)

        coverage = build_coverage_index(
            data,
            tickers,
            source=config.data.source,
            policy=config.data.coverage_policy,
            proxy="SPY" if "SPY" in tickers else (tickers[0] if tickers else None),
        )
        if cancelled:
            progress_reporter.emit(
                "artifacts", 0, 1, message="Cancelled; partial audit artifacts saved"
            )
        else:
            progress_reporter.emit("artifacts", 1, 1, message="Audit artifacts complete")
        manifest = {
            "run_id": run_id,
            "config_hash": self._hash_config(config),
            "config_name": config.backtest.name,
            "status": "cancelled" if cancelled else "completed",
            "execution_time_seconds": (datetime.now(timezone.utc) - start_time).total_seconds(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "runtime": collect_runtime_info(
                row
                for state in states.values()
                for row in state.decision_log
            ),
            "data_coverage": coverage.to_dict(),
            "progress": progress_reporter.events,
        }
        with (run_path / "manifest.json").open("w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True)

        return {
            "run_id": run_id,
            "output_path": str(run_path),
            "leaderboard_hash": _hash_dataframe(leaderboard_df),
            "suite_summary": suite_summary,
            "status": manifest["status"],
        }

    def _initialize_states(self, strategy_specs: List[dict], config: SuiteConfig) -> Dict[str, StrategyState]:
        states: Dict[str, StrategyState] = {}
        for strat in strategy_specs:
            strat_type = strat["type"]
            strat_name = strat["name"]
            if strat_type not in self._registry:
                raise ValueError(f"Unknown strategy type: {strat_type}")
            if strat_name in states:
                raise ValueError(f"Duplicate strategy name: {strat_name}")
            portfolio = Portfolio(cash=config.backtest.initial_cash, positions={})
            strategy = create_strategy(strat_type, strat.get("params"))
            states[strat_name] = StrategyState(
                name=strat_name,
                strategy_type=strat_type,
                strategy=strategy,
                portfolio=portfolio,
            )
        return states

    def _expand_strategy_specs(self, strategies: List[object], ml_config: object) -> List[dict]:
        expanded: List[dict] = []
        for strat in strategies:
            base_params = strat.params or {}
            param_grid = strat.param_grid or {}
            if getattr(ml_config, "expanded", False) and strat.type.startswith("ml_"):
                if "train_window_days" not in param_grid and "train_window_days" not in base_params:
                    param_grid["train_window_days"] = list(ml_config.rolling_windows)
                if "expanding" not in param_grid and "expanding" not in base_params:
                    expanding_values = [False, True] if getattr(ml_config, "expanding", False) else [False]
                    param_grid["expanding"] = expanding_values
                if "embargo_intervals" not in param_grid and "embargo_intervals" not in base_params:
                    param_grid["embargo_intervals"] = [ml_config.embargo_intervals]
                if "expanded_features" not in param_grid and "expanded_features" not in base_params:
                    param_grid["expanded_features"] = [True]
            if not param_grid:
                expanded.append({"name": strat.name, "type": strat.type, "params": base_params})
                continue

            keys = list(param_grid.keys())
            values_list = [param_grid[key] for key in keys]
            for values in itertools.product(*values_list):
                params = dict(base_params)
                for key, value in zip(keys, values):
                    params[key] = value
                suffix = "_".join(f"{key}={value}" for key, value in zip(keys, values))
                name = f"{strat.name}_{suffix}"
                expanded.append({"name": name, "type": strat.type, "params": params})
        return expanded

    def _run_warmup(
        self,
        config: SuiteConfig,
        states: Dict[str, StrategyState],
        decisions: List[date],
        data_by_date: pd.DataFrame,
        trading_days: List[date],
        run_path: Path,
        first_scored_decision: date,
        universe: Universe,
        progress_reporter: Optional[ProgressReporter] = None,
    ) -> Dict[str, Dict[str, float]]:
        warmup_weights: Dict[str, Dict[str, float]] = {}
        decision_field = "Open" if config.execution.decision_time == "open" else "Close"
        fill_field = "Open" if config.execution.fill_time == "open" else "Close"
        warmup_schedule: List[dict] = []
        if decisions:
            warmup_schedule, _ = build_decision_schedule(
                decisions,
                trading_days,
                config.execution.decision_time,
                config.execution.fill_time,
                first_scored_decision,
            )

        total_steps = max(1, len(states) * max(1, len(warmup_schedule)))
        completed_steps = 0
        for state in states.values():
            warmup_portfolio = Portfolio(cash=config.backtest.initial_cash, positions={})
            if warmup_schedule:
                for entry in warmup_schedule:
                    if progress_reporter is not None:
                        progress_reporter.check_cancelled()
                    decision_date = entry["decision_date"]
                    fill_date = entry["fill_date"]
                    eligible = universe.get_eligible_tickers(decision_date)
                    if decision_date not in data_by_date.index or fill_date not in data_by_date.index:
                        continue

                    raw_weights = self._compute_target_weights(
                        config=config,
                        state=state,
                        decision_date=decision_date,
                        eligible_tickers=eligible,
                        data_by_date=data_by_date,
                        override_weights=None,
                        portfolio_override=warmup_portfolio,
                    )
                    decision_prices = self._get_prices(
                        data_by_date,
                        decision_date,
                        eligible,
                        decision_field,
                    )
                    if not decision_prices:
                        continue

                    current_weights = compute_current_weights(
                        warmup_portfolio.positions,
                        warmup_portfolio.cash,
                        decision_prices,
                    )
                    target_weights, _ = apply_weight_constraints(
                        raw_weights,
                        current_weights,
                        config.execution.max_weight,
                        config.execution.turnover_cap,
                    )
                    target_weights = {
                        ticker: weight
                        for ticker, weight in target_weights.items()
                        if ticker in decision_prices
                    }

                    fill_prices = self._get_prices(
                        data_by_date,
                        fill_date,
                        eligible,
                        fill_field,
                    )
                    if not fill_prices:
                        continue

                    if state.strategy_type == "buy_and_hold" and warmup_portfolio.positions:
                        orders = []
                    else:
                        orders = generate_orders(
                            target_weights=target_weights,
                            current_positions=warmup_portfolio.positions,
                            prices=decision_prices,
                            cash=warmup_portfolio.cash,
                            total_value=warmup_portfolio.get_total_value(decision_prices),
                            min_notional=config.execution.min_order_notional,
                            cash_buffer_pct=config.execution.cash_buffer_pct,
                            fractional_shares=config.execution.fractional_shares,
                            decision_date=decision_date,
                        )
                    fills = simulate_fills(
                        orders,
                        fill_prices=fill_prices,
                        fill_date=fill_date,
                        slippage_bps=config.costs.slippage_bps,
                        commission=config.costs.commission_per_trade,
                        available_cash=warmup_portfolio.cash,
                    )
                    warmup_portfolio.apply_fills(fills)
                    completed_steps += 1
                    if progress_reporter is not None:
                        progress_reporter.emit(
                            "warmup", completed_steps, total_steps,
                            current_date=decision_date, fill_date=fill_date,
                            active_strategy=state.name, message="Warming strategy history",
                        )

            decision_prices = self._get_prices(
                data_by_date,
                first_scored_decision,
                universe.get_eligible_tickers(first_scored_decision),
                decision_field,
            )
            total_value = warmup_portfolio.get_total_value(decision_prices)
            weights = {}
            for ticker, shares in warmup_portfolio.positions.items():
                price = decision_prices.get(ticker)
                if price is None:
                    continue
                weights[ticker] = (shares * price) / total_value if total_value > 0 else 0.0
            weights["cash_weight"] = warmup_portfolio.cash / total_value if total_value > 0 else 1.0
            warmup_weights[state.name] = weights

            warmup_path = run_path / state.name
            warmup_path.mkdir(parents=True, exist_ok=True)
            warmup_summary = {
                "warmup_start_date": config.warmup.start_date,
                "warmup_end_decision_date": decisions[-1].isoformat() if decisions else None,
                "first_scored_decision_date": first_scored_decision.isoformat(),
                "final_value": total_value,
                "weights": weights,
            }
            with (warmup_path / "warmup_summary.json").open("w", encoding="utf-8") as handle:
                json.dump(warmup_summary, handle, indent=2, sort_keys=True)

            if config.warmup.enabled and not config.warmup.rebase:
                state.portfolio = warmup_portfolio

        if progress_reporter is not None:
            progress_reporter.emit("warmup", total_steps, total_steps, message="Warmup complete")
        return warmup_weights

    def _apply_rebase(
        self,
        config: SuiteConfig,
        states: Dict[str, StrategyState],
        warmup_weights: Dict[str, Dict[str, float]],
        data_by_date: pd.DataFrame,
        run_path: Path,
        decision_date: date,
        fill_date: date,
    ) -> Dict[str, List[Dict[str, object]]]:
        init_trades: Dict[str, List[Dict[str, object]]] = {}
        eligible = list(data_by_date.columns.get_level_values(0).unique())
        decision_field = "Open" if config.execution.decision_time == "open" else "Close"
        fill_field = "Open" if config.execution.fill_time == "open" else "Close"
        decision_prices = self._get_prices(data_by_date, decision_date, eligible, decision_field)
        fill_prices = self._get_prices(data_by_date, fill_date, eligible, fill_field)

        for state in states.values():
            state.portfolio = Portfolio(cash=config.backtest.initial_cash, positions={})
            weights = warmup_weights.get(state.name, {})
            target_weights = {
                k: v
                for k, v in weights.items()
                if k != "cash_weight" and k in decision_prices
            }
            current_weights = compute_current_weights(
                state.portfolio.positions,
                state.portfolio.cash,
                decision_prices,
            )
            target_weights, _ = apply_weight_constraints(
                target_weights,
                current_weights,
                config.execution.max_weight,
                config.execution.turnover_cap,
            )
            target_weights = {
                ticker: weight for ticker, weight in target_weights.items() if ticker in decision_prices
            }

            orders = generate_orders(
                target_weights=target_weights,
                current_positions=state.portfolio.positions,
                prices=decision_prices,
                cash=state.portfolio.cash,
                total_value=state.portfolio.get_total_value(decision_prices),
                min_notional=config.execution.min_order_notional,
                cash_buffer_pct=config.execution.cash_buffer_pct,
                fractional_shares=config.execution.fractional_shares,
                decision_date=decision_date,
            )
            fills = simulate_fills(
                orders,
                fill_prices=fill_prices,
                fill_date=fill_date,
                slippage_bps=config.costs.slippage_bps,
                commission=config.costs.commission_per_trade,
                available_cash=state.portfolio.cash,
            )
            state.portfolio.apply_fills(fills)

            trades = [self._fill_to_trade(fill, decision_date, True) for fill in fills]
            init_trades[state.name] = trades

            init_path = run_path / state.name
            init_path.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(trades).to_csv(init_path / "initialization_trades.csv", index=False)

            state.trades.extend(trades)
            state.orders.extend(orders)
            state.fills.extend(fills)

        return init_trades

    def _compute_target_weights(
        self,
        config: SuiteConfig,
        state: StrategyState,
        decision_date: date,
        eligible_tickers: List[str],
        data_by_date: pd.DataFrame,
        override_weights: Optional[Dict[str, float]],
        portfolio_override: Optional[Portfolio] = None,
        strategy_override: Optional[str] = None,
    ) -> Dict[str, float]:
        if override_weights is not None:
            return override_weights

        strategy_type = strategy_override or state.strategy_type
        if strategy_override is None:
            strategy = state.strategy
        else:
            strategy = create_strategy(strategy_type, None)
            if getattr(self, "_context", None) is not None:
                strategy.set_context(self._context)
        price_history = data_by_date.loc[:decision_date]
        portfolio = portfolio_override or state.portfolio

        return strategy.compute_target_weights(
            as_of_date=decision_date,
            eligible_tickers=eligible_tickers,
            prices=price_history,
            positions=portfolio.positions,
        )

    def _get_prices(
        self,
        data_by_date: pd.DataFrame,
        target_date: date,
        tickers: List[str],
        field: str,
    ) -> Dict[str, float]:
        row = data_by_date.loc[target_date]
        prices = {}
        for ticker in tickers:
            try:
                price = float(row[(ticker, field)])
                if isfinite(price) and price > 0:
                    prices[ticker] = price
            except KeyError:
                continue
        return prices

    def _process_decision(
        self,
        config: SuiteConfig,
        state: StrategyState,
        decision_date: date,
        fill_date: date,
        decision_prices: Dict[str, float],
        eligible_tickers: List[str],
        data_by_date: pd.DataFrame,
        fill_field: str,
        raw_weights: Dict[str, float],
        initialization: bool,
        market_id: str = "UNKNOWN",
    ) -> None:
        valuation_tickers = list(dict.fromkeys([*eligible_tickers, *state.portfolio.positions]))
        held_tickers = [ticker for ticker, shares in state.portfolio.positions.items() if shares != 0]
        decision_field = "Open" if config.execution.decision_time == "open" else "Close"
        decision_prices = self._get_prices(data_by_date, decision_date, valuation_tickers, decision_field)
        if any(ticker not in decision_prices for ticker in held_tickers):
            raise ValueError(f"Cannot value held positions on decision date {decision_date}: missing price")
        total_value_before = state.portfolio.get_total_value(decision_prices)
        current_weights = compute_current_weights(
            state.portfolio.positions,
            state.portfolio.cash,
            decision_prices,
        )
        target_weights, constraint_info = apply_weight_constraints(
            raw_weights,
            current_weights,
            config.execution.max_weight,
            config.execution.turnover_cap,
        )
        target_weights = {
            ticker: weight for ticker, weight in target_weights.items() if ticker in decision_prices
        }

        if state.strategy_type == "buy_and_hold" and state.portfolio.positions:
            # A benchmark must preserve its acquired shares. Its changing target
            # weights still describe portfolio drift for comparison/meta use.
            # An asset leaving the eligible universe is the sole exception.
            orders = [
                Order(
                    ticker=ticker,
                    shares=-shares,
                    decision_date=decision_date,
                    target_weight=0.0,
                )
                for ticker, shares in state.portfolio.positions.items()
                if shares != 0 and ticker not in eligible_tickers and ticker in decision_prices
            ]
            liquidation_turnover = sum(
                abs(order.shares * decision_prices[order.ticker]) / total_value_before
                for order in orders
            ) if total_value_before > 0 else 0.0
            constraint_info["turnover_post"] = liquidation_turnover
        else:
            orders = generate_orders(
                target_weights=target_weights,
                current_positions=state.portfolio.positions,
                prices=decision_prices,
                cash=state.portfolio.cash,
                total_value=total_value_before,
                min_notional=config.execution.min_order_notional,
                cash_buffer_pct=config.execution.cash_buffer_pct,
                fractional_shares=config.execution.fractional_shares,
                decision_date=decision_date,
            )
        fill_prices = self._get_prices(data_by_date, fill_date, valuation_tickers, fill_field)
        if not fill_prices:
            return
        if any(ticker not in fill_prices for ticker in held_tickers):
            raise ValueError(f"Cannot value held positions on fill date {fill_date}: missing price")

        pre_trade_value = state.portfolio.get_total_value(fill_prices)
        interval_return = None
        net_interval_return = None
        if state.last_fill_value is not None and state.last_fill_value > 0:
            interval_return = (pre_trade_value - state.last_fill_value) / state.last_fill_value
            state.returns.append(interval_return)
        fills = simulate_fills(
            orders,
            fill_prices=fill_prices,
            fill_date=fill_date,
            slippage_bps=config.costs.slippage_bps,
            commission=config.costs.commission_per_trade,
            available_cash=state.portfolio.cash,
        )

        for fill in fills:
            state.total_costs += fill.slippage_cost + fill.commission
            state.total_gross += fill.gross_value

        state.portfolio.apply_fills(fills)
        total_value_after = state.portfolio.get_total_value(fill_prices)
        if state.last_fill_value is not None and state.last_fill_value > 0:
            net_interval_return = (total_value_after - state.last_fill_value) / state.last_fill_value
        state.last_fill_value = total_value_after

        trade_records = [self._fill_to_trade(fill, decision_date, initialization) for fill in fills]
        state.trades.extend(trade_records)
        state.orders.extend(orders)
        state.fills.extend(fills)

        turnover = constraint_info.get("turnover_post", 0.0)
        state.turnover.append(turnover)

        state.cash_pct.append(
            state.portfolio.cash / total_value_after if total_value_after > 0 else 1.0
        )

        state.portfolio_values.append(
            {"date": fill_date, "total_value": total_value_after}
        )
        state.interval_records.append(
            {
                "decision_date": decision_date,
                "fill_date": fill_date,
                "interval_return": interval_return,
                "net_interval_return": net_interval_return,
                "market_id": market_id,
                "turnover": turnover,
                "total_value": total_value_after,
            }
        )
        holdings_snapshot = {"date": _format_date(fill_date), "cash": state.portfolio.cash}
        holdings_snapshot.update(state.portfolio.positions)
        state.holdings.append(holdings_snapshot)

        metrics = _rolling_metrics(
            state.returns,
            state.portfolio_values,
            state.turnover,
            config.leaderboard.window,
        )
        state.rolling_sharpe.append(metrics["sharpe"])
        state.rolling_drawdown.append(metrics["drawdown"])
        state.rolling_turnover.append(metrics["turnover"])

        state.decision_log.append(
            {
                "decision_date": _format_date(decision_date),
                "fill_date": _format_date(fill_date),
                "market_regime": market_id,
                "eligible_tickers": eligible_tickers,
                "raw_target_weights": raw_weights,
                "target_weights": target_weights,
                "cash_weight": constraint_info.get("cash_weight", _cash_weight(target_weights)),
                "portfolio_value_before": total_value_before,
                "portfolio_value_pre_trade": pre_trade_value,
                "portfolio_value_after": total_value_after,
                "interval_return": interval_return,
                "turnover_pre": constraint_info.get("turnover_pre"),
                "turnover_post": constraint_info.get("turnover_post"),
                "turnover_scale_factor": constraint_info.get("scale_factor"),
                "rolling_sharpe": metrics["sharpe"],
                "rolling_drawdown": metrics["drawdown"],
                "rolling_turnover": metrics["turnover"],
                "signals": state.strategy.get_last_signals(),
                "training_info": state.strategy.get_last_training_info(),
            }
        )

        forecasts = state.strategy.get_last_forecasts()
        if forecasts:
            state.forecasts.extend(forecasts)

    def _process_meta_decision(
        self,
        config: SuiteConfig,
        meta_state: MetaState,
        decision_date: date,
        fill_date: date,
        decision_prices: Dict[str, float],
        eligible_tickers: List[str],
        data_by_date: pd.DataFrame,
        fill_field: str,
        raw_weights: Dict[str, float],
        selected_strategy: str,
        leaderboard_snapshot: Dict[str, object],
        market_id: str = "UNKNOWN",
        regime_details: Optional[Dict[str, object]] = None,
        selection_info: Optional[Dict[str, object]] = None,
    ) -> List[Dict[str, object]]:
        portfolio = meta_state.portfolio
        valuation_tickers = list(dict.fromkeys([*eligible_tickers, *portfolio.positions]))
        held_tickers = [ticker for ticker, shares in portfolio.positions.items() if shares != 0]
        decision_field = "Open" if config.execution.decision_time == "open" else "Close"
        decision_prices = self._get_prices(data_by_date, decision_date, valuation_tickers, decision_field)
        if any(ticker not in decision_prices for ticker in held_tickers):
            raise ValueError(f"Cannot value held positions on decision date {decision_date}: missing price")
        total_value_before = portfolio.get_total_value(decision_prices)
        current_weights = compute_current_weights(
            portfolio.positions,
            portfolio.cash,
            decision_prices,
        )
        target_weights, constraint_info = apply_weight_constraints(
            raw_weights,
            current_weights,
            config.execution.max_weight,
            config.execution.turnover_cap,
        )
        target_weights = {
            ticker: weight for ticker, weight in target_weights.items() if ticker in decision_prices
        }
        orders = generate_orders(
            target_weights=target_weights,
            current_positions=portfolio.positions,
            prices=decision_prices,
            cash=portfolio.cash,
            total_value=total_value_before,
            min_notional=config.execution.min_order_notional,
            cash_buffer_pct=config.execution.cash_buffer_pct,
            fractional_shares=config.execution.fractional_shares,
            decision_date=decision_date,
        )
        fill_prices = self._get_prices(data_by_date, fill_date, valuation_tickers, fill_field)
        if not fill_prices:
            return []
        if any(ticker not in fill_prices for ticker in held_tickers):
            raise ValueError(f"Cannot value held positions on fill date {fill_date}: missing price")
        pre_trade_value = portfolio.get_total_value(fill_prices)
        interval_return = None
        if meta_state.last_fill_value is not None and meta_state.last_fill_value > 0:
            interval_return = (pre_trade_value - meta_state.last_fill_value) / meta_state.last_fill_value
            meta_state.returns.append(interval_return)
        fills = simulate_fills(
            orders,
            fill_prices=fill_prices,
            fill_date=fill_date,
            slippage_bps=config.costs.slippage_bps,
            commission=config.costs.commission_per_trade,
            available_cash=portfolio.cash,
        )
        for fill in fills:
            meta_state.total_costs += fill.slippage_cost + fill.commission
            meta_state.total_gross += fill.gross_value
        portfolio.apply_fills(fills)
        total_value_after = portfolio.get_total_value(fill_prices)
        meta_state.last_fill_value = total_value_after
        meta_state.portfolio_values.append({"date": fill_date, "total_value": total_value_after})

        trades = [self._fill_to_trade(fill, decision_date, False) for fill in fills]
        meta_state.turnover.append(constraint_info.get("turnover_post", 0.0))

        selection_info = selection_info or {}
        regime_details = regime_details or {"market_regime": market_id}
        position_value = sum(
            shares * fill_prices[ticker]
            for ticker, shares in portfolio.positions.items()
            if shares != 0
        )
        meta_state.decision_log.append(
            {
                "decision_date": _format_date(decision_date),
                "fill_date": _format_date(fill_date),
                "market_regime": market_id,
                "regime_details": regime_details,
                "selected_strategy": selected_strategy,
                "incumbent": selection_info.get("incumbent"),
                "challenger": selection_info.get("challenger"),
                "switched": selection_info.get("switched", False),
                "switch_reason": selection_info.get("switch_reason"),
                "score_margin": selection_info.get("score_margin"),
                "raw_target_weights": raw_weights,
                "target_weights": target_weights,
                "cash_weight": constraint_info.get("cash_weight", _cash_weight(target_weights)),
                "portfolio_value_before": total_value_before,
                "portfolio_value_pre_trade": pre_trade_value,
                "portfolio_value_after": total_value_after,
                "cash_after": portfolio.cash,
                "positions_after": dict(sorted(portfolio.positions.items())),
                "position_value_after": position_value,
                "accounting_reconciliation_error": total_value_after
                - (portfolio.cash + position_value),
                "fill_count": len(fills),
                "commission_cost": sum(fill.commission for fill in fills),
                "slippage_cost": sum(fill.slippage_cost for fill in fills),
                "interval_return": interval_return,
                "turnover_post": constraint_info.get("turnover_post"),
                "leaderboard_top": leaderboard_snapshot.get("top"),
                "leaderboard_ranks": leaderboard_snapshot.get("ranks"),
                "leaderboard_eligibility": leaderboard_snapshot.get("eligibility"),
                "leaderboard_scores": leaderboard_snapshot.get("scores"),
                "global_percentiles": leaderboard_snapshot.get("global_percentiles"),
                "regime_percentiles": leaderboard_snapshot.get("regime_percentiles"),
            }
        )

        return trades

    def _rank_strategies(
        self,
        snapshot: Dict[str, Dict[str, Optional[float]]],
        dd_limit: float,
        turnover_limit: float,
        global_weight: float = 0.60,
        regime_weight: float = 0.40,
    ) -> Dict[str, object]:
        eligibility: Dict[str, bool] = {}
        for name, metrics in snapshot.items():
            score = metrics["sharpe"]
            drawdown = metrics["drawdown"]
            turnover = metrics["turnover"]
            eligible = (
                score is not None
                and drawdown is not None
                and turnover is not None
                and drawdown >= dd_limit
                and turnover <= turnover_limit
            )
            eligibility[name] = eligible

        eligible_names = [name for name, is_ok in eligibility.items() if is_ok]

        def percentiles(values: Dict[str, float]) -> Dict[str, float]:
            if not values:
                return {}
            series = pd.Series(values, dtype=float)
            if len(series) == 1:
                return {str(series.index[0]): 1.0}
            ranked = series.rank(method="average", pct=False)
            normalized = (ranked - 1.0) / (len(series) - 1.0)
            return {str(name): float(value) for name, value in normalized.items()}

        global_percentiles = percentiles(
            {name: float(snapshot[name]["sharpe"]) for name in eligible_names}
        )
        regime_percentiles = percentiles(
            {
                name: float(snapshot[name]["regime_score"])
                for name in eligible_names
                if snapshot[name]["regime_score"] is not None
            }
        )
        scores: Dict[str, float] = {}
        for name in eligible_names:
            global_score = global_percentiles[name]
            if name in regime_percentiles and regime_weight > 0:
                denominator = global_weight + regime_weight
                score = (
                    global_weight * global_score
                    + regime_weight * regime_percentiles[name]
                ) / denominator
                snapshot[name]["score_source"] = "global_regime_composite"
            else:
                score = global_score
                snapshot[name]["score_source"] = "global_sharpe"
            scores[name] = float(score)
            snapshot[name]["global_percentile"] = global_percentiles[name]
            snapshot[name]["regime_percentile"] = regime_percentiles.get(name)
            snapshot[name]["champion_score"] = float(score)

        sortable = [
            (name, scores[name], snapshot[name]["drawdown"], snapshot[name]["turnover"])
            for name in eligible_names
        ]

        sortable.sort(
            key=lambda item: (
                -item[1],
                -(item[2] or 0.0),
                item[3] or 0.0,
                item[0],
            )
        )

        ranks: Dict[str, int] = {}
        for idx, (name, _, _, _) in enumerate(sortable, start=1):
            ranks[name] = idx

        top = sortable[0][0] if sortable else None

        return {
            "eligibility": eligibility,
            "ranks": ranks,
            "top": top,
            "scores": scores,
            "global_percentiles": global_percentiles,
            "regime_percentiles": regime_percentiles,
        }

    def _fill_to_trade(self, fill: Fill, decision_date: date, initialization: bool) -> Dict[str, object]:
        return {
            "ticker": fill.ticker,
            "shares": fill.shares,
            "fill_price": fill.fill_price,
            "fill_date": _format_date(fill.fill_date),
            "decision_date": _format_date(decision_date),
            "commission": fill.commission,
            "slippage_cost": fill.slippage_cost,
            "gross_value": fill.gross_value,
            "net_cost": fill.net_cost,
            "is_initialization": initialization,
        }

    def _write_strategy_artifacts(self, states: Dict[str, StrategyState], run_path: Path) -> None:
        for state in states.values():
            strategy_path = run_path / state.name
            strategy_path.mkdir(parents=True, exist_ok=True)

            pd.DataFrame([asdict(order) for order in state.orders]).to_csv(
                strategy_path / "orders.csv",
                index=False,
            )
            pd.DataFrame([asdict(fill) for fill in state.fills]).to_csv(
                strategy_path / "fills.csv",
                index=False,
            )
            pd.DataFrame(state.trades).to_csv(
                strategy_path / "trades.csv",
                index=False,
            )
            pd.DataFrame(state.holdings).to_csv(
                strategy_path / "holdings.csv",
                index=False,
            )
            _write_jsonl(strategy_path / "decision_log.jsonl", state.decision_log)
            if state.forecasts:
                pd.DataFrame(state.forecasts).to_csv(
                    strategy_path / "forecasts.csv",
                    index=False,
                )

    @staticmethod
    def _build_ml_evaluation(forecasts: List[Dict[str, object]]) -> Dict[str, object]:
        """Score completed walk-forward return, volatility, and RAR forecasts."""
        frame = pd.DataFrame(forecasts)
        required = {"strategy", "decision_date", "ticker"}
        if frame.empty or not required.issubset(frame.columns):
            return {
                "status": "insufficient_data",
                "reason": "No completed forecasts were available.",
                "claim": "No ML value conclusion is supported.",
                "strategies": {},
            }
        frame = frame.sort_values(["strategy", "ticker", "decision_date"])

        def diagnostics(
            group: pd.DataFrame,
            prediction: pd.Series,
            actual: pd.Series,
            *,
            directional: bool = False,
        ) -> Dict[str, object]:
            error = prediction - actual
            correlations = []
            work = group.assign(prediction=prediction, actual=actual)
            for _, event in work.groupby("decision_date"):
                if len(event) >= 2 and event["prediction"].nunique() > 1 and event["actual"].nunique() > 1:
                    value = float(event["prediction"].rank().corr(event["actual"].rank()))
                    if isfinite(value):
                        correlations.append(value)
            result = {
                "observations": int(len(group)),
                "mae": float(error.abs().mean()),
                "rmse": float((error.pow(2).mean()) ** 0.5),
                "mean_rank_correlation": float(pd.Series(correlations).mean()) if correlations else None,
            }
            if directional:
                result["directional_accuracy"] = float(((prediction >= 0) == (actual >= 0)).mean())
            return result

        def split_labels(group: pd.DataFrame) -> pd.Series:
            dates = sorted(group["decision_date"].dropna().astype(str).unique())
            if not dates:
                return pd.Series("train", index=group.index)
            validation_at = max(1, int(len(dates) * 0.60))
            holdout_at = max(validation_at + 1, int(len(dates) * 0.80))
            validation_at = min(validation_at, len(dates))
            holdout_at = min(holdout_at, len(dates))
            validation_start = dates[validation_at] if validation_at < len(dates) else None
            holdout_start = dates[holdout_at] if holdout_at < len(dates) else None
            def label(value: object) -> str:
                text = str(value)
                if holdout_start is not None and text >= holdout_start:
                    return "holdout"
                if validation_start is not None and text >= validation_start:
                    return "validation"
                return "train"
            return group["decision_date"].map(label)

        strategies: Dict[str, object] = {}
        for name, group in frame.groupby("strategy", sort=True):
            group = group.copy()
            group["evaluation_split"] = split_labels(group)
            result: Dict[str, object] = {
                "model_family": str(group["model_family"].iloc[0]) if "model_family" in group else None,
                "split_counts": {str(k): int(v) for k, v in group["evaluation_split"].value_counts().items()},
            }
            if {"mu", "actual_return"}.issubset(group.columns):
                returns = group.dropna(subset=["mu", "actual_return"]).copy()
                if not returns.empty:
                    prediction = pd.to_numeric(returns["mu"])
                    actual = pd.to_numeric(returns["actual_return"])
                    persistence = actual.groupby(returns["ticker"]).shift(1)
                    valid = persistence.notna()
                    result["return"] = {
                        "walk_forward_model": diagnostics(returns, prediction, actual, directional=True),
                        "naive_zero_baseline": diagnostics(returns, pd.Series(0.0, index=returns.index), actual, directional=True),
                        "naive_persistence_baseline": diagnostics(returns.loc[valid], persistence.loc[valid], actual.loc[valid], directional=True) if valid.any() else None,
                        "by_split": {
                            split: diagnostics(part, pd.to_numeric(part["mu"]), pd.to_numeric(part["actual_return"]), directional=True)
                            for split, part in returns.groupby("evaluation_split")
                        },
                    }
            if {"sigma", "actual_volatility"}.issubset(group.columns):
                vols = group.dropna(subset=["sigma", "actual_volatility"]).copy()
                if not vols.empty:
                    prediction = pd.to_numeric(vols["sigma"]).clip(lower=0)
                    actual = pd.to_numeric(vols["actual_volatility"]).clip(lower=0)
                    persistence = actual.groupby(vols["ticker"]).shift(1)
                    valid = persistence.notna()
                    vol_metrics = diagnostics(vols, prediction, actual)
                    actual_mean = float(actual.mean())
                    vol_metrics["calibration_ratio"] = float(prediction.mean() / actual_mean) if actual_mean > 0 else None
                    result["volatility"] = {
                        "walk_forward_model": vol_metrics,
                        "naive_persistence_baseline": diagnostics(vols.loc[valid], persistence.loc[valid], actual.loc[valid]) if valid.any() else None,
                        "by_split": {
                            split: diagnostics(
                                part,
                                pd.to_numeric(part["sigma"]).clip(lower=0),
                                pd.to_numeric(part["actual_volatility"]).clip(lower=0),
                            )
                            for split, part in vols.groupby("evaluation_split")
                        },
                    }
            if {"score", "actual_rar"}.issubset(group.columns):
                rar = group.dropna(subset=["score", "actual_rar"]).copy()
                if not rar.empty:
                    predicted = pd.to_numeric(rar["score"])
                    actual = pd.to_numeric(rar["actual_rar"])
                    hits = []
                    for _, event in rar.assign(predicted=predicted, actual=actual).groupby("decision_date"):
                        if len(event) > 0:
                            hits.append(event.loc[event["predicted"].idxmax(), "ticker"] == event.loc[event["actual"].idxmax(), "ticker"])
                    result["rar"] = {
                        "rank_diagnostics": diagnostics(rar, predicted, actual),
                        "top_selection_hit_rate": float(pd.Series(hits).mean()) if hits else None,
                        "by_split": {
                            split: diagnostics(
                                part,
                                pd.to_numeric(part["score"]),
                                pd.to_numeric(part["actual_rar"]),
                            )
                            for split, part in rar.groupby("evaluation_split")
                        },
                    }
            strategies[str(name)] = result

        ridge = {name: result for name, result in strategies.items() if result["model_family"] == "ridge"}
        return {
            "status": "evaluated",
            "claim": "Metrics are descriptive; no ML superiority conclusion is supported without a predeclared untouched holdout after costs.",
            "ridge_reference": ridge if ridge else "not_run",
            "strategies": strategies,
        }

    def _build_reliability_report(
        self,
        states: Dict[str, StrategyState],
        leaderboard_df: pd.DataFrame,
    ) -> Dict[str, object]:
        per_strategy = {}
        if {"rank", "strategy"}.issubset(leaderboard_df.columns):
            rank_counts = leaderboard_df.loc[
                leaderboard_df["rank"] == 1, "strategy"
            ].value_counts()
        else:
            rank_counts = pd.Series(dtype=int)

        for name, state in states.items():
            sharpe_series = pd.Series([value for value in state.rolling_sharpe if value is not None])
            drawdown_series = pd.Series([value for value in state.rolling_drawdown if value is not None])
            turnover_series = pd.Series([value for value in state.rolling_turnover if value is not None])

            per_strategy[name] = {
                "rolling_sharpe": {
                    "mean": float(sharpe_series.mean()) if not sharpe_series.empty else None,
                    "std": float(sharpe_series.std()) if not sharpe_series.empty else None,
                    "min": float(sharpe_series.min()) if not sharpe_series.empty else None,
                    "max": float(sharpe_series.max()) if not sharpe_series.empty else None,
                },
                "max_drawdown": float(drawdown_series.min()) if not drawdown_series.empty else None,
                "turnover": {
                    "mean": float(turnover_series.mean()) if not turnover_series.empty else None,
                    "max": float(turnover_series.max()) if not turnover_series.empty else None,
                },
                "cash_pct": float(pd.Series(state.cash_pct).mean()) if state.cash_pct else None,
                "cost_drag": (state.total_costs / state.total_gross) if state.total_gross > 0 else 0.0,
                "top_rank_count": int(rank_counts.get(name, 0)),
            }

        most_reliable = None
        if per_strategy:
            ranked = sorted(
                per_strategy.items(),
                key=lambda item: (
                    -item[1]["top_rank_count"],
                    item[1]["rolling_sharpe"]["std"] or float("inf"),
                ),
            )
            most_reliable = ranked[0][0] if ranked else None

        return {
            "most_reliable": most_reliable,
            "most_reliable_rule": (
                "Highest top-rank frequency among eligible strategies; ties broken by lowest rolling "
                "Sharpe standard deviation."
            ),
            "strategies": per_strategy,
        }

    def _build_suite_summary(
        self,
        states: Dict[str, StrategyState],
        meta_state: Optional[MetaState],
        config: SuiteConfig,
    ) -> Dict[str, object]:
        summaries: Dict[str, Dict[str, object]] = {}
        for name, state in states.items():
            summaries[name] = self._build_portfolio_summary(
                name=name,
                portfolio_values=state.portfolio_values,
                returns=state.returns,
                turnovers=state.turnover,
                decision_log=state.decision_log,
                total_costs=state.total_costs,
                total_gross=state.total_gross,
            )

        best_overall, top_three = self._select_best_overall(
            summaries=summaries,
            dd_limit=config.leaderboard.dd_limit,
            turnover_limit=config.leaderboard.turnover_limit,
            min_periods=config.meta.min_periods_before_selection,
        )

        meta_summary = None
        if meta_state is not None:
            meta_summary = self._build_portfolio_summary(
                name="meta",
                portfolio_values=meta_state.portfolio_values,
                returns=meta_state.returns,
                turnovers=meta_state.turnover,
                decision_log=meta_state.decision_log,
                total_costs=meta_state.total_costs,
                total_gross=meta_state.total_gross,
            )

        comparison = list(summaries.values())
        if meta_summary is not None:
            comparison.append(meta_summary)
        return {
            "objective": {
                "primary": "net_sharpe",
                "gates": {
                    "max_drawdown": config.leaderboard.dd_limit,
                    "turnover": config.leaderboard.turnover_limit,
                    "min_periods": config.meta.min_periods_before_selection,
                },
                "tie_breakers": [
                    "higher_cagr",
                    "lower_max_drawdown_magnitude",
                    "lower_turnover",
                ],
            },
            "meta": meta_summary,
            "comparison": comparison,
            "best_overall": best_overall,
            "top3": top_three,
            "strategies": summaries,
        }

    def _build_portfolio_summary(
        self,
        name: str,
        portfolio_values: List[Dict[str, object]],
        returns: List[float],
        turnovers: List[float],
        decision_log: List[Dict[str, object]],
        total_costs: float,
        total_gross: float,
    ) -> Dict[str, object]:
        values = [entry["total_value"] for entry in portfolio_values]
        series = _value_series(portfolio_values)
        metrics = compute_metrics(series)
        max_drawdown = _compute_drawdown(values) if values else 0.0
        if max_drawdown is None:
            max_drawdown = 0.0
        sharpe = metrics["sharpe"] if len(series) >= 3 else 0.0
        if sharpe is None:
            sharpe = 0.0
        turnover = _compute_turnover(turnovers) if turnovers else 0.0
        if turnover is None:
            turnover = 0.0
        counts = _decision_counts(decision_log)
        cost_drag = (total_costs / total_gross) if total_gross > 0 else 0.0

        return {
            "strategy": name,
            "metrics": {
                "final_value": metrics["final_value"],
                "total_return_pct": metrics["total_return"],
                "cagr_pct": metrics["cagr"],
                "sharpe": sharpe,
                "annualized_volatility": metrics["annualized_volatility"],
                "max_drawdown_pct": metrics["max_drawdown"],
                "max_drawdown": max_drawdown,
                "turnover": turnover,
                "periods": len(returns),
                "decisions_executed": counts["executed"],
                "decisions_skipped": counts["skipped"],
                "cost_drag": cost_drag,
            },
        }

    def _select_best_overall(
        self,
        summaries: Dict[str, Dict[str, object]],
        dd_limit: float,
        turnover_limit: float,
        min_periods: int,
    ) -> tuple[Optional[Dict[str, object]], List[Dict[str, object]]]:
        candidates: List[Dict[str, object]] = []
        for summary in summaries.values():
            metrics = summary["metrics"]
            eligible = (
                metrics["periods"] >= min_periods
                and metrics["max_drawdown"] >= dd_limit
                and metrics["turnover"] <= turnover_limit
            )
            entry = dict(summary)
            entry["eligible"] = eligible
            candidates.append(entry)

        if not candidates:
            return None, []

        eligible_candidates = [entry for entry in candidates if entry["eligible"]]
        ranking_pool = eligible_candidates if eligible_candidates else candidates

        def sort_key(entry: Dict[str, object]) -> tuple:
            metrics = entry["metrics"]
            sharpe = metrics["sharpe"] if metrics["sharpe"] is not None else float("-inf")
            cagr = metrics["cagr_pct"] if metrics["cagr_pct"] is not None else float("-inf")
            max_drawdown = metrics["max_drawdown"] if metrics["max_drawdown"] is not None else -1e9
            turnover = metrics["turnover"] if metrics["turnover"] is not None else float("inf")
            return (-sharpe, -cagr, -max_drawdown, turnover, entry["strategy"])

        ranking_pool = sorted(ranking_pool, key=sort_key)
        best = ranking_pool[0] if ranking_pool else None
        top_three = ranking_pool[:3]
        return best, top_three

    def _build_regime_leaderboard(
        self,
        states: Dict[str, StrategyState],
        schedule: List[Dict[str, object]],
        data_by_date: pd.DataFrame,
        config: SuiteConfig,
    ) -> pd.DataFrame:
        market_ids = self._compute_market_ids(data_by_date, schedule)
        rows: List[Dict[str, object]] = []

        for state in states.values():
            regime_records: Dict[str, List[Dict[str, object]]] = {}
            for record in state.interval_records:
                interval_return = record.get("interval_return")
                if interval_return is None:
                    continue
                decision_date = record["decision_date"]
                market_id = market_ids.get(decision_date, "UNKNOWN")
                regime_records.setdefault(market_id, []).append(record)

            for market_id, records in regime_records.items():
                returns = [rec["interval_return"] for rec in records if rec.get("interval_return") is not None]
                if not returns:
                    continue
                turnovers = [rec["turnover"] for rec in records if rec.get("turnover") is not None]
                # An interval return begins at the prior fill. Regime slices
                # cannot reconstruct that boundary reliably, so leave
                # annualized values unavailable rather than assuming 252.
                sharpe = 0.0
                cagr = 0.0
                values = _returns_to_values(returns)
                max_dd = _compute_drawdown(values) if values else 0.0
                if max_dd is None:
                    max_dd = 0.0
                turnover = _compute_turnover(turnovers) if turnovers else 0.0
                if turnover is None:
                    turnover = 0.0
                win_rate = _compute_win_rate(returns)

                rows.append(
                    {
                        "market_id": market_id,
                        "strategy": state.name,
                        "intervals": len(returns),
                        "sharpe": sharpe,
                        "cagr": cagr,
                        "max_dd": max_dd,
                        "turnover": turnover,
                        "win_rate": win_rate,
                    }
                )

        columns = [
            "market_id",
            "strategy",
            "intervals",
            "sharpe",
            "cagr",
            "max_dd",
            "turnover",
            "win_rate",
            "best_strategy_for_market_id",
        ]
        if not rows:
            return pd.DataFrame(columns=columns)

        df = pd.DataFrame(rows)

        best_map: Dict[str, Optional[str]] = {}
        for market_id, group in df.groupby("market_id"):
            best_map[market_id] = self._select_best_from_rows(
                group,
                dd_limit=config.leaderboard.dd_limit,
                turnover_limit=config.leaderboard.turnover_limit,
                min_periods=config.meta.min_periods_before_selection,
            )

        df["best_strategy_for_market_id"] = df["market_id"].map(best_map)
        return df[columns]

    def _select_best_from_rows(
        self,
        group: pd.DataFrame,
        dd_limit: float,
        turnover_limit: float,
        min_periods: int,
    ) -> Optional[str]:
        eligible = group[
            (group["intervals"] >= min_periods)
            & (group["max_dd"] >= dd_limit)
            & (group["turnover"] <= turnover_limit)
        ]
        pool = eligible if not eligible.empty else group

        pool = pool.copy()
        pool["sort_sharpe"] = pool["sharpe"].fillna(-float("inf"))
        pool["sort_cagr"] = pool["cagr"].fillna(-float("inf"))
        pool["sort_drawdown"] = pool["max_dd"].fillna(-float("inf"))
        pool["sort_turnover"] = pool["turnover"].fillna(float("inf"))
        pool = pool.sort_values(
            by=["sort_sharpe", "sort_cagr", "sort_drawdown", "sort_turnover", "strategy"],
            ascending=[False, False, False, True, True],
        )

        if pool.empty:
            return None
        return str(pool.iloc[0]["strategy"])

    def _compute_market_ids(
        self,
        data_by_date: pd.DataFrame,
        schedule: List[Dict[str, object]],
    ) -> Dict[date, str]:
        tickers = list(data_by_date.columns.get_level_values(0).unique())
        equity_ticker = "SPY" if "SPY" in tickers else (tickers[0] if tickers else None)

        market_ids: Dict[date, str] = {}
        for entry in schedule:
            decision_date = entry["decision_date"]
            market_ids[decision_date] = self._market_id_for_date(
                data_by_date,
                decision_date,
                equity_ticker,
            )
        return market_ids

    def _market_id_for_date(
        self,
        data_by_date: pd.DataFrame,
        decision_date: date,
        equity_ticker: Optional[str],
    ) -> str:
        return str(self._market_snapshot_for_date(data_by_date, decision_date, equity_ticker)["market_regime"])

    def _market_snapshot_for_date(
        self,
        data_by_date: pd.DataFrame,
        decision_date: date,
        equity_ticker: Optional[str],
    ) -> Dict[str, object]:
        unknown = {
            "market_regime": "UNKNOWN",
            "proxy": equity_ticker,
            "return_63": None,
            "annualized_volatility_21": None,
            "drawdown_63": None,
        }
        if equity_ticker is None:
            return unknown
        if decision_date not in data_by_date.index:
            return unknown

        try:
            series = data_by_date.loc[:decision_date, (equity_ticker, "Close")].dropna()
        except KeyError:
            return unknown

        if len(series) < 64:
            return unknown

        ret_63 = series.iloc[-1] / series.iloc[-64] - 1
        returns = series.pct_change().dropna()
        if len(returns) < 21:
            return unknown
        # Market regime uses daily close returns; this is distinct from the
        # date-aware event-level performance metrics above.
        vol_21 = returns.tail(21).std() * (252 ** 0.5)
        dd_63 = _compute_drawdown(series.tail(63).tolist())
        if dd_63 is None:
            return unknown

        if ret_63 > 0.03:
            trend = "UP"
        elif ret_63 < -0.03:
            trend = "DOWN"
        else:
            trend = "SIDE"

        vol_bucket = "LOWVOL" if vol_21 < 0.18 else "HIGHVOL"
        market_id = f"{trend}_{vol_bucket}"
        if dd_63 <= -0.12:
            market_id = f"{market_id}_STRESS"

        return {
            "market_regime": market_id,
            "proxy": equity_ticker,
            "return_63": float(ret_63),
            "annualized_volatility_21": float(vol_21),
            "drawdown_63": float(dd_63),
        }

    @staticmethod
    def _hash_config(config: SuiteConfig) -> str:
        payload = json.dumps(config.model_dump(), sort_keys=True)
        return hashlib.md5(payload.encode("utf-8")).hexdigest()
