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
                fill_price=100.5,
            fill_date=date(2024, 1, 2),
            commission=0.0,
                slippage_cost=0.5,
                gross_value=100.5,
                net_cost=0.5,
        )
    ]

    portfolio.apply_fills(fills)

    assert portfolio.cash == 899.5


def test_cash_accounting_sell_fees() -> None:
    portfolio = Portfolio(cash=1000.0, positions={"SPY": 1.0})
    fills = [
        Fill(
            ticker="SPY",
            shares=-1.0,
            fill_price=100.0,
            fill_date=date(2024, 1, 2),
            commission=1.0,
                slippage_cost=1.0,
                gross_value=99.0,
                net_cost=2.0,
        )
    ]

    portfolio.apply_fills(fills)

    assert portfolio.cash == 1098.0
    assert "SPY" not in portfolio.positions


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
    expected_slippage = 0.1
    expected_net = expected_slippage + 1.0

    assert fills[0].net_cost == pytest.approx(expected_net)


def test_round_trip_costs_are_charged_once_and_cash_reconciles() -> None:
    buy, sell = simulate_fills(
        [
            Order(ticker="SPY", shares=10.0, decision_date=date(2024, 1, 2), target_weight=1.0),
            Order(ticker="SPY", shares=-10.0, decision_date=date(2024, 1, 3), target_weight=0.0),
        ],
        fill_prices={"SPY": 100.0}, fill_date=date(2024, 1, 3),
        slippage_bps=100.0, commission=1.0,
    )
    portfolio = Portfolio(cash=2000.0, positions={})
    portfolio.apply_fills([buy, sell])

    assert buy.fill_price == pytest.approx(101.0)
    assert sell.fill_price == pytest.approx(99.0)
    assert buy.slippage_cost == sell.slippage_cost == pytest.approx(10.0)
    assert buy.net_cost == sell.net_cost == pytest.approx(11.0)
    assert buy.cash_flow == pytest.approx(-1011.0)
    assert sell.cash_flow == pytest.approx(989.0)
    assert portfolio.cash == pytest.approx(1978.0)
    assert portfolio.positions == {}


def test_omitted_target_liquidates_and_unaffordable_buy_is_partial() -> None:
    orders = generate_orders(
        target_weights={}, current_positions={"SPY": 2.0}, prices={"SPY": 100.0},
        cash=0.0, total_value=200.0, min_notional=0.0, cash_buffer_pct=0.0,
        decision_date=date(2024, 1, 2),
    )
    assert len(orders) == 1 and orders[0].shares == pytest.approx(-2.0)

    fills = simulate_fills(
        [Order(ticker="SPY", shares=10.0, decision_date=date(2024, 1, 2), target_weight=1.0)],
        fill_prices={"SPY": 100.0}, fill_date=date(2024, 1, 3),
        slippage_bps=0.0, commission=1.0, available_cash=251.0,
    )
    assert fills[0].shares == pytest.approx(2.5)
    portfolio = Portfolio(cash=251.0, positions={})
    portfolio.apply_fills(fills)
    assert portfolio.cash == pytest.approx(0.0)
    assert portfolio.get_total_value({"SPY": 100.0}) == pytest.approx(250.0)


def test_invalid_or_missing_marks_are_rejected() -> None:
    portfolio = Portfolio(cash=0.0, positions={"SPY": 1.0})
    with pytest.raises(ValueError, match="Missing mark"):
        portfolio.get_total_value({})
    with pytest.raises(ValueError, match="Invalid mark"):
        portfolio.get_total_value({"SPY": 0.0})
