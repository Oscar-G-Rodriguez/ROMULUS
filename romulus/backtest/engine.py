"""Main backtest engine."""

from __future__ import annotations

import hashlib
import json
from math import isfinite
from dataclasses import asdict
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd

from romulus.backtest.metrics import compute_metrics
from romulus.backtest.progress import ProgressEvent, ProgressReporter, ProgressTracker
from romulus.backtest.schedule import build_decision_schedule
from romulus.calendar.decision_days import generate_decision_calendar
from romulus.calendar.trading_days import get_trading_days
from romulus.config.schema import BacktestConfig
from romulus.data.ingestion import fetch_daily_data, load_price_data
from romulus.data.universe import Universe
from romulus.data.coverage import build_coverage_index
from romulus.portfolio.account import Portfolio
from romulus.portfolio.fills import Fill, simulate_fills
from romulus.portfolio.orders import generate_orders
from romulus.runtime import collect_runtime_info
from romulus.strategy.constraints import apply_weight_constraints, compute_current_weights
from romulus.strategy.registry import create_strategy


class BacktestEngine:
    """Orchestrates backtest execution."""

    def run(
        self,
        config: BacktestConfig,
        progress_callback: Optional[Callable[[ProgressEvent], None]] = None,
        cancel_requested: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, object]:
        """Run a backtest and return metadata/results."""
        start_time = datetime.now(timezone.utc)
        progress_reporter = ProgressReporter(progress_callback, cancel_requested, warmup_enabled=False)
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

        trading_days = get_trading_days(
            config.backtest.start_date,
            config.backtest.end_date,
        )
        decision_calendar = generate_decision_calendar(
            config.backtest.start_date,
            config.backtest.end_date,
            days=config.execution.decision_days,
        )

        portfolio = Portfolio(cash=config.backtest.initial_cash, positions={})

        orders_list = []
        fills_list = []
        trades_list: List[Dict[str, object]] = []
        decision_log: List[Dict[str, object]] = []
        forecasts_list: List[Dict[str, object]] = []
        positions_history: List[Dict[str, object]] = []
        portfolio_value_history: List[Dict[str, object]] = []

        strategy = create_strategy(config.strategy.type, config.strategy.params)

        data_by_date = data.copy()
        data_by_date.index = data_by_date.index.date

        end_date = date.fromisoformat(config.backtest.end_date)
        schedule, skipped = build_decision_schedule(
            decision_calendar,
            trading_days,
            config.execution.decision_time,
            config.execution.fill_time,
            end_date,
        )

        progress = None if progress_callback is not None else ProgressTracker(
            start_date=date.fromisoformat(config.backtest.start_date),
            end_date=end_date,
            label="Run",
            total_units=len(schedule),
        )

        if skipped is not None:
            message = (
                f"Skipping decision {skipped['decision_date']} because no fill date is available "
                f"before end_date {config.backtest.end_date}."
            )
            print(message)
            decision_log.append(
                {
                    "decision_date": skipped["decision_date"].isoformat(),
                    "skipped": True,
                    "reason": skipped["reason"],
                    "message": message,
                }
            )

        if not schedule:
            raise ValueError("No decision dates available for backtest run")
        progress_reporter.emit("validation", 1, 1, message="Configuration and schedule validated")

        # The pre-trade baseline makes initial transaction costs visible in
        # reported performance while retaining event-timestamped valuation.
        portfolio_value_history.append(
            {"date": schedule[0]["decision_date"], "total_value": portfolio.cash}
        )
        progress_reporter.emit("data", 1, 1, message="Price data loaded")

        decision_index_map = {
            entry["decision_date"]: idx for idx, entry in enumerate(schedule)
        }
        decision_field = "Open" if config.execution.decision_time == "open" else "Close"
        fill_field = "Open" if config.execution.fill_time == "open" else "Close"
        strategy.set_context(
            {
                "decision_schedule": schedule,
                "decision_index_map": decision_index_map,
                "universe": universe,
                "data_by_date": data_by_date,
                "costs": config.costs,
                "fill_field": fill_field,
            }
        )

        last_fill_value: float | None = None

        cancelled = False
        for decision_number, entry in enumerate(schedule, start=1):
            if cancel_requested is not None and cancel_requested():
                cancelled = True
                break
            decision_date = entry["decision_date"]
            fill_date = entry["fill_date"]
            eligible_tickers = universe.get_eligible_tickers(decision_date)
            if not eligible_tickers:
                continue

            if decision_date not in data_by_date.index or fill_date not in data_by_date.index:
                message = (
                    f"Skipping decision {decision_date} because price data is missing for "
                    f"decision or fill date."
                )
                print(message)
                decision_log.append(
                    {
                        "decision_date": decision_date.isoformat(),
                        "skipped": True,
                        "reason": "missing_price_data",
                        "message": message,
                    }
                )
                break

            decision_row = data_by_date.loc[decision_date]
            tradable_tickers = list(dict.fromkeys([*eligible_tickers, *portfolio.positions]))
            decision_prices = {}
            for ticker in tradable_tickers:
                try:
                    price = float(decision_row[(ticker, decision_field)])
                    if isfinite(price) and price > 0:
                        decision_prices[ticker] = price
                except KeyError:
                    continue
            if not decision_prices:
                continue
            eligible_with_prices = [ticker for ticker in eligible_tickers if ticker in decision_prices]
            if any(ticker not in decision_prices for ticker, shares in portfolio.positions.items() if shares != 0):
                raise ValueError(f"Cannot value held positions on decision date {decision_date}: missing price")

            price_history = data_by_date.loc[:decision_date]
            raw_weights = strategy.compute_target_weights(
                as_of_date=decision_date,
                eligible_tickers=eligible_with_prices,
                prices=price_history,
                positions=portfolio.positions,
            )

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

            total_value = portfolio.get_total_value(decision_prices)
            orders = generate_orders(
                target_weights=target_weights,
                current_positions=portfolio.positions,
                prices=decision_prices,
                cash=portfolio.cash,
                total_value=total_value,
                min_notional=config.execution.min_order_notional,
                cash_buffer_pct=config.execution.cash_buffer_pct,
                fractional_shares=config.execution.fractional_shares,
                decision_date=decision_date,
            )
            orders_list.extend(orders)

            fill_row = data_by_date.loc[fill_date]
            fill_prices = {}
            for ticker in tradable_tickers:
                try:
                    price = float(fill_row[(ticker, fill_field)])
                    if isfinite(price) and price > 0:
                        fill_prices[ticker] = price
                except KeyError:
                    continue
            if not fill_prices:
                continue

            pre_trade_value = portfolio.get_total_value(fill_prices)
            interval_return = None
            if last_fill_value is not None and last_fill_value > 0:
                interval_return = (pre_trade_value - last_fill_value) / last_fill_value

            fills = simulate_fills(
                orders,
                fill_prices=fill_prices,
                fill_date=fill_date,
                slippage_bps=config.costs.slippage_bps,
                commission=config.costs.commission_per_trade,
                available_cash=portfolio.cash,
            )
            fills_list.extend(fills)

            portfolio.apply_fills(fills)

            for fill in fills:
                trades_list.append(self._fill_to_trade(fill, decision_date))

            positions_snapshot = {"date": fill_date}
            positions_snapshot.update(portfolio.positions)
            positions_snapshot["cash"] = portfolio.cash
            positions_history.append(positions_snapshot)

            portfolio_value = portfolio.get_total_value(fill_prices)
            last_fill_value = portfolio_value
            portfolio_value_history.append(
                {"date": fill_date, "total_value": portfolio_value}
            )
            if progress is not None:
                progress.update(fill_date)
            progress_reporter.emit(
                "simulation", decision_number, len(schedule),
                current_date=decision_date, fill_date=fill_date,
                active_strategy=config.strategy.type,
                message=f"Decision {decision_number} of {len(schedule)}",
            )
            decision_log.append(
                {
                    "decision_date": decision_date.isoformat(),
                    "fill_date": fill_date.isoformat(),
                    "eligible_tickers": eligible_tickers,
                    "raw_target_weights": raw_weights,
                    "target_weights": target_weights,
                    "cash_weight": constraint_info.get("cash_weight"),
                    "turnover_pre": constraint_info.get("turnover_pre"),
                    "turnover_post": constraint_info.get("turnover_post"),
                    "turnover_scale_factor": constraint_info.get("scale_factor"),
                    "portfolio_value_before": total_value,
                    "portfolio_value_pre_trade": pre_trade_value,
                    "portfolio_value_after": portfolio_value,
                    "interval_return": interval_return,
                    "signals": strategy.get_last_signals(),
                    "training_info": strategy.get_last_training_info(),
                }
            )

            forecasts = strategy.get_last_forecasts()
            if forecasts:
                forecasts_list.extend(forecasts)

        if progress is not None:
            progress.finish()
        progress_reporter.emit("artifacts", 0, 1, message="Writing audit artifacts")

        portfolio_value_df = pd.DataFrame(portfolio_value_history)
        if not portfolio_value_df.empty:
            portfolio_value_df = portfolio_value_df.set_index("date")
        metrics = compute_metrics(portfolio_value_df["total_value"] if not portfolio_value_df.empty else pd.Series())

        config_hash = self._hash_config(config)
        run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{config_hash[:6]}"
        output_path = Path(config.output.run_dir) / run_id
        output_path.mkdir(parents=True, exist_ok=True)

        orders_df = pd.DataFrame([asdict(order) for order in orders_list])
        fills_df = pd.DataFrame([asdict(fill) for fill in fills_list])
        positions_df = pd.DataFrame(positions_history)
        if not positions_df.empty:
            positions_df = positions_df.set_index("date")

        orders_df.to_parquet(output_path / "orders.parquet")
        fills_df.to_parquet(output_path / "fills.parquet")
        positions_df.to_parquet(output_path / "positions.parquet")
        portfolio_value_df.to_parquet(output_path / "portfolio_value.parquet")

        orders_df.to_csv(output_path / "orders.csv", index=False)
        fills_df.to_csv(output_path / "fills.csv", index=False)
        pd.DataFrame(trades_list).to_csv(output_path / "trades.csv", index=False)
        positions_df.to_csv(output_path / "holdings.csv")

        with (output_path / "decision_log.jsonl").open("w", encoding="utf-8") as handle:
            for row in decision_log:
                handle.write(json.dumps(row) + "\n")

        if forecasts_list:
            pd.DataFrame(forecasts_list).to_csv(output_path / "forecasts.csv", index=False)

        with (output_path / "metrics.json").open("w", encoding="utf-8") as handle:
            json.dump(metrics, handle, indent=2, sort_keys=True)

        coverage = build_coverage_index(
            data, tickers, source=config.data.source,
            policy=config.data.coverage_policy,
            proxy="SPY" if "SPY" in tickers else (tickers[0] if tickers else None),
        )
        progress_reporter.emit("artifacts", 1, 1, message="Audit artifacts complete")
        manifest = {
            "run_id": run_id,
            "config_hash": config_hash,
            "config_name": config.backtest.name,
            "data_checksums": self._load_checksums(config.data.cache_dir),
            "status": "cancelled" if cancelled else "completed",
            "execution_time_seconds": (datetime.now(timezone.utc) - start_time).total_seconds(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "runtime": collect_runtime_info(decision_log),
            "data_coverage": coverage.to_dict(),
            "progress": progress_reporter.events,
        }
        with (output_path / "manifest.json").open("w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True)

        return {
            "run_id": run_id,
            "metrics": metrics,
            "output_path": str(output_path),
            "portfolio_value": portfolio_value_df,
            "config_hash": config_hash,
            "status": manifest["status"],
        }

    @staticmethod
    def _hash_config(config: BacktestConfig) -> str:
        payload = json.dumps(config.model_dump(), sort_keys=True)
        return hashlib.md5(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _load_checksums(cache_dir: str) -> Dict[str, str]:
        checksums_path = Path(cache_dir) / "checksums.json"
        if not checksums_path.exists():
            return {}
        with checksums_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def _fill_to_trade(fill: Fill, decision_date: date) -> Dict[str, object]:
        return {
            "ticker": fill.ticker,
            "shares": fill.shares,
            "fill_price": fill.fill_price,
            "fill_date": fill.fill_date.isoformat(),
            "decision_date": decision_date.isoformat(),
            "commission": fill.commission,
            "slippage_cost": fill.slippage_cost,
            "gross_value": fill.gross_value,
            "net_cost": fill.net_cost,
        }
