"""Fixed-weight ensemble strategy."""

from __future__ import annotations

from datetime import date
from typing import Dict, List

import pandas as pd

from romulus.strategy.base import BaseStrategy


class EnsembleFixedStrategy(BaseStrategy):
    """Combine child strategies with fixed blend weights."""

    description = "Blend multiple child strategies with fixed weights."

    def __init__(self, children: List[dict], blend_weight: float | None = None) -> None:
        if not children:
            raise ValueError("EnsembleFixedStrategy requires at least one child")
        from romulus.strategy.registry import create_strategy
        self.children_specs = children
        self.blend_weight = blend_weight
        self.children = []
        self.child_weights = []
        total = 0.0
        for child in children:
            weight = float(child.get("blend_weight", 1.0))
            self.child_weights.append(weight)
            total += weight
            self.children.append(create_strategy(child["type"], child.get("params")))
        if total <= 0:
            raise ValueError("EnsembleFixedStrategy blend weights must sum to > 0")
        self.child_weights = [weight / total for weight in self.child_weights]
        self._last_signals: dict = {}
        self._last_raw_weights: dict = {}

    def set_context(self, context: dict) -> None:
        for child in self.children:
            child.set_context(context)

    def compute_target_weights(
        self,
        as_of_date: date,
        eligible_tickers: List[str],
        prices: pd.DataFrame,
        positions: Dict[str, float],
    ) -> Dict[str, float]:
        combined: Dict[str, float] = {}
        child_details = []
        for child, weight in zip(self.children, self.child_weights):
            child_weights = child.compute_target_weights(
                as_of_date=as_of_date,
                eligible_tickers=eligible_tickers,
                prices=prices,
                positions=positions,
            )
            child_details.append({"weights": child_weights, "blend_weight": weight})
            for ticker, child_weight in child_weights.items():
                combined[ticker] = combined.get(ticker, 0.0) + weight * child_weight

        total = sum(combined.values())
        if total > 1.0:
            combined = {ticker: weight / total for ticker, weight in combined.items()}

        self._last_signals = {"children": child_details}
        self._last_raw_weights = combined
        return combined

    def get_last_signals(self) -> dict:
        return self._last_signals

    def get_last_raw_weights(self) -> dict:
        return self._last_raw_weights
