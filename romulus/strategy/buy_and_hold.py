"""Buy-and-hold benchmark with no scheduled rebalancing after entry."""

from __future__ import annotations

from datetime import date
from typing import Dict, List

import pandas as pd

from romulus.strategy.base import BaseStrategy


class BuyAndHoldStrategy(BaseStrategy):
    """Buy the initially eligible universe equally, then preserve its drift.

    Assets that become ineligible are omitted and therefore liquidated by the
    engine. Later entrants are not added, keeping this distinct from the
    periodically rebalanced equal-weight benchmark.
    """

    def compute_target_weights(
        self,
        as_of_date: date,
        eligible_tickers: List[str],
        prices: pd.DataFrame,
        positions: Dict[str, float],
    ) -> Dict[str, float]:
        held = {
            ticker: shares
            for ticker, shares in positions.items()
            if shares > 0 and ticker in eligible_tickers
        }
        if not held:
            if not eligible_tickers:
                return {}
            weight = 1.0 / len(eligible_tickers)
            return {ticker: weight for ticker in eligible_tickers}

        values: Dict[str, float] = {}
        for ticker, shares in held.items():
            try:
                series = pd.to_numeric(prices[(ticker, "Close")], errors="coerce").dropna()
                mark = float(series.iloc[-1])
            except (KeyError, IndexError, TypeError, ValueError):
                continue
            if mark > 0:
                values[ticker] = shares * mark
        total = sum(values.values())
        return {ticker: value / total for ticker, value in values.items()} if total > 0 else {}
