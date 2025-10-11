"""
Turn model (selection champion) predictions into portfolio target weights.

Primary flow (V1)
1) Load Selection Champion (decision timeframe) registry:
     data/registry/selection_champion.json
2) Load its OOF predictions and take the most recent cross-section as the
   decision snapshot (for live this will point to live preds).
3) Convert cross-sectional scores → preliminary weights (rank mapping).
4) Apply risk controls (exposure caps, turnover, neutrality, targeting).
5) Optionally refine with a simple optimizer (risk parity / mean-variance).
6) Write targets to data/results/targets/YYYY-MM-DD/targets.parquet

Fallback
- If no selection champion is available yet, combine value-model champions’
  OOF scores across timeframes (equal-weight) and proceed.

Notes
- This module does not submit orders; it only emits target weights.
- Execution (paper/live) will consume the targets to create orders.
"""

import os
import glob
import json
from typing import Dict, Any, List

import numpy as np
import pandas as pd

from ..utils.io_utils import ensure_dir, load_json, load_configs
from .risk_controls import apply_risk_controls
from .optimizer import refine_weights

# Registries and data roots
VAL_CHAMPIONS_REG = "data/registry/champions.json"           # value-model champions
SEL_CHAMPION_REG  = "data/registry/selection_champion.json"  # selection champion
OOF_ROOT          = "data/processed/oof"
SEL_OOF_ROOT      = "data/processed/selection_oof"
FEAT_ROOT         = "data/processed/features_sel"
OUT_ROOT          = "data/results/targets"


def _latest_timestamp(df: pd.DataFrame, col: str = "timestamp") -> pd.Timestamp:
    if df.empty or col not in df.columns:
        return None
    ts = pd.to_datetime(df[col]).dt.tz_localize(None)
    return ts.max() if len(ts) else None


def _load_selection_champion(decision_tf: str) -> Dict[str, Any]:
    if not os.path.exists(SEL_CHAMPION_REG):
        return {}
    reg = load_json(SEL_CHAMPION_REG) or {}
    return reg.get(decision_tf, {})


def _load_selection_oof(decision_tf: str, fam_pid: str) -> pd.DataFrame:
    p = os.path.join(SEL_OOF_ROOT, decision_tf, f"{fam_pid}.parquet")
    if not os.path.exists(p):
        return pd.DataFrame()
    df = pd.read_parquet(p)
    df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
    df["ticker"] = df["ticker"].str.upper()
    return df[["timestamp", "ticker", "pred"]]


def _latest_xs_from_selection(decision_tf: str) -> pd.DataFrame:
    """
    Returns DataFrame [ticker, score] at the most recent decision timestamp
    produced by the Selection Champion.
    """
    meta = _load_selection_champion(decision_tf)
    if not meta:
        return pd.DataFrame()
    fam_pid = f"{meta['family']}__{meta['param_id']}"
    oof = _load_selection_oof(decision_tf, fam_pid)
    if oof.empty:
        return pd.DataFrame()
    t_last = _latest_timestamp(oof)
    if t_last is None:
        return pd.DataFrame()
    xs = oof[oof["timestamp"] == t_last][["ticker", "pred"]].copy()
    xs = xs.rename(columns={"pred": "score"})
    return xs.reset_index(drop=True)


def _load_value_champions() -> Dict[str, Any]:
    if not os.path.exists(VAL_CHAMPIONS_REG):
        return {}
    return load_json(VAL_CHAMPIONS_REG) or {}


def _load_value_oof(tf: str, fam_pid: str) -> pd.DataFrame:
    p = os.path.join(OOF_ROOT, tf, f"{fam_pid}.parquet")
    if not os.path.exists(p):
        return pd.DataFrame()
    df = pd.read_parquet(p)
    df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
    df["ticker"] = df["ticker"].str.upper()
    return df[["timestamp", "ticker", "pred"]]


