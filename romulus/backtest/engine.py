"""Main backtest engine."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Dict, List

import pandas as pd

from romulus.backtest.metrics import compute_metrics
from romulus.calendar.decision_days import generate_decision_calendar, get_next_trading_day
from romulus.calendar.trading_days import get_trading_days
from romulus.config.schema import BacktestConfig
from romulus.data.ingestion import fetch_daily_data
from romulus.data.universe import Universe
from romulus.portfolio.account import Portfolio
from romulus.portfolio.fills import simulate_fills
from romulus.portfolio.orders import generate_orders
from romulus.strategy.cash_only import CashOnlyStrategy
from romulus.strategy.equal_weight import EqualWeightStrategy


class BacktestEngine:
    """Orchestrates backtest execution."""

    def __init__(self) -> None:
        self._strategy_map = {
            "equal_weight": EqualWeightStrategy,
            "cash_only": CashOnlyStrategy,
        }

    def run(self, config: BacktestConfig) -> Dict[str, object]:
        """Run a backtest and return metadata/results."""
        start_time = datetime.now(timezone.utc)

        universe = Universe.load_from_json(config.universe.source)
        tickers = universe.get_all_tickers()

        data = fetch_daily_data(
            tickers=tickers,
            start=config.backtest.start_date,
            end=config.backtest.end_date,
            cache_dir=config.data.cache_dir,
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
        positions_history: List[Dict[str, object]] = []
        portfolio_value_history: List[Dict[str, object]] = []

        strategy_type = config.strategy.type
        if strategy_type not in self._strategy_map:
            raise ValueError(f"Unknown strategy type: {strategy_type}")
        strategy = self._strategy_map[strategy_type]()

        data_by_date = data.copy()
        data_by_date.index = data_by_date.index.date

        for decision_date in decision_calendar:
            eligible_tickers = universe.get_eligible_tickers(decision_date)
            if not eligible_tickers:
                continue

            decision_row = data_by_date.loc[decision_date]
            decision_prices = {
                ticker: float(decision_row[(ticker, "Close")])
                for ticker in eligible_tickers
            }

            price_history = data_by_date.loc[:decision_date]
            target_weights = strategy.compute_target_weights(
                as_of_date=decision_date,
                eligible_tickers=eligible_tickers,
                prices=price_history,
                positions=portfolio.positions,
            )

            total_value = portfolio.get_total_value(decision_prices)
            orders = generate_orders(
                target_weights=target_weights,
                current_positions=portfolio.positions,
                prices=decision_prices,
                cash=portfolio.cash,
                total_value=total_value,
                min_notional=config.execution.min_order_notional,
                cash_buffer_pct=config.execution.cash_buffer_pct,
                decision_date=decision_date,
            )
            orders_list.extend(orders)

            fill_date = get_next_trading_day(decision_date, trading_days)
            fill_row = data_by_date.loc[fill_date]
            fill_prices = {
                ticker: float(fill_row[(ticker, "Open")])
                for ticker in eligible_tickers
                if ticker in decision_prices
            }

            fills = simulate_fills(
                orders,
                fill_prices=fill_prices,
                fill_date=fill_date,
                slippage_bps=config.costs.slippage_bps,
                commission=config.costs.commission_per_trade,
            )
            fills_list.extend(fills)

            portfolio.apply_fills(fills)

            positions_snapshot = {"date": fill_date}
            positions_snapshot.update(portfolio.positions)
            positions_history.append(positions_snapshot)

            portfolio_value = portfolio.get_total_value(fill_prices)
            portfolio_value_history.append(
                {"date": fill_date, "total_value": portfolio_value}
            )

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

        with (output_path / "metrics.json").open("w", encoding="utf-8") as handle:
            json.dump(metrics, handle, indent=2, sort_keys=True)

        manifest = {
            "run_id": run_id,
            "config_hash": config_hash,
            "config_name": config.backtest.name,
            "data_checksums": self._load_checksums(config.data.cache_dir),
            "status": "completed",
            "execution_time_seconds": (datetime.now(timezone.utc) - start_time).total_seconds(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with (output_path / "manifest.json").open("w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True)

        return {
            "run_id": run_id,
            "metrics": metrics,
            "output_path": str(output_path),
            "portfolio_value": portfolio_value_df,
            "config_hash": config_hash,
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
