"""Integration tests for determinism and lookahead checks."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from romulus.backtest.engine import BacktestEngine
from romulus.backtest.schedule import build_decision_schedule
from romulus.calendar.decision_days import generate_decision_calendar
from romulus.calendar.trading_days import get_trading_days
from romulus.config.schema import (
    BacktestConfig,
    BacktestSettings,
    CostConfig,
    DataConfig,
    ExecutionConfig,
    OutputConfig,
    StrategyConfig,
    UniverseConfig,
)


def _build_sample_data(tickers, start: str, end: str) -> pd.DataFrame:
    trading_days = get_trading_days(start, end)
    index = pd.to_datetime(trading_days)
    columns = pd.MultiIndex.from_product([tickers, ["Open", "Close"]])
    data = pd.DataFrame(index=index, columns=columns, dtype=float)

    for i, _ in enumerate(index):
        for j, ticker in enumerate(tickers):
            base = 100.0 + i * (j + 1)
            data[(ticker, "Open")].iloc[i] = base
            data[(ticker, "Close")].iloc[i] = base + 1.0

    return data


def _build_config(tmp_path, universe_path: Path, start: str, end: str, strategy_type: str) -> BacktestConfig:
    return BacktestConfig(
        backtest=BacktestSettings(
            name="Test",
            start_date=start,
            end_date=end,
            initial_cash=10000.0,
        ),
        universe=UniverseConfig(source=str(universe_path)),
        strategy=StrategyConfig(type=strategy_type),
        execution=ExecutionConfig(min_order_notional=0.0),
        costs=CostConfig(slippage_bps=5.0, commission_per_trade=0.0),
        data=DataConfig(cache_dir=str(tmp_path / "cache")),
        output=OutputConfig(run_dir=str(tmp_path / "runs")),
    )


def test_deterministic_runs(tmp_path, monkeypatch) -> None:
    universe = {
        "etfs": [
            {"ticker": "SPY", "name": "Test SPY", "inception_date": "2000-01-01"},
            {"ticker": "QQQ", "name": "Test QQQ", "inception_date": "2000-01-01"},
        ]
    }
    universe_path = tmp_path / "universe.json"
    universe_path.write_text(json.dumps(universe), encoding="utf-8")

    start_date = "2024-01-02"
    end_date = "2024-01-18"
    tickers = ["SPY", "QQQ"]
    sample_data = _build_sample_data(tickers, start_date, end_date)

    monkeypatch.setattr("romulus.backtest.engine.fetch_daily_data", lambda *args, **kwargs: sample_data)

    config = _build_config(tmp_path, universe_path, start_date, end_date, "equal_weight")

    engine = BacktestEngine()
    result_one = engine.run(config)
    result_two = engine.run(config)

    assert result_one["config_hash"] == result_two["config_hash"]
    pd.testing.assert_frame_equal(result_one["portfolio_value"], result_two["portfolio_value"])
    assert result_one["metrics"]["final_value"] == result_two["metrics"]["final_value"]


def test_no_lookahead(tmp_path, monkeypatch) -> None:
    universe = {
        "etfs": [
            {"ticker": "SPY", "name": "Test SPY", "inception_date": "2000-01-01"},
            {"ticker": "QQQ", "name": "Test QQQ", "inception_date": "2000-01-01"},
        ]
    }
    universe_path = tmp_path / "universe.json"
    universe_path.write_text(json.dumps(universe), encoding="utf-8")

    start_date = "2024-01-02"
    end_date = "2024-01-18"
    tickers = ["SPY", "QQQ"]
    sample_data = _build_sample_data(tickers, start_date, end_date)

    monkeypatch.setattr("romulus.backtest.engine.fetch_daily_data", lambda *args, **kwargs: sample_data)

    class LookaheadStrategy:
        def compute_target_weights(self, as_of_date, eligible_tickers, prices, positions):
            if len(prices.index) > 0:
                assert max(prices.index) <= as_of_date
            target = eligible_tickers[as_of_date.day % len(eligible_tickers)]
            return {ticker: (1.0 if ticker == target else 0.0) for ticker in eligible_tickers}

        def set_context(self, context):
            return None

        def get_last_signals(self):
            return {}

        def get_last_training_info(self):
            return {}

        def get_last_forecasts(self):
            return []

    monkeypatch.setattr(
        "romulus.backtest.engine.create_strategy",
        lambda *args, **kwargs: LookaheadStrategy(),
    )
    engine = BacktestEngine()

    config = _build_config(tmp_path, universe_path, start_date, end_date, "lookahead")
    result = engine.run(config)

    output_path = Path(result["output_path"])
    fills = pd.read_parquet(output_path / "fills.parquet")
    orders = pd.read_parquet(output_path / "orders.parquet")

    decision_calendar = generate_decision_calendar(start_date, end_date)
    trading_days = get_trading_days(start_date, end_date)
    schedule, _ = build_decision_schedule(
        decision_calendar,
        trading_days,
        "close",
        "open",
        pd.to_datetime(end_date).date(),
    )
    expected_fill_dates = [entry["fill_date"] for entry in schedule]

    fill_dates = pd.to_datetime(fills["fill_date"]).dt.date
    assert set(fill_dates) == set(expected_fill_dates)

    min_decision_date = pd.to_datetime(orders["decision_date"]).dt.date.min()
    assert all(fill_dates > min_decision_date)


def test_costs_applied(tmp_path, monkeypatch) -> None:
    universe = {
        "etfs": [
            {"ticker": "SPY", "name": "Test SPY", "inception_date": "2000-01-01"},
            {"ticker": "QQQ", "name": "Test QQQ", "inception_date": "2000-01-01"},
        ]
    }
    universe_path = tmp_path / "universe.json"
    universe_path.write_text(json.dumps(universe), encoding="utf-8")

    start_date = "2024-01-02"
    end_date = "2024-01-18"
    tickers = ["SPY", "QQQ"]
    sample_data = _build_sample_data(tickers, start_date, end_date)

    monkeypatch.setattr("romulus.backtest.engine.fetch_daily_data", lambda *args, **kwargs: sample_data)

    config = _build_config(tmp_path, universe_path, start_date, end_date, "equal_weight")
    engine = BacktestEngine()
    result = engine.run(config)

    fills = pd.read_parquet(Path(result["output_path"]) / "fills.parquet")

    assert (fills["slippage_cost"] > 0).all()
    assert (fills["net_cost"] > fills["gross_value"]).all()
