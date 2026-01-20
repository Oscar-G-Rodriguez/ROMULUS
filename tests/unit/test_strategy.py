"""Unit tests for strategy implementations."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from romulus.strategy.cash_only import CashOnlyStrategy
from romulus.strategy.equal_weight import EqualWeightStrategy


def test_equal_weight_sums_to_one() -> None:
    strategy = EqualWeightStrategy()
    weights = strategy.compute_target_weights(
        as_of_date=date(2024, 1, 2),
        eligible_tickers=["SPY", "QQQ", "IWM"],
        prices=pd.DataFrame(),
        positions={},
    )

    assert sum(weights.values()) == pytest.approx(1.0)


def test_equal_weight_excludes_ineligible() -> None:
    strategy = EqualWeightStrategy()
    eligible = ["SPY", "QQQ"]
    weights = strategy.compute_target_weights(
        as_of_date=date(2024, 1, 2),
        eligible_tickers=eligible,
        prices=pd.DataFrame(),
        positions={},
    )

    assert set(weights.keys()) == set(eligible)


def test_equal_weight_handles_single_ticker() -> None:
    strategy = EqualWeightStrategy()
    weights = strategy.compute_target_weights(
        as_of_date=date(2024, 1, 2),
        eligible_tickers=["SPY"],
        prices=pd.DataFrame(),
        positions={},
    )

    assert weights["SPY"] == 1.0


def test_cash_only_returns_empty_weights() -> None:
    strategy = CashOnlyStrategy()
    weights = strategy.compute_target_weights(
        as_of_date=date(2024, 1, 2),
        eligible_tickers=["SPY"],
        prices=pd.DataFrame(),
        positions={},
    )

    assert weights == {}
