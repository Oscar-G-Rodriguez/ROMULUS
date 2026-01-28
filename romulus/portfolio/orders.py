"""Order generation utilities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, List


@dataclass
class Order:
    """Represents an order generated on a decision date."""

    ticker: str
    shares: float
    decision_date: date
    target_weight: float


def generate_orders(
    target_weights: Dict[str, float],
    current_positions: Dict[str, float],
    prices: Dict[str, float],
    cash: float,
    total_value: float,
    min_notional: float,
    cash_buffer_pct: float,
    decision_date: date | None = None,
) -> List[Order]:
    """Generate orders to reach target weights."""
    if decision_date is None:
        decision_date = date.today()

    orders: List[Order] = []
    for ticker, target_weight in target_weights.items():
        price = prices[ticker]
        target_value = target_weight * total_value * (1 - cash_buffer_pct)
        current_value = current_positions.get(ticker, 0.0) * price
        shares_to_trade = 0.0 if price == 0 else (target_value - current_value) / price

        if abs(shares_to_trade * price) < min_notional:
            continue

        orders.append(
            Order(
                ticker=ticker,
                shares=shares_to_trade,
                decision_date=decision_date,
                target_weight=target_weight,
            )
        )

    return orders
