"""
Configuration schema definitions using Pydantic.

This module defines the configuration models for the ROMULUS backtesting engine.
All configuration files are validated against these schemas.
"""

from datetime import date
from pathlib import Path
from typing import List, Literal, Optional

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


class BacktestSettings(BaseModel):
    """Core backtest settings."""

    name: str = Field(description="Human-readable name for the backtest")
    start_date: str = Field(description="Start date in YYYY-MM-DD format")
    end_date: str = Field(description="End date in YYYY-MM-DD format")
    initial_cash: float = Field(default=10000.0, ge=0, description="Starting cash balance")

    @field_validator('start_date', 'end_date')
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        """Validate date string format."""
        try:
            date.fromisoformat(v)
        except ValueError:
            raise ValueError(f"Invalid date format: {v}. Use YYYY-MM-DD.")
        return v


class UniverseConfig(BaseModel):
    """Configuration for the ETF universe."""

    source: str = Field(description="Path to universe JSON file")


class StrategyConfig(BaseModel):
    """Configuration for the trading strategy."""

    type: str = Field(description="Strategy type identifier (e.g., 'equal_weight')")
    params: Optional[dict] = Field(default=None, description="Optional strategy parameters")


class SuiteStrategyConfig(BaseModel):
    """Configuration for a strategy within a suite."""

    name: str = Field(description="Unique strategy name in suite")
    type: str = Field(description="Strategy type identifier (e.g., 'equal_weight')")
    params: Optional[dict] = Field(default=None, description="Optional strategy parameters")
    param_grid: Optional[dict] = Field(
        default=None,
        description="Optional parameter grid for auto-expanding strategies",
    )


class WarmupConfig(BaseModel):
    """Configuration for warmup and rebase."""

    enabled: bool = Field(default=True, description="Whether to run warmup simulation")
    start_date: Optional[str] = Field(default=None, description="Warmup start date in YYYY-MM-DD format")
    rebase: bool = Field(default=True, description="Rebase scored run to warmup weights")

    @field_validator("start_date")
    @classmethod
    def validate_warmup_date_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        try:
            date.fromisoformat(v)
        except ValueError:
            raise ValueError(f"Invalid warmup date format: {v}. Use YYYY-MM-DD.")
        return v


class LeaderboardConfig(BaseModel):
    """Configuration for strategy leaderboard."""

    window: int = Field(default=20, ge=1, description="Rolling window length for metrics")
    dd_limit: float = Field(default=-0.2, description="Max drawdown gate (negative fraction)")
    turnover_limit: float = Field(default=1.0, ge=0, description="Max turnover gate per period")
    regime_min_periods: int = Field(
        default=4,
        ge=0,
        description="Completed matching-regime intervals required before conditional champion scoring; 0 disables it",
    )
    global_weight: float = Field(default=0.60, ge=0, le=1)
    regime_weight: float = Field(default=0.40, ge=0, le=1)

    @model_validator(mode="after")
    def validate_score_weights(self) -> "LeaderboardConfig":
        if self.global_weight + self.regime_weight <= 0:
            raise ValueError("At least one leaderboard score weight must be positive")
        return self


class MetaConfig(BaseModel):
    """Configuration for optional meta-strategy selection."""

    enabled: bool = Field(default=True, description="Enable meta-strategy selection")
    min_periods_before_selection: int = Field(
        default=4,
        ge=0,
        description="Minimum periods before selecting from leaderboard",
    )
    baseline_strategy: str = Field(
        default="equal_weight",
        description="Baseline strategy used before selection begins",
    )
    selection_day: Literal["monday", "tuesday", "wednesday", "thursday", "friday"] = Field(
        default="friday", description="Weekday on which the champion may change"
    )
    switch_margin: float = Field(default=0.10, ge=0, le=1, description="Minimum normalized lead required to replace an eligible incumbent")


class MLConfig(BaseModel):
    """Configuration for expanded ML features in suite runs."""

    expanded: bool = Field(default=False, description="Enable expanded ML features")
    rolling_windows: List[int] = Field(
        default_factory=lambda: [252, 504, 756],
        description="Training window lengths in trading days for rolling runs",
    )
    expanding: bool = Field(default=True, description="Include expanding-window ML variants")
    embargo_intervals: int = Field(
        default=1,
        ge=0,
        description="Number of recent intervals to embargo from training",
    )
    macro_enabled: bool = Field(default=False, description="Enable only point-in-time macro features with availability dates")
    macro_series: Optional[List[str]] = Field(
        default=None,
        description="Optional Nasdaq Data Link series codes (e.g., FRED/GDP)",
    )
    alt_enabled: bool = Field(default=False, description="Enable only point-in-time alt features with availability dates")
    alt_sleep_seconds: float = Field(
        default=1.0,
        ge=0,
        description="Seconds to sleep between pytrends requests",
    )

