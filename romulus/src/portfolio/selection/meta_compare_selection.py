"""
Pick Selection Champion (per decision timeframe) and write registry.

Writes:
- data/registry/selection_champion.json
"""

import os
import json
import numpy as np
import pandas as pd
from ...utils.io_utils import ensure_dir, save_json

SEL_METRICS_DIR = "data/results/selection_metrics"
REG_PATH        = "data/registry/selection_champion.json"

def _choose(df: pd.DataFrame):
    df = df.copy()
    df["rank_key"] = list(zip(-df["avg_IC"].fillna(-np.inf), df["avg_RMSE"].fillna(np.inf)))
    df = df.sort_values("rank_key").drop(columns=["rank_key"]).reset_index(drop=True)
    best = df.iloc[0].to_dict()
    return {
        "timeframe": best["timeframe"],
        "family": best["family"],
        "param_id": best["param_id"],
        "params": best.get("params", {}),
        "target": best["target"],
        "avg_IC": best["avg_IC"],
        "avg_RMSE": best["avg_RMSE"],
        "model_path": best["model_path"],
        "oof_path": best["oof_path"],
        "features": best.get("features", []),
    }

def main() -> None:
    if not os.path.exists(SEL_METRICS_DIR):
        print("No selection metrics dir.")
        return
    tfs = [d for d in os.listdir(SEL_METRICS_DIR) if os.path.isdir(os.path.join(SEL_METRICS_DIR, d))]

    registry = {}
    for tf in tfs:
        lb = os.path.join(SEL_METRICS_DIR, tf, "leaderboard.parquet")
        if not os.path.exists(lb):
            print(f"Skip selection {tf}: no leaderboard")
            continue
        df = pd.read_parquet(lb)
        if df.empty:
            continue
        registry[tf] = _choose(df)

    if not registry:
        print("No selection champions.")
        return

    ensure_dir(os.path.dirname(REG_PATH))
    save_json(registry, REG_PATH)
    print(f"Wrote selection champion -> {REG_PATH}")

main()
