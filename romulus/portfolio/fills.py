"""Fill simulation utilities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
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


def simulate_fills(
    orders: List[Order],
    fill_prices: Dict[str, float],
    fill_date: date,
    slippage_bps: float,
    commission: float,
) -> List[Fill]:
    """Simulate fills with slippage and commission."""
    fills: List[Fill] = []
    for order in orders:
        sign = 1 if order.shares > 0 else -1
        base_price = fill_prices[order.ticker]
        fill_price = base_price * (1 + sign * slippage_bps / 10000)
        gross_value = abs(order.shares) * fill_price
        slippage_cost = gross_value * (slippage_bps / 10000)
        net_cost = gross_value + commission + slippage_cost

        fills.append(
            Fill(
                ticker=order.ticker,
                shares=order.shares,
                fill_price=fill_price,
                fill_date=fill_date,
                commission=commission,
                slippage_cost=slippage_cost,
                gross_value=gross_value,
                net_cost=net_cost,
            )
        )

    return fills
