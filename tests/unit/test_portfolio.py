"""Unit tests for portfolio accounting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from romulus.portfolio.account import Portfolio


@dataclass
class DummyFill:
    ticker: str
    shares: float
    net_cost: float
    fill_date: date


def test_cash_accounting() -> None:
    portfolio = Portfolio(cash=1000.0, positions={})
    fills = [DummyFill(ticker="SPY", shares=1.0, net_cost=105.0, fill_date=date(2024, 1, 2))]

    portfolio.apply_fills(fills)

    assert portfolio.cash == 895.0


def test_fractional_shares() -> None:
    portfolio = Portfolio(cash=500.0, positions={})
    fills = [DummyFill(ticker="SPY", shares=2.5, net_cost=250.0, fill_date=date(2024, 1, 2))]

    portfolio.apply_fills(fills)

    assert portfolio.positions["SPY"] == 2.5


def test_market_value_calculation() -> None:
    portfolio = Portfolio(cash=100.0, positions={"SPY": 2.0, "QQQ": 1.0})
    prices = {"SPY": 100.0, "QQQ": 200.0}

    assert portfolio.compute_market_value(prices) == 400.0
    assert portfolio.get_total_value(prices) == 500.0
