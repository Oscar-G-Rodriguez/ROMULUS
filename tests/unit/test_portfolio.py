"""Unit tests for portfolio accounting."""

from __future__ import annotations

from datetime import date

import pytest

from romulus.portfolio.account import Portfolio
from romulus.portfolio.fills import Fill, simulate_fills
from romulus.portfolio.orders import Order, generate_orders


def test_cash_accounting() -> None:
    portfolio = Portfolio(cash=1000.0, positions={})
    fills = [
        Fill(
            ticker="SPY",
            shares=1.0,
            fill_price=100.0,
            fill_date=date(2024, 1, 2),
            commission=0.0,
            slippage_cost=5.0,
            gross_value=100.0,
            net_cost=105.0,
        )
    ]

    portfolio.apply_fills(fills)

    assert portfolio.cash == 895.0


def test_cash_accounting_sell_fees() -> None:
    portfolio = Portfolio(cash=1000.0, positions={"SPY": 1.0})
    fills = [
        Fill(
            ticker="SPY",
            shares=-1.0,
            fill_price=100.0,
            fill_date=date(2024, 1, 2),
            commission=1.0,
            slippage_cost=2.0,
            gross_value=100.0,
            net_cost=103.0,
        )
    ]

    portfolio.apply_fills(fills)

    assert portfolio.cash == 1097.0
    assert portfolio.positions["SPY"] == 0.0


def test_fractional_shares() -> None:
    portfolio = Portfolio(cash=500.0, positions={})
    fills = [
        Fill(
            ticker="SPY",
            shares=2.5,
            fill_price=100.0,
            fill_date=date(2024, 1, 2),
            commission=0.0,
            slippage_cost=0.0,
            gross_value=250.0,
            net_cost=250.0,
        )
    ]

    portfolio.apply_fills(fills)

    assert portfolio.positions["SPY"] == 2.5


def test_market_value_calculation() -> None:
    portfolio = Portfolio(cash=100.0, positions={"SPY": 2.0, "QQQ": 1.0})
    prices = {"SPY": 100.0, "QQQ": 200.0}

    assert portfolio.compute_market_value(prices) == 400.0
    assert portfolio.get_total_value(prices) == 500.0


def test_order_generation_respects_min_notional() -> None:
    orders = generate_orders(
        {"SPY": 0.001},
        current_positions={},
        prices={"SPY": 100.0},
        cash=1000.0,
        total_value=1000.0,
        min_notional=1.0,
        cash_buffer_pct=0.01,
        decision_date=date(2024, 1, 2),
    )

    assert orders == []


def test_order_generation_respects_cash_buffer() -> None:
    orders = generate_orders(
        {"SPY": 1.0},
        current_positions={},
        prices={"SPY": 100.0},
        cash=1000.0,
        total_value=1000.0,
        min_notional=1.0,
        cash_buffer_pct=0.01,
        decision_date=date(2024, 1, 2),
    )

    assert len(orders) == 1
    assert orders[0].shares == pytest.approx(9.9)


def test_slippage_applied_correctly() -> None:
    orders = [
        Order(ticker="SPY", shares=10.0, decision_date=date(2024, 1, 2), target_weight=0.5),
        Order(ticker="SPY", shares=-10.0, decision_date=date(2024, 1, 2), target_weight=0.5),
    ]

    fills = simulate_fills(
        orders,
        fill_prices={"SPY": 100.0},
        fill_date=date(2024, 1, 3),
        slippage_bps=10.0,
        commission=0.0,
    )

    assert fills[0].fill_price == pytest.approx(100.1)
    assert fills[1].fill_price == pytest.approx(99.9)


def test_commission_applied() -> None:
    orders = [
        Order(ticker="SPY", shares=1.0, decision_date=date(2024, 1, 2), target_weight=1.0)
    ]

    fills = simulate_fills(
        orders,
        fill_prices={"SPY": 100.0},
        fill_date=date(2024, 1, 3),
        slippage_bps=10.0,
        commission=1.0,
    )

    expected_fill_price = 100.0 * 1.001
    expected_gross = expected_fill_price
    expected_slippage = expected_gross * 0.001
    expected_net = expected_gross + 1.0 + expected_slippage

    assert fills[0].net_cost == pytest.approx(expected_net)
