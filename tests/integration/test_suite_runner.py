"""Integration tests for suite runner."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from romulus.backtest.suite import SuiteRunner
from romulus.calendar.trading_days import get_trading_days
from romulus.config.schema import (
    BacktestSettings,
    CostConfig,
    DataConfig,
    ExecutionConfig,
    LeaderboardConfig,
    MetaConfig,
    SuiteConfig,
    SuiteOutputConfig,
    SuiteStrategyConfig,
    UniverseConfig,
    WarmupConfig,
)


def _build_sample_data(tickers, start: str, end: str) -> pd.DataFrame:
    trading_days = get_trading_days(start, end)
    index = pd.to_datetime(trading_days)
    columns = pd.MultiIndex.from_product([tickers, ["Open", "Close", "High", "Low", "Volume"]])
    data = pd.DataFrame(index=index, columns=columns, dtype=float)

    for i, _ in enumerate(index):
        for ticker in tickers:
            open_price = 100.0 + i
            data[(ticker, "Open")].iloc[i] = open_price
            data[(ticker, "Close")].iloc[i] = open_price + 1.0
            data[(ticker, "High")].iloc[i] = open_price + 2.0
            data[(ticker, "Low")].iloc[i] = open_price - 1.0
            data[(ticker, "Volume")].iloc[i] = 1_000_000 + i

    return data


def test_suite_runner_outputs_and_determinism(tmp_path, monkeypatch) -> None:
    universe = {
        "etfs": [
            {"ticker": "SPY", "name": "Test SPY", "inception_date": "2000-01-01"},
            {"ticker": "QQQ", "name": "Test QQQ", "inception_date": "2000-01-01"},
        ]
    }
    universe_path = tmp_path / "universe.json"
    universe_path.write_text(json.dumps(universe), encoding="utf-8")

    start_date = "2023-10-02"
    end_date = "2024-01-18"
    tickers = ["SPY", "QQQ"]
    sample_data = _build_sample_data(tickers, start_date, end_date)

    monkeypatch.setattr("romulus.backtest.suite.fetch_daily_data", lambda *args, **kwargs: sample_data)

    config = SuiteConfig(
        backtest=BacktestSettings(
            name="Suite Test",
            start_date=start_date,
            end_date=end_date,
            initial_cash=10000.0,
        ),
        universe=UniverseConfig(source=str(universe_path)),
        strategies=[
            SuiteStrategyConfig(name="equal_weight", type="equal_weight"),
            SuiteStrategyConfig(name="cash_only", type="cash_only"),
            SuiteStrategyConfig(
                name="ml_risk_adjusted",
                type="ml_risk_adjusted",
                params={
                    "model_family": "ridge",
                    "min_train_rows": 1,
                    "train_window_days": 200,
                    "device": "cpu",
                },
            ),
        ],
        execution=ExecutionConfig(min_order_notional=0.0),
        costs=CostConfig(),
        data=DataConfig(cache_dir=str(tmp_path / "cache")),
        output=SuiteOutputConfig(run_dir=str(tmp_path / "runs")),
        warmup=WarmupConfig(enabled=False),
        leaderboard=LeaderboardConfig(window=3, dd_limit=-1.0, turnover_limit=10.0),
        meta=MetaConfig(enabled=True, min_periods_before_selection=0),
    )

    runner = SuiteRunner()
    result_one = runner.run(config)

    config_two = config.model_copy(deep=True)
    config_two.output = SuiteOutputConfig(run_dir=str(tmp_path / "runs_two"))
    result_two = runner.run(config_two)

    assert result_one["leaderboard_hash"] == result_two["leaderboard_hash"]

    run_path = Path(result_one["output_path"])
    leaderboard_path = run_path / "leaderboard.csv"
    assert leaderboard_path.exists()

    leaderboard = pd.read_csv(leaderboard_path)
    expected_columns = {
        "decision_date",
        "strategy",
        "score",
        "rolling_sharpe",
        "rolling_drawdown",
        "rolling_turnover",
        "eligible",
        "rank",
    }
    assert expected_columns.issubset(set(leaderboard.columns))

    decision_log_path = run_path / "meta" / "decision_log.jsonl"
    lines = decision_log_path.read_text(encoding="utf-8").strip().splitlines()
    assert lines
    first_entry = json.loads(lines[0])
    assert "selected_strategy" in first_entry
    assert "leaderboard_ranks" in first_entry

    forecasts_path = run_path / "forecasts.csv"
    assert forecasts_path.exists()

    suite_summary_path = run_path / "suite_summary.json"
    assert suite_summary_path.exists()
    suite_summary = json.loads(suite_summary_path.read_text(encoding="utf-8"))
    assert "best_overall" in suite_summary

    regime_path = run_path / "regime_leaderboard.csv"
    assert regime_path.exists()
