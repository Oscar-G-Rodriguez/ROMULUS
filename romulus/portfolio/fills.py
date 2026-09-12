"""Fill simulation utilities.

Slippage is represented once: it is embedded in an adverse fill price.
``slippage_cost`` records the difference from the reference price for audit,
but is never deducted again from cash.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import isfinite
from typing import Dict, List

from romulus.portfolio.orders import Order


@dataclass
class Fill:
    """Represents an executed fill for an order."""

    ticker: str
    shares: float
    fill_price: float
    fill_date: date
    commission: float
    slippage_cost: float
    gross_value: float
    net_cost: float
    cash_flow: float = 0.0


def simulate_fills(
    orders: List[Order],
    fill_prices: Dict[str, float],
    fill_date: date,
    slippage_bps: float,
    commission: float,
    available_cash: float | None = None,
) -> List[Fill]:
    """Simulate fills at an adverse price with one commission per order.

    ``net_cost`` is slippage plus commission; ``cash_flow`` is signed cash
    movement (negative for buys, positive for sells).
    """
    fills: List[Fill] = []
    simulated_cash = available_cash
    # Execute sells before buys; buys may be partially filled when a gap or fee
    # makes their decision-time notional unaffordable at the actual fill.
    execution_orders = sorted(orders, key=lambda item: item.shares > 0) if available_cash is not None else orders
    for order in execution_orders:
        base_price = float(fill_prices[order.ticker])
        if not isfinite(base_price) or base_price <= 0 or order.shares == 0:
            continue
        sign = 1 if order.shares > 0 else -1
        fill_price = base_price * (1 + sign * slippage_bps / 10000)
        shares = order.shares
        if shares > 0 and simulated_cash is not None:
            shares = min(shares, max(0.0, (simulated_cash - commission) / fill_price))
            if shares <= 0:
                continue
        gross_value = abs(shares) * fill_price
        slippage_cost = abs(shares) * abs(fill_price - base_price)
        net_cost = slippage_cost + commission
        cash_flow = -gross_value - commission if shares > 0 else gross_value - commission

        fills.append(
            Fill(
                ticker=order.ticker,
                shares=shares,
                fill_price=fill_price,
                fill_date=fill_date,
                commission=commission,
                slippage_cost=slippage_cost,
                gross_value=gross_value,
                net_cost=net_cost,
                cash_flow=cash_flow,
            )
        )
        if simulated_cash is not None:
            simulated_cash += cash_flow

    return fills