class ExecutionConfig(BaseModel):
    """Configuration for order execution."""

    decision_days: List[str] = Field(
        default=["wednesday", "friday"],
        description="Days of week to make rebalancing decisions"
    )
    decision_time: Literal["open", "close"] = Field(
        default="close",
        description="Time of day for decision prices"
    )
    fill_time: Literal["open", "close"] = Field(
        default="open",
        description="Time of day for fill prices"
    )
    fractional_shares: bool = Field(
        default=True,
        description="Whether to allow fractional shares"
    )
    min_order_notional: float = Field(
        default=1.0,
        ge=0,
        description="Minimum order value in dollars"
    )
    cash_buffer_pct: float = Field(
        default=0.01,
        ge=0,
        le=1,
        description="Percentage of portfolio to keep as cash buffer"
    )
    max_weight: float = Field(
        default=0.35,
        ge=0,
        le=1,
        description="Maximum weight per ticker"
    )
    turnover_cap: float = Field(
        default=0.35,
        ge=0,
        le=1,
        description="Maximum turnover per rebalance"
    )


class CostConfig(BaseModel):
    """Configuration for transaction costs."""

    commission_per_trade: float = Field(
        default=0.0,
        ge=0,
        description="Fixed commission per trade in dollars"
    )
    slippage_bps: float = Field(
        default=5.0,
        ge=0,
        description="Slippage in basis points"
    )


class DataConfig(BaseModel):
    """Configuration for data sources."""

    source: Literal["yfinance", "cache", "synthetic"] = Field(
        default="yfinance",
        description="Data source provider"
    )
    cache_dir: str = Field(
        default="data/cache",
        description="Directory for caching data"
    )
    adjustment: Literal["split_and_dividend", "none"] = Field(
        default="split_and_dividend",
        description="Price adjustment method"
    )
    coverage_policy: Literal["dynamic", "common"] = Field(
        default="dynamic",
        description="Date-bound policy used by the desktop data inspector",
    )


class OutputConfig(BaseModel):
    """Configuration for output files."""

    run_dir: str = Field(
        default="outputs/runs",
        description="Base directory for backtest outputs"
    )


class SuiteOutputConfig(BaseModel):
    """Configuration for suite output files."""

    run_dir: str = Field(
        default="outputs/suite_runs",
        description="Base directory for suite outputs"
    )


class BacktestConfig(BaseModel):
    """
    Complete backtest configuration.

    This is the top-level configuration model that contains all settings
    for running a backtest.
    """

    backtest: BacktestSettings
    universe: UniverseConfig
    strategy: StrategyConfig
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    costs: CostConfig = Field(default_factory=CostConfig)
    data: DataConfig = Field(default_factory=DataConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)


class SuiteConfig(BaseModel):
    """Configuration for running a strategy suite."""

    backtest: BacktestSettings
    universe: UniverseConfig
    strategies: List[SuiteStrategyConfig]
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    costs: CostConfig = Field(default_factory=CostConfig)
    data: DataConfig = Field(default_factory=DataConfig)
    output: SuiteOutputConfig = Field(default_factory=SuiteOutputConfig)
    warmup: WarmupConfig = Field(default_factory=WarmupConfig)
    leaderboard: LeaderboardConfig = Field(default_factory=LeaderboardConfig)
    meta: MetaConfig = Field(default_factory=MetaConfig)
    ml: MLConfig = Field(default_factory=MLConfig)


def load_config(path: str) -> BacktestConfig:
    """
    Load and validate a backtest configuration from a YAML file.

    Args:
        path: Path to the YAML configuration file.

    Returns:
        Validated BacktestConfig instance.

    Raises:
        FileNotFoundError: If the config file doesn't exist.
        ValidationError: If the config file is invalid.
    """
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(config_path, 'r') as f:
        raw_config = yaml.safe_load(f)

    return BacktestConfig(**raw_config)


def load_suite_config(path: str) -> SuiteConfig:
    """
    Load and validate a suite configuration from a YAML file.

    Args:
        path: Path to the YAML configuration file.

    Returns:
        Validated SuiteConfig instance.
    """
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(config_path, "r") as f:
        raw_config = yaml.safe_load(f)

    return SuiteConfig(**raw_config)
