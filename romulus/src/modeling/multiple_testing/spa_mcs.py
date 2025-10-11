"""
SPA + MCS validation of challengers.

Purpose
-------
Given many challengers with observed performance (avg_IC, avg_RMSE, or daily IC series),
determine which have statistically superior predictive ability.

Implements:
- Superior Predictive Ability (SPA) test (Hansen, 2005)
- Model Confidence Set (MCS) approximation (Hansen, Lunde, Nason, 2011)

Inputs
------
- data/results/metrics/<tf>/metrics.jsonl (from train_models)
  Each record: {"family", "param_id", "avg_IC", "avg_RMSE", ...}

Outputs
-------
- data/results/metrics/<tf>/mcs_results.json
  {"survivors": [list of (family,param_id)], "removed": [list of losers], "threshold": 0.1}

Usage
-----
python -m romulus.src.modeling.multiple_testing.spa_mcs
"""

import os
import json
import numpy as np
import pandas as pd
from typing import List, Dict, Any
from scipy.stats import ttest_rel
from ...utils.io_utils import ensure_dir, save_json

METRICS_DIR = "data/results/metrics"

def _load_metrics(tf: str) -> pd.DataFrame:
    path = os.path.join(METRICS_DIR, tf, "metrics.jsonl")
    if not os.path.exists(path):
        return pd.DataFrame()
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return pd.DataFrame(rows)

def _bootstrap_spa(df: pd.DataFrame, key: str = "avg_IC", n_boot: int = 5000, alpha: float = 0.1) -> List[str]:
    """
    Approximate SPA by bootstrap resampling challenger scores (avg_ICs).
    Returns survivors whose mean performance cannot be rejected as worse than best.
    """
    if df.empty or key not in df.columns:
        return []

    vals = df[key].astype(float).values
    fam_pid = df["family"] + "__" + df["param_id"]
    idx_best = np.nanargmax(vals)
    best_val = vals[idx_best]
    n = len(vals)

    survivors = []
    rng = np.random.default_rng(42)
    diffs = np.zeros((n_boot, n))
    for b in range(n_boot):
        # stationary bootstrap of IC differences vs best
        resample = rng.choice(vals, size=n, replace=True)
        diffs[b, :] = resample - best_val
    pvals = (diffs > 0).mean(axis=0)
    for i in range(n):
        if pvals[i] > alpha:
            survivors.append(fam_pid.iloc[i])
    return survivors

def _pairwise_mcs(df: pd.DataFrame, key: str = "avg_IC", alpha: float = 0.1) -> List[str]:
    """
    Simplified pairwise MCS: iteratively drop the worst until remaining models are not significantly different.
    """
    survivors = df.copy()
    while len(survivors) > 1:
        vals = survivors[key].astype(float).values
        fam_pid = survivors["family"] + "__" + survivors["param_id"]
        # compute pairwise t-tests between best and others
        best_idx = np.nanargmax(vals)
        best_val = vals[best_idx]
        diffs = vals - best_val
        t_stat, pval = ttest_rel(vals, np.full_like(vals, best_val), nan_policy="omit")
        if np.nanmax(pval) > alpha:
            break
        worst_idx = np.nanargmin(vals)
        survivors = survivors.drop(survivors.index[worst_idx])
    return list((survivors["family"] + "__" + survivors["param_id"]).values)

def main() -> None:
    if not os.path.exists(METRICS_DIR):
        print("No metrics directory.")
        return

    tfs = [d for d in os.listdir(METRICS_DIR) if os.path.isdir(os.path.join(METRICS_DIR, d))]
    for tf in tfs:
        df = _load_metrics(tf)
        if df.empty:
            print(f"No metrics for {tf}")
            continue

        survivors_spa = _bootstrap_spa(df, key="avg_IC", n_boot=1000, alpha=0.1)
        survivors_mcs = _pairwise_mcs(df, key="avg_IC", alpha=0.1)
        survivors = sorted(set(survivors_spa).union(set(survivors_mcs)))
        losers = sorted(set((df["family"] + "__" + df["param_id"]).values) - set(survivors))

        result = {"survivors": survivors, "removed": losers, "threshold": 0.1}
        out_path = os.path.join(METRICS_DIR, tf, "mcs_results.json")
        ensure_dir(os.path.dirname(out_path))
        save_json(result, out_path)
        print(f"[{tf}] MCS survivors: {len(survivors)}/{len(df)} -> {out_path}")

    print("SPA/MCS filtering complete.")


main()
