"""Unit tests for backtest utilities."""

from __future__ import annotations

import pandas as pd
import pytest

from romulus.backtest.costs import compute_commission, compute_slippage
from romulus.backtest.metrics import compute_metrics


def test_slippage_calculation() -> None:
    slippage = compute_slippage(shares=10.0, price=100.0, slippage_bps=5.0)

    assert slippage == pytest.approx(0.5)


def test_commission_calculation() -> None:
    assert compute_commission(shares=1.0, commission_per_trade=2.0) == 2.0
    assert compute_commission(shares=0.0, commission_per_trade=2.0) == 0.0


def test_metrics_calculation() -> None:
    portfolio_value = pd.Series(
        [100.0, 110.0, 121.0],
        index=pd.to_datetime(["2024-01-01", "2024-07-02", "2025-01-01"]),
    )

    metrics = compute_metrics(portfolio_value)

    expected_total_return = 21.0
    expected_cagr = (1.21 ** (365.25 / 366.0) - 1.0) * 100.0

    assert metrics["initial_value"] == 100.0
    assert metrics["final_value"] == 121.0
    assert metrics["total_return"] == pytest.approx(expected_total_return)
    assert metrics["cagr"] == pytest.approx(expected_cagr)
    assert metrics["sharpe"] == 0.0
    assert metrics["max_drawdown"] == 0.0


def test_metrics_use_elapsed_time_not_event_count() -> None:
    values = pd.Series(
        [100.0, 110.0, 121.0],
        index=pd.to_datetime(["2024-01-01", "2024-01-03", "2025-01-01"]),
    )
    metrics = compute_metrics(values)

    assert metrics["elapsed_days"] == 366.0
    assert metrics["cagr"] == pytest.approx((1.21 ** (365.25 / 366.0) - 1.0) * 100.0)
    # The irregular gaps are part of the calculation, not treated as 252 days.
    assert metrics["sharpe"] != 0.0
    assert metrics["annualized_volatility"] > 0.0
