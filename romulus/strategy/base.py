"""Base strategy interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Dict, List

import pandas as pd


class BaseStrategy(ABC):
    """Abstract base class for strategies."""

    @abstractmethod
    def compute_target_weights(
        self,
        as_of_date: date,
        eligible_tickers: List[str],
        prices: pd.DataFrame,
        positions: Dict[str, float],
    ) -> Dict[str, float]:
        """Return target weights where sum(weights) <= 1.0. Only allocate to eligible_tickers."""
        raise NotImplementedError
