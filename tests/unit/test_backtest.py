"""Unit tests for backtest utilities."""

from __future__ import annotations

import pytest

from romulus.backtest.costs import compute_commission, compute_slippage


def test_slippage_calculation() -> None:
    slippage = compute_slippage(shares=10.0, price=100.0, slippage_bps=5.0)

    assert slippage == pytest.approx(0.5)


def test_commission_calculation() -> None:
    assert compute_commission(shares=1.0, commission_per_trade=2.0) == 2.0
    assert compute_commission(shares=0.0, commission_per_trade=2.0) == 0.0
