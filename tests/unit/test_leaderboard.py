"""Unit tests for leaderboard timing."""

from __future__ import annotations

import pandas as pd

from romulus.backtest.suite import StrategyState, compute_leaderboard_snapshot
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
        {"date": "2024-01-03", "total_value": 110.0},
        {"date": "2024-01-05", "total_value": 132.0},
        {"date": "2024-01-07", "total_value": 171.6},
    ]

    snapshot = compute_leaderboard_snapshot(2, [state], window=3)
    metrics = snapshot["test"]

    expected = pd.Series([0.10, 0.20])
    expected_sharpe = expected.mean() / expected.std() * (252 ** 0.5)

    assert metrics["sharpe"] == expected_sharpe

    snapshot_one = compute_leaderboard_snapshot(1, [state], window=3)
    assert snapshot_one["test"]["sharpe"] is None
