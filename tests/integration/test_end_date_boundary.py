"""Integration tests for end-date boundary handling."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from romulus.backtest.engine import BacktestEngine
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


def _build_sample_data(tickers, dates: list[str]) -> pd.DataFrame:
    index = pd.to_datetime(dates)
    columns = pd.MultiIndex.from_product([tickers, ["Open", "Close"]])
    data = pd.DataFrame(index=index, columns=columns, dtype=float)

    for i, _ in enumerate(index):
        for ticker in tickers:
            data.loc[data.index[i], (ticker, "Open")] = 100.0 + i
            data.loc[data.index[i], (ticker, "Close")] = 101.0 + i

    return data


def test_end_date_boundary_skip_logged(tmp_path, monkeypatch) -> None:
    universe = {
        "etfs": [
            {"ticker": "SPY", "name": "Test SPY", "inception_date": "2000-01-01"},
            {"ticker": "QQQ", "name": "Test QQQ", "inception_date": "2000-01-01"},
        ]
    }
    universe_path = tmp_path / "universe.json"
    universe_path.write_text(json.dumps(universe), encoding="utf-8")

    dates = ["2024-01-03", "2024-01-04", "2024-01-05"]
    sample_data = _build_sample_data(["SPY", "QQQ"], dates)

    monkeypatch.setattr("romulus.backtest.engine.fetch_daily_data", lambda *args, **kwargs: sample_data)

    config = BacktestConfig(
        backtest=BacktestSettings(
            name="Boundary Test",
            start_date="2024-01-03",
            end_date="2024-01-05",
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
    decision_log_path = output_path / "decision_log.jsonl"
    entries = [json.loads(line) for line in decision_log_path.read_text(encoding="utf-8").splitlines()]

    assert any(entry.get("skipped") for entry in entries)
