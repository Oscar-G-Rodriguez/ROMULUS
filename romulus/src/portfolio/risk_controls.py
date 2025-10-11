"""
Risk controls for portfolio targets.

apply_risk_controls(weights, cfg) → weights
  Applies, in order:
    1) Exposure caps (per-name, gross, net)
    2) Beta neutrality (proxy in V1: de-mean weights)
    3) Volatility targeting (proxy in V1 via gross cap already)
    4) Turnover limit vs last targets (if available)

Config (config.yaml)
portfolio:
  long_short: true
  per_name_cap: 0.05
  gross_cap: 1.0
  net_cap: 0.1
  max_turnover: 0.5
"""

import os
from typing import Dict, Any

import numpy as np
import pandas as pd

LAST_TARGETS_DIR = "data/results/targets"


def _load_last_targets() -> pd.DataFrame:
    if not os.path.exists(LAST_TARGETS_DIR):
        return pd.DataFrame()
    sub = [d for d in os.listdir(LAST_TARGETS_DIR) if len(d) >= 8 and d[:4].isdigit()]
    if not sub:
        return pd.DataFrame()
    sub = sorted(sub, reverse=True)
    for s in sub:
        p = os.path.join(LAST_TARGETS_DIR, s, "targets.parquet")
        if os.path.exists(p):
            try:
                df = pd.read_parquet(p)
                return df[["ticker", "w"]].copy()
            except Exception:
                continue
    return pd.DataFrame()


def _cap_exposures(w: pd.Series, per_name: float, gross: float, net: float, long_short: bool) -> pd.Series:
    w = w.clip(lower=-per_name if long_short else 0.0, upper=per_name)
    gross_now = w.abs().sum()
    if gross_now > gross and gross_now > 0:
        w = w * (gross / gross_now)
    net_now = w.sum()
    if abs(net_now) > net and w.abs().sum() > 0:
        shift = (net_now - np.sign(net_now) * net) / len(w)
        w = w - shift
    return w


def _turnover_limit(curr: pd.Series, prev: pd.Series, max_turnover: float) -> pd.Series:
    if prev is None or prev.empty:
        return curr
    aligned_prev = prev.reindex(curr.index).fillna(0.0)
    tv = (curr - aligned_prev).abs().sum()
    if tv <= max_turnover:
        return curr
    lam = max_turnover / tv if tv > 0 else 1.0
    return aligned_prev + lam * (curr - aligned_prev)


def apply_risk_controls(prelim: pd.DataFrame, cfg: Dict[str, Any]) -> pd.DataFrame:
    """
    prelim: DataFrame with columns [ticker, w]
    """
    rules = cfg.get("portfolio", {}) or {}
    long_short   = bool(rules.get("long_short", True))
    per_name_cap = float(rules.get("per_name_cap", 0.05))
    gross_cap    = float(rules.get("gross_cap", 1.0))
    net_cap      = float(rules.get("net_cap", 0.1))
    max_turnover = float(rules.get("max_turnover", 0.5))

    if prelim.empty:
        return prelim

    w = prelim.set_index("ticker")["w"].astype(float).copy()

    # 1) Exposure caps
    w = _cap_exposures(w, per_name_cap, gross_cap, net_cap, long_short)

    # 2) Beta neutrality (proxy): de-mean cross-section for long/short books
    if long_short:
        w = w - w.mean()

    # 3) Vol targeting (proxy): handled implicitly by gross_cap; replace with risk model later

    # 4) Turnover vs last targets
    last = _load_last_targets()
    prev = last.set_index("ticker")["w"] if not last.empty else None
    w = _turnover_limit(w, prev, max_turnover)

    return w.rename("w").reset_index()
