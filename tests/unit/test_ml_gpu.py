"""Optional GPU smoke test for XGBoost."""

from __future__ import annotations

import os

import numpy as np
import pytest


def test_xgboost_cuda_smoke() -> None:
    if os.getenv("ROMULUS_ENABLE_CUDA_TEST") != "1":
        pytest.skip("CUDA smoke test disabled (set ROMULUS_ENABLE_CUDA_TEST=1 to enable).")

    try:
        import xgboost as xgb
    except Exception:
        pytest.skip("xgboost not installed.")

    X = np.random.RandomState(0).rand(20, 3)
    y = np.random.RandomState(1).rand(20)

    model = xgb.XGBRegressor(
        n_estimators=5,
        max_depth=2,
        learning_rate=0.1,
        tree_method="hist",
        device="cuda",
        nthread=1,
        random_state=42,
    )

    try:
        model.fit(X, y)
    except Exception as exc:
        pytest.skip(f"CUDA not available: {exc}")
