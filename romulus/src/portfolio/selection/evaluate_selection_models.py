"""
Consolidate selection challenger metrics to a leaderboard.
"""

import os
import json
import numpy as np
import pandas as pd
from ...utils.io_utils import ensure_dir, save_json

SEL_METRICS_DIR = "data/results/selection_metrics"

def _load_metrics(tf: str):
    path = os.path.join(SEL_METRICS_DIR, tf, "metrics.jsonl")
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try: rows.append(json.loads(line))
            except Exception: pass
    return rows

def main() -> None:
    if not os.path.exists(SEL_METRICS_DIR):
        print("No selection metrics dir.")
        return
    tfs = [d for d in os.listdir(SEL_METRICS_DIR) if os.path.isdir(os.path.join(SEL_METRICS_DIR, d))]

    for tf in tfs:
        rows = _load_metrics(tf)
        if not rows:
            print(f"No selection metrics for {tf}")
            continue
        df = pd.DataFrame(rows)
        df["rank_key"] = list(zip(-df["avg_IC"].fillna(-np.inf), df["avg_RMSE"].fillna(np.inf)))
        df = df.sort_values("rank_key").drop(columns=["rank_key"]).reset_index(drop=True)
        df["rank"] = np.arange(1, len(df)+1)

        out_dir = os.path.join(SEL_METRICS_DIR, tf)
        ensure_dir(out_dir)
        lb = os.path.join(out_dir, "leaderboard.parquet")
        df.to_parquet(lb, index=False)

        # top-1 summaries per family
        for fam in df["family"].unique():
            top = df[df["family"] == fam].iloc[0].to_dict()
            save_json(top, os.path.join(out_dir, f"{fam}_summary.json"))

        print(f"[selection {tf}] wrote leaderboard -> {lb}")

    print("Selection evaluation consolidation complete.")

main()
