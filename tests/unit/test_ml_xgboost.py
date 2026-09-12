"""Native XGBoost integration tests."""

from __future__ import annotations

import numpy as np

from romulus.strategy.ml import MLReturnStrategy


def test_native_xgboost_cpu_model_fits_and_predicts() -> None:
    rng = np.random.default_rng(42)
    X = rng.normal(size=(64, 5))
    y = 0.4 * X[:, 0] - 0.2 * X[:, 1]
    strategy = MLReturnStrategy(
        model_family="xgboost",
        device="cpu",
        xgb_params={"n_estimators": 8, "max_depth": 2},
    )

    model, device, fallback, params = strategy._train_model(X, y)
    predictions = model.predict(X[:4])

    assert device == "cpu"
    assert fallback is None
    assert params["device"] == "cpu"
    assert params["num_boost_round"] == 8
    assert predictions.shape == (4,)
    assert np.isfinite(predictions).all()
