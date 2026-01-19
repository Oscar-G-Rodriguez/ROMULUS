"""Equal-weight baseline strategy."""

from __future__ import annotations

from datetime import date
from typing import Dict, List

import pandas as pd

from romulus.strategy.base import BaseStrategy


class EqualWeightStrategy(BaseStrategy):
    """Equal-weight allocation across eligible tickers."""

    def compute_target_weights(
        self,
        as_of_date: date,
        eligible_tickers: List[str],
        prices: pd.DataFrame,
        positions: Dict[str, float],
    ) -> Dict[str, float]:
        """Return equal weights for all eligible tickers."""
        if not eligible_tickers:
            return {}

        weight = 1.0 / len(eligible_tickers)
        return {ticker: weight for ticker in eligible_tickers}
