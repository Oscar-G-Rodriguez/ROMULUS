"""
Pick a champion challenger per timeframe using leaderboard.

Rule
- Choose row with highest avg_IC (break ties by lower avg_RMSE).
- Persist full artifact locators including param_id and params.

Writes:
- data/registry/champions.json
"""

import os
import json
import numpy as np
import pandas as pd
from typing import Dict, Any

from ..utils.io_utils import ensure_dir, save_json

METRICS_DIR = "data/results/metrics"
REGISTRY    = "data/registry/champions.json"

def _choose(df: pd.DataFrame) -> Dict[str, Any]:
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
    if not os.path.exists(METRICS_DIR):
        print("No metrics dir.")
        return

    champions = {}
    tfs = [d for d in os.listdir(METRICS_DIR) if os.path.isdir(os.path.join(METRICS_DIR, d))]
    for tf in tfs:
        lb_path = os.path.join(METRICS_DIR, tf, "leaderboard.parquet")
        if not os.path.exists(lb_path):
            print(f"Skip {tf}: no leaderboard")
            continue
        df = pd.read_parquet(lb_path)
        if df.empty:
            continue
        champions[tf] = _choose(df)

    ensure_dir(os.path.dirname(REGISTRY))
    save_json(champions, REGISTRY)
    print(f"Wrote champions -> {REGISTRY}")


main()
