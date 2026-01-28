"""Suite runner for Phase B strategy comparisons."""

from __future__ import annotations

import hashlib
import itertools
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd

from romulus.backtest.metrics import compute_metrics
from romulus.backtest.progress import ProgressTracker
from romulus.backtest.schedule import build_decision_schedule
from romulus.calendar.decision_days import generate_decision_calendar
from romulus.calendar.trading_days import get_trading_days
from romulus.config.schema import SuiteConfig
from romulus.data.ingestion import fetch_daily_data
from romulus.data.external_features import (
    DEFAULT_MACRO_SERIES,
    align_features_to_dates,
    fetch_pytrends_series,
    fetch_quandl_series,
)
from romulus.data.universe import Universe
from romulus.portfolio.account import Portfolio
from romulus.portfolio.fills import Fill, simulate_fills
from romulus.portfolio.orders import Order, generate_orders
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


def _compute_sharpe(returns: List[float]) -> Optional[float]:
    if len(returns) < 2:
        return None
    series = pd.Series(returns)
    std = series.std()
    if std == 0 or pd.isna(std):
        return 0.0
    return float(series.mean() / std * (252 ** 0.5))


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


def _compute_cagr_from_returns(returns: List[float]) -> float:
    if not returns:
        return 0.0
    value = 1.0
    for ret in returns:
        value *= 1 + ret
    num_years = len(returns) / 252
    if num_years <= 0:
        return 0.0
    return float((value ** (1 / num_years) - 1) * 100)


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
    values: List[float],
    turnovers: List[float],
    window: int,
) -> Dict[str, Optional[float]]:
    if not returns:
        return {"sharpe": None, "drawdown": None, "turnover": None}

    window_returns = returns[-window:]
    window_values = values[-max(len(window_returns), 1):]
    window_turnovers = turnovers[-window:]

    return {
        "sharpe": _compute_sharpe(window_returns),
        "drawdown": _compute_drawdown(window_values),
        "turnover": _compute_turnover(window_turnovers),
    }


def compute_leaderboard_snapshot(
    decision_index: int,
    states: Iterable[StrategyState],
    window: int,
) -> Dict[str, Dict[str, Optional[float]]]:
    snapshot: Dict[str, Dict[str, Optional[float]]] = {}
    for state in states:
        metrics = _rolling_metrics(
            state.returns[:decision_index],
            [entry["total_value"] for entry in state.portfolio_values[:decision_index]],
            state.turnover[:decision_index],
            window,
        )
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


