"""
Unit tests for the configuration module.
"""

import json
import tempfile
from pathlib import Path

import pytest
import yaml

from romulus.config import (
    BacktestConfig,
    CostConfig,
    ExecutionConfig,
    UniverseConfig,
    load_config,
)


class TestConfigLoading:
    """Tests for configuration loading and validation."""

    def test_config_loads_successfully(self):
        """Test that the default config file loads without errors."""
        config = load_config("configs/etf_equal_weight.yaml")

        # Verify it returns a BacktestConfig instance
        assert isinstance(config, BacktestConfig)

        # Verify key fields are loaded correctly
        assert config.backtest.name == "ETF Equal Weight Baseline"
        assert config.backtest.start_date == "2010-01-01"
        assert config.backtest.end_date == "2024-12-31"
        assert config.backtest.initial_cash == 10000.0

        # Verify universe source
        assert config.universe.source == "configs/universe_default.json"

        # Verify strategy
        assert config.strategy.type == "equal_weight"

        # Verify execution settings
        assert config.execution.decision_days == ["wednesday", "friday"]
        assert config.execution.decision_time == "close"
        assert config.execution.fill_time == "open"
        assert config.execution.fractional_shares is True
        assert config.execution.min_order_notional == 1.0
        assert config.execution.cash_buffer_pct == 0.01
        assert config.execution.max_weight == 0.35
        assert config.execution.turnover_cap == 0.35

        # Verify cost settings
        assert config.costs.commission_per_trade == 0.0
        assert config.costs.slippage_bps == 5.0

        # Verify data settings
        assert config.data.source == "yfinance"
        assert config.data.cache_dir == "data/cache"

        # Verify output settings
        assert config.output.run_dir == "outputs/runs"

    def test_config_file_not_found(self):
        """Test that FileNotFoundError is raised for missing config."""
        with pytest.raises(FileNotFoundError):
            load_config("nonexistent_config.yaml")

    def test_config_with_defaults(self):
        """Test that configs with missing optional fields use defaults."""
        # Create a minimal config
        minimal_config = {
            "backtest": {
                "name": "Minimal Test",
                "start_date": "2020-01-01",
                "end_date": "2020-12-31",
            },
            "universe": {
                "source": "configs/universe_default.json"
            },
            "strategy": {
                "type": "equal_weight"
            }
        }

        # Write to temp file
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', delete=False
        ) as f:
            yaml.dump(minimal_config, f)
            temp_path = f.name

        try:
            config = load_config(temp_path)

            # Verify defaults are applied
            assert config.execution.decision_days == ["wednesday", "friday"]
            assert config.execution.fractional_shares is True
            assert config.costs.commission_per_trade == 0.0
            assert config.costs.slippage_bps == 5.0
            assert config.data.source == "yfinance"
        finally:
            Path(temp_path).unlink()

    def test_invalid_date_format(self):
        """Test that invalid date formats are rejected."""
        invalid_config = {
            "backtest": {
                "name": "Invalid Date Test",
                "start_date": "01/01/2020",  # Wrong format
                "end_date": "2020-12-31",
            },
            "universe": {"source": "test.json"},
            "strategy": {"type": "equal_weight"}
        }

        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', delete=False
        ) as f:
            yaml.dump(invalid_config, f)
            temp_path = f.name

        try:
            with pytest.raises(Exception):  # Pydantic ValidationError
                load_config(temp_path)
        finally:
            Path(temp_path).unlink()


class TestUniverseConfig:
    """Tests for universe configuration."""

    def test_universe_json_valid_format(self):
        """Test that the default universe JSON has valid format."""
        with open("configs/universe_default.json", 'r') as f:
            universe_data = json.load(f)

        # Verify structure
        assert "etfs" in universe_data
        assert isinstance(universe_data["etfs"], list)
        assert len(universe_data["etfs"]) == 4

        # Verify each ETF has required fields
        required_fields = {"ticker", "name", "inception_date"}
        for etf in universe_data["etfs"]:
            assert required_fields.issubset(etf.keys())

        # Verify specific ETFs
        tickers = [etf["ticker"] for etf in universe_data["etfs"]]
        assert set(tickers) == {"SPY", "QQQ", "IWM", "TLT"}


class TestCostConfig:
    """Tests for cost configuration."""

    def test_cost_config_defaults(self):
        """Test that cost config has sensible defaults."""
        cost_config = CostConfig()
        assert cost_config.commission_per_trade == 0.0
        assert cost_config.slippage_bps == 5.0

    def test_cost_config_validation(self):
        """Test that negative costs are rejected."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            CostConfig(commission_per_trade=-1.0)

        with pytest.raises(Exception):
            CostConfig(slippage_bps=-5.0)


class TestExecutionConfig:
    """Tests for execution configuration."""

    def test_execution_config_defaults(self):
        """Test that execution config has correct defaults."""
        exec_config = ExecutionConfig()
        assert exec_config.decision_days == ["wednesday", "friday"]
        assert exec_config.decision_time == "close"
        assert exec_config.fill_time == "open"
        assert exec_config.fractional_shares is True
        assert exec_config.min_order_notional == 1.0
        assert exec_config.cash_buffer_pct == 0.01
        assert exec_config.max_weight == 0.35
        assert exec_config.turnover_cap == 0.35

    def test_cash_buffer_validation(self):
        """Test that cash buffer must be between 0 and 1."""
        # Valid values
        ExecutionConfig(cash_buffer_pct=0.0)
        ExecutionConfig(cash_buffer_pct=0.5)
        ExecutionConfig(cash_buffer_pct=1.0)

        # Invalid values
        with pytest.raises(Exception):
            ExecutionConfig(cash_buffer_pct=-0.1)

        with pytest.raises(Exception):
            ExecutionConfig(cash_buffer_pct=1.5)
