"""Strategy module for ROMULUS."""

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
from romulus.strategy.ml import MLRiskAdjustedStrategy, MLReturnStrategy, MLVolStrategy
from romulus.strategy.registry import create_strategy, get_strategy_registry

__all__ = [
    "BaseStrategy",
    "CashOnlyStrategy",
    "EqualWeightStrategy",
    "InvVolStrategy",
    "TsMomStrategy",
    "XSecMomStrategy",
    "VolTargetStrategy",
    "MaCrossoverStrategy",
    "EnsembleFixedStrategy",
    "MLReturnStrategy",
    "MLVolStrategy",
    "MLRiskAdjustedStrategy",
    "create_strategy",
    "get_strategy_registry",
]
