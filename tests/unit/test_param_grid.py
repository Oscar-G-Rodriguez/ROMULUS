"""Unit tests for param grid expansion."""

from __future__ import annotations

from romulus.backtest.suite import SuiteRunner
from romulus.config.schema import MLConfig, SuiteStrategyConfig


def test_param_grid_expansion_is_deterministic() -> None:
    runner = SuiteRunner()
    strategies = [
        SuiteStrategyConfig(
            name="xsec_mom",
            type="xsec_mom",
            params={"weighting": "equal"},
            param_grid={
                "lookback_days": [21, 63],
                "top_k": [2, 4],
            },
        )
    ]

    expanded = runner._expand_strategy_specs(strategies, MLConfig())
    names = [spec["name"] for spec in expanded]

    assert names == [
        "xsec_mom_lookback_days=21_top_k=2",
        "xsec_mom_lookback_days=21_top_k=4",
        "xsec_mom_lookback_days=63_top_k=2",
        "xsec_mom_lookback_days=63_top_k=4",
    ]
