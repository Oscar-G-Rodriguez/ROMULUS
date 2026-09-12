"""Headless tests for the desktop result presenters."""

import json

import pandas as pd

from romulus.ui.presenters import RunPresenter


def test_presenter_exposes_overview_champion_ml_and_audit(tmp_path) -> None:
    run = tmp_path / "run"
    (run / "meta").mkdir(parents=True)
    (run / "alpha").mkdir()
    (run / "manifest.json").write_text(json.dumps({"status": "completed", "run_id": "demo"}), encoding="utf-8")
    (run / "suite_summary.json").write_text(json.dumps({"comparison": [{"strategy": "meta", "metrics": {"sharpe": 1.0}}]}), encoding="utf-8")
    meta = {"decision_date": "2024-01-05", "selected_strategy": "alpha", "switch_reason": "test"}
    (run / "meta" / "decision_log.jsonl").write_text(json.dumps(meta) + "\n", encoding="utf-8")
    (run / "alpha" / "decision_log.jsonl").write_text(json.dumps({"decision_date": "2024-01-05", "signals": {"x": 1}}) + "\n", encoding="utf-8")
    pd.DataFrame([{"decision_date": "2024-01-05", "strategy": "alpha", "rank": 1}]).to_csv(run / "leaderboard.csv", index=False)
    pd.DataFrame([{"decision_date": "2024-01-05", "ticker": "AAA"}]).to_csv(run / "meta" / "trades.csv", index=False)
    (run / "ml_evaluation.json").write_text(json.dumps({"strategies": {"ml": {"model_family": "xgboost", "return": {"walk_forward_model": {"observations": 2, "mae": 0.1}}}}}), encoding="utf-8")

    presenter = RunPresenter(run)

    assert presenter.overview_rows()[0]["strategy"] == "meta"
    assert presenter.champion_rows()[0]["switch_reason"] == "test"
    assert presenter.ml_rows()[0]["target"] == "return"
    assert presenter.ml_rows()[0]["series"] == "walk_forward_model"
    assert presenter.decision_audit("2024-01-05")["trades"][0]["ticker"] == "AAA"
