"""Performance metrics for backtests."""

from __future__ import annotations

from math import sqrt
from typing import Dict

import pandas as pd


def compute_metrics(portfolio_value: pd.Series) -> Dict[str, float]:
    """Compute performance metrics from a portfolio value series."""
    if portfolio_value.empty:
        return {
            "total_return": 0.0,
            "cagr": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "final_value": 0.0,
            "initial_value": 0.0,
        }

    initial_value = float(portfolio_value.iloc[0])
    final_value = float(portfolio_value.iloc[-1])
    total_return = (final_value - initial_value) / initial_value * 100
    num_years = len(portfolio_value) / 252
    cagr = ((final_value / initial_value) ** (1 / num_years) - 1) * 100

    returns = portfolio_value.pct_change().dropna()
    returns_std = returns.std()
    sharpe = (
        returns.mean() / returns_std * sqrt(252)
        if returns_std > 0
        else 0.0
    )

    running_max = portfolio_value.cummax()
    drawdown = (portfolio_value - running_max) / running_max
    max_drawdown = drawdown.min() * 100

    return {
        "total_return": float(total_return),
        "cagr": float(cagr),
        "sharpe": float(sharpe),
        "max_drawdown": float(max_drawdown),
        "final_value": final_value,
        "initial_value": initial_value,
    }
