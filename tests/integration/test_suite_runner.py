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
            data.loc[data.index[i], (ticker, "Open")] = open_price
            data.loc[data.index[i], (ticker, "Close")] = open_price + 1.0
            data.loc[data.index[i], (ticker, "High")] = open_price + 2.0
            data.loc[data.index[i], (ticker, "Low")] = open_price - 1.0
            data.loc[data.index[i], (ticker, "Volume")] = 1_000_000 + i

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
            SuiteStrategyConfig(name="buy_and_hold", type="buy_and_hold"),
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
    assert first_entry["accounting_reconciliation_error"] == 0.0
    assert first_entry["portfolio_value_after"] == first_entry["cash_after"] + first_entry["position_value_after"]
    assert isinstance(first_entry["positions_after"], dict)
    assert (run_path / "meta" / "portfolio_values.csv").exists()

    forecasts_path = run_path / "forecasts.csv"
    assert forecasts_path.exists()

    ml_evaluation_path = run_path / "ml_evaluation.json"
    assert ml_evaluation_path.exists()
    assert "status" in json.loads(ml_evaluation_path.read_text(encoding="utf-8"))

    suite_summary_path = run_path / "suite_summary.json"
    assert suite_summary_path.exists()
    suite_summary = json.loads(suite_summary_path.read_text(encoding="utf-8"))
    assert "best_overall" in suite_summary

    regime_path = run_path / "regime_leaderboard.csv"
    assert regime_path.exists()

    buy_hold_trades = pd.read_csv(run_path / "buy_and_hold" / "trades.csv")
    assert len(buy_hold_trades) == len(tickers)

    manifest = json.loads((run_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["runtime"]["python_version"].startswith("3.12.")
    assert manifest["runtime"]["xgboost_version"]
    assert manifest["runtime"]["execution_devices"]

    cancelled_config = config.model_copy(deep=True)
    cancelled_config.output = SuiteOutputConfig(run_dir=str(tmp_path / "cancelled"))
    cancelled = runner.run(cancelled_config, cancel_requested=lambda: True)
    cancelled_manifest = json.loads(
        (Path(cancelled["output_path"]) / "manifest.json").read_text(encoding="utf-8")
    )
    assert cancelled["status"] == "cancelled"
    assert cancelled_manifest["status"] == "cancelled"
    assert cancelled_manifest["progress"][-1]["overall_percent"] < 100.0


def test_meta_champion_swaps_only_after_completed_intervals(tmp_path, monkeypatch) -> None:
    """A deterministic price reversal must switch the champion next decision."""
    universe_path = tmp_path / "universe.json"
    universe_path.write_text(json.dumps({"etfs": [
        {"ticker": "AAA", "name": "Alpha", "inception_date": "2000-01-01"},
        {"ticker": "BBB", "name": "Beta", "inception_date": "2000-01-01"},
    ]}), encoding="utf-8")
    start_date, end_date = "2024-01-02", "2024-02-16"
    days = pd.to_datetime(get_trading_days(start_date, end_date))
    columns = pd.MultiIndex.from_product([["AAA", "BBB"], ["Open", "Close", "High", "Low", "Volume"]])
    data = pd.DataFrame(index=days, columns=columns, dtype=float)
    for day in days:
        # AAA leads over the first completed interval, then BBB decisively
        # leads over the next. Values are known only at their fill dates.
        aaa = 100.0 if day < pd.Timestamp("2024-01-08") else (110.0 if day < pd.Timestamp("2024-01-11") else 88.0)
        bbb = 100.0 if day < pd.Timestamp("2024-01-08") else (101.0 if day < pd.Timestamp("2024-01-11") else 111.0)
        for ticker, value in (("AAA", aaa), ("BBB", bbb)):
            data.loc[day, (ticker, "Open")] = value
            data.loc[day, (ticker, "Close")] = value
            data.loc[day, (ticker, "High")] = value
            data.loc[day, (ticker, "Low")] = value
            data.loc[day, (ticker, "Volume")] = 1_000_000

    class SingleAssetStrategy:
        def __init__(self, ticker):
            self.ticker = ticker

        def set_context(self, context):
            return None

        def compute_target_weights(self, as_of_date, eligible_tickers, prices, positions):
            return {self.ticker: 1.0} if self.ticker in eligible_tickers else {}

        def get_last_signals(self):
            return {}

        def get_last_training_info(self):
            return {}

        def get_last_forecasts(self):
            return []

    monkeypatch.setattr("romulus.backtest.suite.fetch_daily_data", lambda *args, **kwargs: data)
    monkeypatch.setattr(
        "romulus.backtest.suite.create_strategy",
        lambda strategy_type, params=None: SingleAssetStrategy("AAA" if strategy_type == "alpha" else "BBB"),
    )
    config = SuiteConfig(
        backtest=BacktestSettings(name="Champion swap", start_date=start_date, end_date=end_date, initial_cash=10_000.0),
        universe=UniverseConfig(source=str(universe_path)),
        strategies=[
            SuiteStrategyConfig(name="alpha", type="alpha"),
            SuiteStrategyConfig(name="beta", type="beta"),
        ],
        execution=ExecutionConfig(min_order_notional=0.0, cash_buffer_pct=0.0, max_weight=1.0, turnover_cap=1.0),
        costs=CostConfig(), data=DataConfig(cache_dir=str(tmp_path / "cache")),
        output=SuiteOutputConfig(run_dir=str(tmp_path / "runs")), warmup=WarmupConfig(enabled=False),
        leaderboard=LeaderboardConfig(window=10, dd_limit=-1.0, turnover_limit=10.0),
        meta=MetaConfig(enabled=True, min_periods_before_selection=0, baseline_strategy="alpha"),
    )
    runner = SuiteRunner()
    runner._registry = {"alpha": (SingleAssetStrategy, "test"), "beta": (SingleAssetStrategy, "test")}
    result = runner.run(config)
    meta_log = [json.loads(line) for line in (Path(result["output_path"]) / "meta" / "decision_log.jsonl").read_text(encoding="utf-8").splitlines()]
    selections = [entry["selected_strategy"] for entry in meta_log if not entry.get("skipped")]

    # It first uses alpha, then switches to beta only after beta's completed
    # interval is present in the prior-only leaderboard snapshot.
    assert selections[2] == "alpha"
    assert selections[3] == "beta"  # Friday sees the reversal completed at the prior fill
    assert selections[4] == "beta"  # Wednesday holds the weekly incumbent

    timeline = pd.read_csv(Path(result["output_path"]) / "champion_timeline.csv")
    switched = timeline[timeline["switched"] == True]  # noqa: E712
    assert not switched.empty
    assert set(pd.to_datetime(switched["decision_date"]).dt.day_name()) == {"Friday"}
