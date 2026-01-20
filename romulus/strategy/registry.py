"""Strategy registry and factory helpers."""

from __future__ import annotations

from typing import Dict, Tuple, Type

from romulus.strategy.base import BaseStrategy
from romulus.strategy.cash_only import CashOnlyStrategy
from romulus.strategy.deterministic import (
    InvVolStrategy,
    MaCrossoverStrategy,
    TsMomStrategy,
    VolTargetStrategy,
    XSecMomStrategy,
)
from romulus.strategy.ensemble import EnsembleFixedStrategy
from romulus.strategy.equal_weight import EqualWeightStrategy
from romulus.strategy.ml import (
    MLRiskAdjustedStrategy,
    MLReturnStrategy,
    MLVolStrategy,
)

StrategyEntry = Tuple[Type[BaseStrategy], str]


def get_strategy_registry() -> Dict[str, StrategyEntry]:
    return {
        "equal_weight": (EqualWeightStrategy, "Equal-weight allocation across eligible tickers."),
        "cash_only": (CashOnlyStrategy, "Hold 100% cash."),
        "inv_vol": (InvVolStrategy, "Inverse volatility weighting."),
        "ts_mom": (TsMomStrategy, "Time-series momentum with defensive cash."),
        "xsec_mom": (XSecMomStrategy, "Cross-sectional momentum with defensive cash."),
        "vol_target": (VolTargetStrategy, "Volatility targeting with cash scaling."),
        "ma_crossover": (MaCrossoverStrategy, "Moving average crossover trend filter."),
        "ensemble_fixed": (EnsembleFixedStrategy, "Blend child strategies with fixed weights."),
        "ml_return": (MLReturnStrategy, "ML forecast of next-interval returns."),
        "ml_vol": (MLVolStrategy, "ML forecast of next-interval volatility."),
        "ml_risk_adjusted": (MLRiskAdjustedStrategy, "ML risk-adjusted return forecasting."),
    }


def create_strategy(strategy_type: str, params: dict | None = None) -> BaseStrategy:
    registry = get_strategy_registry()
    if strategy_type not in registry:
        raise ValueError(f"Unknown strategy type: {strategy_type}")
    cls = registry[strategy_type][0]
    params = params or {}
    return cls(**params)
