"""
Configuration schema definitions using Pydantic.

This module defines the configuration models for the ROMULUS backtesting engine.
All configuration files are validated against these schemas.
"""

from datetime import date
from pathlib import Path
from typing import List, Literal, Optional

import yaml
from pydantic import BaseModel, Field, field_validator


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

    source: Literal["yfinance"] = Field(
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


class OutputConfig(BaseModel):
    """Configuration for output files."""

    run_dir: str = Field(
        default="outputs/runs",
        description="Base directory for backtest outputs"
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