def _latest_xs_from_value_champions() -> pd.DataFrame:
    """
    Fallback: combine value-model champions' latest cross-sections equally.
    """
    champs = _load_value_champions()
    frames: List[pd.DataFrame] = []
    for tf, meta in champs.items():
        fam_pid = f"{meta['family']}__{meta['param_id']}"
        df = _load_value_oof(tf, fam_pid)
        if df.empty:
            continue
        t_last = _latest_timestamp(df)
        if t_last is None:
            continue
        xs = df[df["timestamp"] == t_last][["ticker", "pred"]].copy()
        xs = xs.rename(columns={"pred": f"score_{tf}"})
        frames.append(xs)

    if not frames:
        return pd.DataFrame()

    # Outer-join across timeframes; average available scores
    out = frames[0]
    for f in frames[1:]:
        out = out.merge(f, on="ticker", how="outer")
    score_cols = [c for c in out.columns if c.startswith("score_")]
    out["score"] = out[score_cols].mean(axis=1, skipna=True)
    return out[["ticker", "score"]].dropna(subset=["score"]).reset_index(drop=True)


def _scores_to_weights(scores: pd.DataFrame, method: str = "rank", long_short: bool = True, top_k: int = None) -> pd.DataFrame:
    """
    Map cross-sectional scores to preliminary weights.
    method='rank':
      long_short: ranks map to [-1, 1]
      long-only:  ranks map to [0, 1]
    Optionally sparsify with top_k.
    """
    s = scores.copy()
    if s.empty:
        return pd.DataFrame(columns=["ticker", "w"])
    s["rank"] = s["score"].rank(method="average", na_option="keep")
    n = s["rank"].count()
    if n == 0:
        s["w"] = 0.0
        return s[["ticker", "w"]]

    if long_short:
        s["w"] = (2.0 * (s["rank"] - 1) / (n - 1)) - 1.0 if n > 1 else 0.0
    else:
        s["w"] = (s["rank"] - 1) / (n - 1) if n > 1 else 1.0

    if top_k is not None and top_k > 0 and n > top_k:
        cutoff = s["rank"].nlargest(top_k).min()
        if long_short:
            bottom_cut = s["rank"].nsmallest(top_k).max()
            keep = (s["rank"] >= cutoff) | (s["rank"] <= bottom_cut)
            s.loc[~keep, "w"] = 0.0
        else:
            keep = s["rank"] >= cutoff
            s.loc[~keep, "w"] = 0.0

    denom = s["w"].abs().sum() if long_short else s["w"].clip(lower=0).sum()
    s["w"] = s["w"] / denom if denom and np.isfinite(denom) else 0.0
    return s[["ticker", "w"]]


def main() -> None:
    cfg = load_configs()
    portfolio_cfg = cfg.get("portfolio", {}) or {}
    long_short = bool(portfolio_cfg.get("long_short", True))
    top_k = portfolio_cfg.get("top_k", None)
    decision_tf = (cfg.get("selection", {}) or {}).get("decision_timeframe", "1w")

    # Try selection champion first
    xs = _latest_xs_from_selection(decision_tf)
    if xs.empty:
        print("No selection-champion scores found; falling back to value champions combine.")
        xs = _latest_xs_from_value_champions()
        if xs.empty:
            print("No scores available to rebalance.")
            return

    prelim = _scores_to_weights(xs, method="rank", long_short=long_short, top_k=top_k)

    # Apply risk controls and optional optimizer refinement
    refined = apply_risk_controls(prelim, cfg)
    refined = refine_weights(refined, cfg)

    # Emit targets
    decision_date = pd.Timestamp.today().strftime("%Y-%m-%d")
    out_dir = os.path.join(OUT_ROOT, decision_date)
    ensure_dir(out_dir)
    dst = os.path.join(out_dir, "targets.parquet")
    refined.to_parquet(dst, index=False)
    print(f"Wrote targets -> {dst}")


main()
