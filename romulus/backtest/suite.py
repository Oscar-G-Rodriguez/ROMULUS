"""Suite runner for Phase B strategy comparisons."""

from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd

from romulus.backtest.schedule import build_decision_schedule
from romulus.calendar.decision_days import generate_decision_calendar
from romulus.calendar.trading_days import get_trading_days
from romulus.config.schema import SuiteConfig
from romulus.data.ingestion import fetch_daily_data
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

        strategy_specs = self._expand_strategy_specs(config.strategies)
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
        meta_portfolio = Portfolio(cash=config.backtest.initial_cash, positions={})
        meta_decision_log: List[Dict[str, object]] = []
        meta_trades: List[Dict[str, object]] = []

        if skip_record is not None and config.meta.enabled:
            meta_decision_log.append(dict(skip_record))

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

            if config.meta.enabled:
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

                meta_trades.extend(
                    self._process_meta_decision(
                        config=config,
                        portfolio=meta_portfolio,
                        decision_date=decision_date,
                        fill_date=fill_date,
                        decision_prices=decision_prices,
                        eligible_tickers=eligible_with_prices,
                        data_by_date=data_by_date,
                        fill_field=fill_field,
                        raw_weights=selected_weights,
                        selected_strategy=selected_strategy_name,
                        leaderboard_snapshot=ranking,
                        decision_log=meta_decision_log,
                    )
                )

        leaderboard_df = pd.DataFrame(leaderboard_rows)
        leaderboard_path = run_path / "leaderboard.csv"
        leaderboard_df.to_csv(leaderboard_path, index=False)

        reliability_report = self._build_reliability_report(
            states,
            leaderboard_df,
        )
        with (run_path / "reliability_report.json").open("w", encoding="utf-8") as handle:
            json.dump(reliability_report, handle, indent=2, sort_keys=True)

        if config.meta.enabled:
            meta_path = run_path / "meta"
            meta_path.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(meta_trades).to_csv(meta_path / "trades.csv", index=False)
            _write_jsonl(meta_path / "decision_log.jsonl", meta_decision_log)

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

    def _expand_strategy_specs(self, strategies: List[object]) -> List[dict]:
        expanded: List[dict] = []
        for strat in strategies:
            base_params = strat.params or {}
            param_grid = strat.param_grid or {}
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
        portfolio: Portfolio,
        decision_date: date,
        fill_date: date,
        decision_prices: Dict[str, float],
        eligible_tickers: List[str],
        data_by_date: pd.DataFrame,
        fill_field: str,
        raw_weights: Dict[str, float],
        selected_strategy: str,
        leaderboard_snapshot: Dict[str, object],
        decision_log: List[Dict[str, object]],
    ) -> List[Dict[str, object]]:
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
        fills = simulate_fills(
            orders,
            fill_prices=fill_prices,
            fill_date=fill_date,
            slippage_bps=config.costs.slippage_bps,
            commission=config.costs.commission_per_trade,
        )
        portfolio.apply_fills(fills)
        total_value_after = portfolio.get_total_value(fill_prices)

        trades = [self._fill_to_trade(fill, decision_date, False) for fill in fills]

        decision_log.append(
            {
                "decision_date": _format_date(decision_date),
                "fill_date": _format_date(fill_date),
                "selected_strategy": selected_strategy,
                "raw_target_weights": raw_weights,
                "target_weights": target_weights,
                "cash_weight": constraint_info.get("cash_weight", _cash_weight(target_weights)),
                "portfolio_value_before": total_value_before,
                "portfolio_value_after": total_value_after,
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

    @staticmethod
    def _hash_config(config: SuiteConfig) -> str:
        payload = json.dumps(config.model_dump(), sort_keys=True)
        return hashlib.md5(payload.encode("utf-8")).hexdigest()
