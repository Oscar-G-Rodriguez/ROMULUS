"""Cost model utilities."""

from __future__ import annotations


def compute_slippage(shares: float, price: float, slippage_bps: float) -> float:
    """Compute slippage cost for a trade."""
    return abs(shares) * price * (slippage_bps / 10000)


def compute_commission(shares: float, commission_per_trade: float) -> float:
    """Compute commission cost for a trade."""
    return commission_per_trade if abs(shares) > 0 else 0.0
