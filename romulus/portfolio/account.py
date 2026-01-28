"""Portfolio account tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
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
        return sum(self.positions.get(ticker, 0.0) * price for ticker, price in prices.items())

    def get_total_value(self, prices: Dict[str, float]) -> float:
        """Compute total portfolio value (cash + market value)."""
        return self.cash + self.compute_market_value(prices)

    def apply_fills(self, fills: List["Fill"]) -> None:
        """Apply fills to update cash and positions."""
        for fill in fills:
            fees = fill.commission + fill.slippage_cost
            if fill.shares > 0:
                self.cash -= fill.gross_value + fees
            else:
                self.cash += fill.gross_value - fees
            self.positions[fill.ticker] = self.positions.get(fill.ticker, 0.0) + fill.shares
