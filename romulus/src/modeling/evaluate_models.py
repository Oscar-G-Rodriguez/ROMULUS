"""
Consolidate challenger metrics to a leaderboard per timeframe.
Keeps (family, param_id, params) so we can promote precise artifacts.
"""

import os
import json
import numpy as np
import pandas as pd
from typing import Dict, Any, List

from ..utils.io_utils import ensure_dir, save_json

METRICS_DIR = "data/results/metrics"

def _load_metrics(tf: str) -> List[Dict[str, Any]]:
    path = os.path.join(METRICS_DIR, tf, "metrics.jsonl")
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows

def main() -> None:
    if not os.path.exists(METRICS_DIR):
        print("No metrics directory.")
        return
    tfs = [d for d in os.listdir(METRICS_DIR) if os.path.isdir(os.path.join(METRICS_DIR, d))]

    for tf in tfs:
        metrics = _load_metrics(tf)
        if not metrics:
            print(f"No metrics for {tf}")
            continue

        df = pd.DataFrame(metrics)
        # Rank: highest avg_IC, then lowest avg_RMSE
        df["rank_key"] = list(zip(-df["avg_IC"].fillna(-np.inf), df["avg_RMSE"].fillna(np.inf)))
        df = df.sort_values("rank_key").drop(columns=["rank_key"]).reset_index(drop=True)
        df["rank"] = np.arange(1, len(df) + 1)

        out_dir = os.path.join(METRICS_DIR, tf)
        ensure_dir(out_dir)
        lb_path = os.path.join(out_dir, "leaderboard.parquet")
        df.to_parquet(lb_path, index=False)

        # Write top-1 per family summaries (optional)
        for fam in df["family"].unique():
            top = df[df["family"] == fam].iloc[0].to_dict()
            save_json(top, os.path.join(out_dir, f"{fam}_summary.json"))

        print(f"[{tf}] wrote leaderboard -> {lb_path}")

    print("Evaluation consolidation complete.")


main()
