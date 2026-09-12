"""Unit tests for leaderboard timing."""

from __future__ import annotations

import pandas as pd

from romulus.backtest.metrics import compute_metrics
from romulus.backtest.suite import SuiteRunner, StrategyState, compute_leaderboard_snapshot
from romulus.portfolio.account import Portfolio
from romulus.strategy.equal_weight import EqualWeightStrategy


def test_leaderboard_uses_prior_interval_only() -> None:
    state = StrategyState(
        name="test",
        strategy_type="equal_weight",
        strategy=EqualWeightStrategy(),
        portfolio=Portfolio(cash=1000.0, positions={}),
    )
    state.returns = [0.10, 0.20, 0.30]
    state.turnover = [0.1, 0.1, 0.1]
    state.portfolio_values = [
        {"date": "2024-01-01", "total_value": 100.0},
        {"date": "2024-01-03", "total_value": 110.0},
        {"date": "2024-01-05", "total_value": 132.0},
        {"date": "2024-01-07", "total_value": 171.6},
    ]

    snapshot = compute_leaderboard_snapshot(3, [state], window=3)
    metrics = snapshot["test"]

    expected = pd.Series(
        [100.0, 110.0, 132.0, 171.6],
        index=pd.to_datetime(["2024-01-01", "2024-01-03", "2024-01-05", "2024-01-07"]),
    )
    expected_sharpe = compute_metrics(expected)["sharpe"]

    assert metrics["sharpe"] == expected_sharpe

    snapshot_one = compute_leaderboard_snapshot(1, [state], window=3)
    assert snapshot_one["test"]["sharpe"] is None


def test_regime_score_uses_only_completed_matching_intervals() -> None:
    state = StrategyState(
        name="test", strategy_type="equal_weight", strategy=EqualWeightStrategy(),
        portfolio=Portfolio(cash=1000.0, positions={}),
    )
    state.returns = [0.01, 0.02, 0.03, -0.99]
    state.turnover = [0.1] * 4
    state.portfolio_values = [
        {"date": "2024-01-01", "total_value": 100.0},
        {"date": "2024-01-03", "total_value": 101.0},
        {"date": "2024-01-05", "total_value": 103.02},
        {"date": "2024-01-08", "total_value": 106.11},
        {"date": "2024-01-10", "total_value": 1.06},
    ]
    state.interval_records = [
        {"market_id": "UP_LOWVOL", "interval_return": 0.01},
        {"market_id": "UP_LOWVOL", "interval_return": 0.02},
        {"market_id": "UP_LOWVOL", "interval_return": 0.03},
        # This future observation would reverse the score if it leaked in.
        {"market_id": "UP_LOWVOL", "interval_return": -0.99},
    ]

    snapshot = compute_leaderboard_snapshot(
        3, [state], window=10, current_regime="UP_LOWVOL", regime_min_periods=3,
    )["test"]
    assert snapshot["regime_observations"] == 3
    assert snapshot["regime_score"] == 0.02
    assert snapshot["score_source"] == "composite_pending"


def test_composite_ranking_blends_global_and_regime_percentiles() -> None:
    snapshot = {
        "global": {"sharpe": 2.0, "regime_score": 0.01, "drawdown": -0.05, "turnover": 0.2},
        "regime": {"sharpe": 1.0, "regime_score": 0.03, "drawdown": -0.05, "turnover": 0.2},
    }
    ranking = SuiteRunner()._rank_strategies(
        snapshot, -0.20, 1.0, global_weight=0.60, regime_weight=0.40,
    )

    assert ranking["scores"] == {"global": 0.6, "regime": 0.4}
    assert ranking["top"] == "global"
    assert snapshot["global"]["score_source"] == "global_regime_composite"
