"""Read-only presenters for ROMULUS desktop views and tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class RunPresenter:
    """Turn one immutable run directory into UI-ready rows."""

    def __init__(self, run_path: str | Path) -> None:
        self.run_path = Path(run_path)
        self.manifest = read_json(self.run_path / "manifest.json", {})
        self.summary = read_json(self.run_path / "suite_summary.json", {})
        self.ml = read_json(self.run_path / "ml_evaluation.json", {})
        self.meta_log = read_jsonl(self.run_path / "meta" / "decision_log.jsonl")

    def overview_rows(self) -> list[dict]:
        comparison = self.summary.get("comparison")
        if comparison is None:
            comparison = list(self.summary.get("strategies", {}).values())
            if self.summary.get("meta"):
                comparison.append(self.summary["meta"])
        rows = []
        for item in comparison or []:
            metrics = item.get("metrics", {})
            rows.append({"strategy": item.get("strategy"), **metrics})
        return rows

    def champion_rows(self) -> list[dict]:
        return [row for row in self.meta_log if not row.get("skipped")]

    def equity_series(self) -> dict[str, list[tuple[str, float]]]:
        series: dict[str, list[tuple[str, float]]] = {}
        strategy_names = [str(row.get("strategy")) for row in self.overview_rows()]
        for name in strategy_names:
            rows = self.meta_log if name == "meta" else read_jsonl(self.run_path / name / "decision_log.jsonl")
            points = [
                (str(row["fill_date"]), float(row["portfolio_value_after"]))
                for row in rows
                if row.get("fill_date") and row.get("portfolio_value_after") is not None
            ]
            if points:
                series[name] = points
        return series

    def ml_rows(self) -> list[dict]:
        rows = []
        for strategy, details in self.ml.get("strategies", {}).items():
            base = {"strategy": strategy, "model_family": details.get("model_family")}
            returns = details.get("return", {})
            for series_name in ("walk_forward_model", "naive_zero_baseline", "naive_persistence_baseline"):
                metrics = returns.get(series_name)
                if metrics:
                    rows.append({**base, "target": "return", "split": "all", "series": series_name, **metrics})
            for split, metrics in returns.get("by_split", {}).items():
                rows.append({**base, "target": "return", "split": split, "series": "walk_forward_model", **metrics})

            volatility = details.get("volatility", {})
            for series_name in ("walk_forward_model", "naive_persistence_baseline"):
                metrics = volatility.get(series_name)
                if metrics:
                    rows.append({**base, "target": "volatility", "split": "all", "series": series_name, **metrics})
            for split, metrics in volatility.get("by_split", {}).items():
                rows.append({**base, "target": "volatility", "split": split, "series": "walk_forward_model", **metrics})

            rar = details.get("rar", {})
            if rar.get("rank_diagnostics"):
                rows.append({
                    **base,
                    "target": "rar",
                    "split": "all",
                    "series": "walk_forward_model",
                    **rar["rank_diagnostics"],
                    "top_selection_hit_rate": rar.get("top_selection_hit_rate"),
                })
            for split, metrics in rar.get("by_split", {}).items():
                rows.append({**base, "target": "rar", "split": split, "series": "walk_forward_model", **metrics})
        return rows

    def decision_audit(self, decision_date: str) -> dict:
        meta = next((row for row in self.meta_log if row.get("decision_date") == decision_date), {})
        leaderboard_path = self.run_path / "leaderboard.csv"
        leaderboard = []
        if leaderboard_path.exists():
            frame = pd.read_csv(leaderboard_path)
            leaderboard = frame.loc[frame["decision_date"].astype(str) == decision_date].to_dict("records")
        selected = meta.get("selected_strategy")
        strategy_log = read_jsonl(self.run_path / str(selected) / "decision_log.jsonl") if selected else []
        strategy_decision = next((row for row in strategy_log if row.get("decision_date") == decision_date), {})
        trades_path = self.run_path / "meta" / "trades.csv"
        trades = []
        if trades_path.exists():
            frame = pd.read_csv(trades_path)
            if "decision_date" in frame:
                trades = frame.loc[frame["decision_date"].astype(str) == decision_date].to_dict("records")
        return {
            "meta": meta,
            "leaderboard": leaderboard,
            "strategy_decision": strategy_decision,
            "trades": trades,
        }

    def status_text(self) -> str:
        status = self.manifest.get("status", "unknown")
        coverage = self.manifest.get("data_coverage", {})
        return (
            f"Status: {status}\n"
            f"Run: {self.manifest.get('run_id', self.run_path.name)}\n"
            f"Config hash: {self.manifest.get('config_hash', 'n/a')}\n"
            f"Coverage: {coverage.get('minimum_date', 'n/a')} to {coverage.get('maximum_date', 'n/a')}"
        )
