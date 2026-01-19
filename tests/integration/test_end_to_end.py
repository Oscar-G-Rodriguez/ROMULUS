"""Integration test for end-to-end backtest run."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from romulus.backtest.engine import BacktestEngine
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
        for ticker in tickers:
            data[(ticker, "Open")].iloc[i] = 100.0 + i
            data[(ticker, "Close")].iloc[i] = 101.0 + i

    return data


def test_full_backtest_completes(tmp_path, monkeypatch) -> None:
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

    def fake_fetch_daily_data(tickers, start, end, cache_dir):
        return sample_data

    monkeypatch.setattr("romulus.backtest.engine.fetch_daily_data", fake_fetch_daily_data)

    config = BacktestConfig(
        backtest=BacktestSettings(
            name="Test",
            start_date=start_date,
            end_date=end_date,
            initial_cash=10000.0,
        ),
        universe=UniverseConfig(source=str(universe_path)),
        strategy=StrategyConfig(type="equal_weight"),
        execution=ExecutionConfig(),
        costs=CostConfig(),
        data=DataConfig(cache_dir=str(tmp_path / "cache")),
        output=OutputConfig(run_dir=str(tmp_path / "runs")),
    )

    engine = BacktestEngine()
    result = engine.run(config)

    output_path = Path(result["output_path"])
    assert output_path.exists()
    assert (output_path / "orders.parquet").exists()
    assert result["metrics"]["final_value"] > 0
