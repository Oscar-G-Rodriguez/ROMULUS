"""Walk-forward forecast-evaluation tests."""

from __future__ import annotations

from romulus.backtest.suite import SuiteRunner


def test_walk_forward_evaluation_reports_naive_and_ridge_references() -> None:
    forecasts = [
        {"strategy": "ridge", "model_family": "ridge", "decision_date": "2024-01-03", "ticker": "AAA", "mu": 0.02, "sigma": 0.01, "score": 2.0, "actual_return": 0.01, "actual_volatility": 0.02, "actual_rar": 0.5},
        {"strategy": "ridge", "model_family": "ridge", "decision_date": "2024-01-03", "ticker": "BBB", "mu": -0.01, "sigma": 0.02, "score": -0.5, "actual_return": -0.02, "actual_volatility": 0.03, "actual_rar": -0.67},
        {"strategy": "ridge", "model_family": "ridge", "decision_date": "2024-01-05", "ticker": "AAA", "mu": 0.01, "sigma": 0.02, "score": 0.5, "actual_return": 0.02, "actual_volatility": 0.02, "actual_rar": 1.0},
        {"strategy": "ridge", "model_family": "ridge", "decision_date": "2024-01-05", "ticker": "BBB", "mu": -0.02, "sigma": 0.03, "score": -0.67, "actual_return": -0.01, "actual_volatility": 0.02, "actual_rar": -0.5},
    ]
    report = SuiteRunner._build_ml_evaluation(forecasts)

    assert report["status"] == "evaluated"
    assert "ridge" in report["ridge_reference"]
    metrics = report["strategies"]["ridge"]
    assert metrics["return"]["walk_forward_model"]["observations"] == 4
    assert metrics["return"]["naive_zero_baseline"]["mae"] > 0
    assert metrics["return"]["naive_persistence_baseline"]["observations"] == 2
    assert metrics["volatility"]["walk_forward_model"]["observations"] == 4
    assert metrics["volatility"]["by_split"]
    assert metrics["rar"]["top_selection_hit_rate"] == 1.0
    assert metrics["rar"]["by_split"]