class SuiteRunner:
    """Runs a strategy suite with shadow portfolios and optional meta-selection."""

    def __init__(self) -> None:
        self._registry = get_strategy_registry()

    def run(self, config: SuiteConfig) -> Dict[str, object]:
        start_time = datetime.now(timezone.utc)

        universe = Universe.load_from_json(config.universe.source)
        tickers = universe.get_all_tickers()

        data = fetch_daily_data(
            tickers=tickers,
            start=config.backtest.start_date,
            end=config.backtest.end_date,
            cache_dir=config.data.cache_dir,
        )
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
                        external_features["macro"] = align_features_to_dates(macro_df, target_dates)

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
                        external_features["alt"] = align_features_to_dates(alt_df, target_dates)

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

        progress = ProgressTracker(
            start_date=date.fromisoformat(config.backtest.start_date),
            end_date=end_date,
            label="Suite",
        )

        strategy_specs = self._expand_strategy_specs(config.strategies, config.ml)
        states = self._initialize_states(strategy_specs, config)

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
        if config.warmup.enabled:
            warmup_weights = self._run_warmup(
                config=config,
                states=states,
                decisions=warmup_decisions,
                data_by_date=data_by_date,
                trading_days=trading_days,
                run_path=run_path,
                first_scored_decision=first_scored_decision,
                universe=universe,
            )

        initialization_trades: Dict[str, List[Dict[str, object]]] = {}
        if config.warmup.enabled and config.warmup.rebase:
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

        if skip_record is not None and meta_state is not None:
            meta_state.decision_log.append(dict(skip_record))

        for decision_index, entry in enumerate(schedule):
            decision_date = entry["decision_date"]
            fill_date = entry["fill_date"]
            eligible_tickers = universe.get_eligible_tickers(decision_date)
            if not eligible_tickers:
                continue

            snapshot = compute_leaderboard_snapshot(
                decision_index,
                states.values(),
                config.leaderboard.window,
            )

            ranking = self._rank_strategies(
                snapshot,
                config.leaderboard.dd_limit,
                config.leaderboard.turnover_limit,
            )

            for name, metrics in snapshot.items():
                row = {
                    "decision_date": _format_date(decision_date),
                    "strategy": name,
                    "score": metrics["sharpe"],
                    "rolling_sharpe": metrics["sharpe"],
                    "rolling_drawdown": metrics["drawdown"],
                    "rolling_turnover": metrics["turnover"],
                    "eligible": ranking["eligibility"].get(name, False),
                    "rank": ranking["ranks"].get(name),
                }
                leaderboard_rows.append(row)

            selected_strategy_name = None
            if config.meta.enabled:
                if decision_index < config.meta.min_periods_before_selection:
                    selected_strategy_name = config.meta.baseline_strategy
                else:
                    selected_strategy_name = ranking["top"]

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
                    )
                )
            progress.update(fill_date)

        progress.finish()

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
            _write_jsonl(meta_path / "decision_log.jsonl", meta_state.decision_log)

        self._write_strategy_artifacts(states, run_path)

        forecast_rows: List[Dict[str, object]] = []
        for state in states.values():
            if not state.forecasts:
                continue
            for row in state.forecasts:
                enriched = dict(row)
                enriched["strategy"] = state.name
                forecast_rows.append(enriched)
        if forecast_rows:
            pd.DataFrame(forecast_rows).to_csv(run_path / "forecasts.csv", index=False)

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

        manifest = {
            "run_id": run_id,
            "config_hash": self._hash_config(config),
            "config_name": config.backtest.name,
            "status": "completed",
            "execution_time_seconds": (datetime.now(timezone.utc) - start_time).total_seconds(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with (run_path / "manifest.json").open("w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True)

        return {
            "run_id": run_id,
            "output_path": str(run_path),
            "leaderboard_hash": _hash_dataframe(leaderboard_df),
            "suite_summary": suite_summary,
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

        for state in states.values():
            warmup_portfolio = Portfolio(cash=config.backtest.initial_cash, positions={})
            if warmup_schedule:
                for entry in warmup_schedule:
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

                    orders = generate_orders(
                        target_weights=target_weights,
                        current_positions=warmup_portfolio.positions,
                        prices=decision_prices,
                        cash=warmup_portfolio.cash,
                        total_value=warmup_portfolio.get_total_value(decision_prices),
                        min_notional=config.execution.min_order_notional,
                        cash_buffer_pct=config.execution.cash_buffer_pct,
                        decision_date=decision_date,
                    )
                    fills = simulate_fills(
                        orders,
                        fill_prices=fill_prices,
                        fill_date=fill_date,
                        slippage_bps=config.costs.slippage_bps,
                        commission=config.costs.commission_per_trade,
                    )
                    warmup_portfolio.apply_fills(fills)

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
                decision_date=decision_date,
            )
            fills = simulate_fills(
                orders,
                fill_prices=fill_prices,
                fill_date=fill_date,
                slippage_bps=config.costs.slippage_bps,
                commission=config.costs.commission_per_trade,
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
                prices[ticker] = float(row[(ticker, field)])
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
    ) -> None:
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

        orders = generate_orders(
            target_weights=target_weights,
            current_positions=state.portfolio.positions,
            prices=decision_prices,
            cash=state.portfolio.cash,
            total_value=total_value_before,
            min_notional=config.execution.min_order_notional,
            cash_buffer_pct=config.execution.cash_buffer_pct,
            decision_date=decision_date,
        )
        fill_prices = self._get_prices(data_by_date, fill_date, eligible_tickers, fill_field)
        if not fill_prices:
            return

        pre_trade_value = state.portfolio.get_total_value(fill_prices)
        interval_return = None
        if state.last_fill_value is not None and state.last_fill_value > 0:
            interval_return = (pre_trade_value - state.last_fill_value) / state.last_fill_value
            state.returns.append(interval_return)
        fills = simulate_fills(
            orders,
            fill_prices=fill_prices,
            fill_date=fill_date,
            slippage_bps=config.costs.slippage_bps,
            commission=config.costs.commission_per_trade,
        )

        for fill in fills:
            state.total_costs += fill.slippage_cost + fill.commission
            state.total_gross += fill.gross_value

        state.portfolio.apply_fills(fills)
        total_value_after = state.portfolio.get_total_value(fill_prices)
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
                "turnover": turnover,
                "total_value": total_value_after,
            }
        )
        holdings_snapshot = {"date": _format_date(fill_date), "cash": state.portfolio.cash}
        holdings_snapshot.update(state.portfolio.positions)
        state.holdings.append(holdings_snapshot)

        metrics = _rolling_metrics(
            state.returns,
            [entry["total_value"] for entry in state.portfolio_values],
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
    ) -> List[Dict[str, object]]:
        portfolio = meta_state.portfolio
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
            decision_date=decision_date,
        )
        fill_prices = self._get_prices(data_by_date, fill_date, eligible_tickers, fill_field)
        if not fill_prices:
            return []
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

        meta_state.decision_log.append(
            {
                "decision_date": _format_date(decision_date),
                "fill_date": _format_date(fill_date),
                "selected_strategy": selected_strategy,
                "raw_target_weights": raw_weights,
                "target_weights": target_weights,
                "cash_weight": constraint_info.get("cash_weight", _cash_weight(target_weights)),
                "portfolio_value_before": total_value_before,
                "portfolio_value_pre_trade": pre_trade_value,
                "portfolio_value_after": total_value_after,
                "interval_return": interval_return,
                "turnover_post": constraint_info.get("turnover_post"),
                "leaderboard_top": leaderboard_snapshot.get("top"),
                "leaderboard_ranks": leaderboard_snapshot.get("ranks"),
                "leaderboard_eligibility": leaderboard_snapshot.get("eligibility"),
            }
        )

        return trades

    def _rank_strategies(
        self,
        snapshot: Dict[str, Dict[str, Optional[float]]],
        dd_limit: float,
        turnover_limit: float,
    ) -> Dict[str, object]:
        eligibility: Dict[str, bool] = {}
        for name, metrics in snapshot.items():
            sharpe = metrics["sharpe"]
            drawdown = metrics["drawdown"]
            turnover = metrics["turnover"]
            eligible = (
                sharpe is not None
                and drawdown is not None
                and turnover is not None
                and drawdown >= dd_limit
                and turnover <= turnover_limit
            )
            eligibility[name] = eligible

        sortable = [
            (
                name,
                snapshot[name]["sharpe"],
                snapshot[name]["drawdown"],
                snapshot[name]["turnover"],
            )
            for name, is_ok in eligibility.items()
            if is_ok
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

        return {"eligibility": eligibility, "ranks": ranks, "top": top}

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

    def _build_reliability_report(
        self,
        states: Dict[str, StrategyState],
        leaderboard_df: pd.DataFrame,
    ) -> Dict[str, object]:
        per_strategy = {}
        rank_counts = leaderboard_df[leaderboard_df["rank"] == 1]["strategy"].value_counts()

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
        series = pd.Series(values) if values else pd.Series()
        metrics = compute_metrics(series)
        max_drawdown = _compute_drawdown(values) if values else 0.0
        if max_drawdown is None:
            max_drawdown = 0.0
        sharpe = _compute_sharpe(returns) if returns else 0.0
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
                sharpe = _compute_sharpe(returns) or 0.0
                cagr = _compute_cagr_from_returns(returns)
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
        if equity_ticker is None:
            return "UNKNOWN"
        if decision_date not in data_by_date.index:
            return "UNKNOWN"

        try:
            series = data_by_date.loc[:decision_date, (equity_ticker, "Close")].dropna()
        except KeyError:
            return "UNKNOWN"

        if len(series) < 64:
            return "UNKNOWN"

        ret_63 = series.iloc[-1] / series.iloc[-64] - 1
        returns = series.pct_change().dropna()
        if len(returns) < 21:
            return "UNKNOWN"
        vol_21 = returns.tail(21).std() * (252 ** 0.5)
        dd_63 = _compute_drawdown(series.tail(63).tolist())
        if dd_63 is None:
            return "UNKNOWN"

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

        return market_id

    @staticmethod
    def _hash_config(config: SuiteConfig) -> str:
        payload = json.dumps(config.model_dump(), sort_keys=True)
        return hashlib.md5(payload.encode("utf-8")).hexdigest()
