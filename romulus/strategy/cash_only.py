"""Cash-only strategy."""

from __future__ import annotations

from datetime import date
from typing import Dict, List

import pandas as pd

from romulus.strategy.base import BaseStrategy


class CashOnlyStrategy(BaseStrategy):
    """Stay entirely in cash."""

    def compute_target_weights(
        self,
        as_of_date: date,
        eligible_tickers: List[str],
        prices: pd.DataFrame,
        positions: Dict[str, float],
    ) -> Dict[str, float]:
        """Return no asset weights (cash only)."""
        return {}
