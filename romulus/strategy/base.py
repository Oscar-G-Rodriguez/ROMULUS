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

    def get_last_signals(self) -> dict:
        """Return latest signals used for decision logging."""
        return {}

    def get_last_raw_weights(self) -> dict:
        """Return latest raw weights before constraints."""
        return {}

    def get_last_forecasts(self) -> list[dict]:
        """Return latest ML forecasts for logging."""
        return []

    def get_last_training_info(self) -> dict:
        """Return latest ML training metadata."""
        return {}

    def set_context(self, context: dict) -> None:
        """Inject shared context (prices, schedule, etc.) if needed."""
        return None
