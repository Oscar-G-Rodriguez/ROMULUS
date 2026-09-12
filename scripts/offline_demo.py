"""Run the deterministic, network-free ROMULUS meta-strategy demonstration.

The generated results are synthetic mechanics evidence, not investment results.
"""

from __future__ import annotations

import json
from pathlib import Path

from romulus.backtest.suite import SuiteRunner
from romulus.config.schema import (
    BacktestSettings,
    CostConfig,
    DataConfig,
    ExecutionConfig,
    LeaderboardConfig,
    MetaConfig,
    MLConfig,
    SuiteConfig,
    SuiteOutputConfig,
    SuiteStrategyConfig,
    UniverseConfig,
    WarmupConfig,
)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output_root = root / "outputs" / "offline_demo"
    fixture_root = output_root / "fixture"
    fixture_root.mkdir(parents=True, exist_ok=True)
    universe_path = fixture_root / "universe.json"
    universe_path.write_text(
        json.dumps(
            {
                "etfs": [
                    {"ticker": ticker, "name": f"Synthetic {ticker}", "inception_date": "2000-01-01"}
                    for ticker in ("SPY", "QQQ", "TLT", "GLD", "DBC")
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    xgb = {
        "model_family": "xgboost",
        "device": "auto",
        "min_train_rows": 80,
        "refit_frequency": "every_n_decisions",
        "refit_n": 20,
        "xgb_params": {"n_estimators": 24, "max_depth": 2},
    }
    config = SuiteConfig(
        backtest=BacktestSettings(
            name="ROMULUS deterministic meta demonstration",
            start_date="2023-01-03",
            end_date="2024-12-31",
            initial_cash=10_000.0,
        ),
        universe=UniverseConfig(source=str(universe_path)),
        strategies=[
            SuiteStrategyConfig(name="cash_only", type="cash_only"),
            SuiteStrategyConfig(name="buy_and_hold", type="buy_and_hold"),
            SuiteStrategyConfig(name="equal_weight", type="equal_weight"),
            SuiteStrategyConfig(name="inv_vol", type="inv_vol"),
            SuiteStrategyConfig(name="ts_mom", type="ts_mom"),
            SuiteStrategyConfig(name="xsec_mom", type="xsec_mom"),
            SuiteStrategyConfig(name="vol_target", type="vol_target"),
            SuiteStrategyConfig(name="ma_crossover", type="ma_crossover"),
            SuiteStrategyConfig(name="ml_return_xgb", type="ml_return", params=xgb),
            SuiteStrategyConfig(name="ml_vol_xgb", type="ml_vol", params=xgb),
            SuiteStrategyConfig(name="ml_rar_xgb", type="ml_risk_adjusted", params=xgb),
            SuiteStrategyConfig(
                name="ml_rar_ridge",
                type="ml_risk_adjusted",
                params={"model_family": "ridge", "device": "cpu", "min_train_rows": 80, "refit_frequency": "every_n_decisions", "refit_n": 20},
            ),
        ],
        execution=ExecutionConfig(min_order_notional=0.0, turnover_cap=0.35),
        costs=CostConfig(commission_per_trade=1.0, slippage_bps=5.0),
        data=DataConfig(source="synthetic", cache_dir=str(fixture_root / "cache")),
        output=SuiteOutputConfig(run_dir=str(output_root / "suite_runs")),
        warmup=WarmupConfig(enabled=False),
        leaderboard=LeaderboardConfig(window=20, regime_min_periods=4),
        meta=MetaConfig(enabled=True, selection_day="friday", switch_margin=0.10),
        ml=MLConfig(embargo_intervals=1),
    )
    result = SuiteRunner().run(config)
    print(f"Offline meta-demo artifacts: {result['output_path']}")
    print("Synthetic input only; reported metrics are not investment results.")


if __name__ == "__main__":
    main()
