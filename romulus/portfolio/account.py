"""Portfolio account tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from romulus.portfolio.fills import Fill


@dataclass
class Portfolio:
    """Tracks cash balance and positions."""

    cash: float
    positions: Dict[str, float] = field(default_factory=dict)

    def compute_market_value(self, prices: Dict[str, float]) -> float:
        """Compute the market value of current positions."""
        value = 0.0
        for ticker, shares in self.positions.items():
            if shares == 0:
                continue
            if ticker not in prices:
                raise ValueError(f"Missing mark price for held position {ticker}")
            price = float(prices[ticker])
            if not isfinite(price) or price <= 0:
                raise ValueError(f"Invalid mark price for {ticker}: {price}")
            value += shares * price
        return value

    def get_total_value(self, prices: Dict[str, float]) -> float:
        """Compute total portfolio value (cash + market value)."""
        return self.cash + self.compute_market_value(prices)

    def apply_fills(self, fills: List["Fill"]) -> None:
        """Apply fills to update cash and positions."""
        # Sells fund buys. Slippage is already in gross_value through price.
        for fill in sorted(fills, key=lambda item: item.shares > 0):
            cash_flow = fill.cash_flow
            # Backward-compatible support for audited legacy Fill records.
            if cash_flow == 0.0 and fill.shares != 0.0:
                cash_flow = -fill.gross_value - fill.commission if fill.shares > 0 else fill.gross_value - fill.commission
            if fill.shares > 0 and self.cash + cash_flow < -1e-9:
                raise ValueError(f"Insufficient cash for {fill.ticker} fill")
            self.cash += cash_flow
            self.positions[fill.ticker] = self.positions.get(fill.ticker, 0.0) + fill.shares
            if abs(self.positions[fill.ticker]) < 1e-12:
                self.positions.pop(fill.ticker)
