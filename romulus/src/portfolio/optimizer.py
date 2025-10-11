"""
Weight refinement (optional lightweight optimizers).

refine_weights(weights, cfg) → weights
- If cfg.portfolio.optimizer == "none": return as-is.
- If "riskparity": equal risk contribution using diag vol proxy (V1).
- If "meanvar": shrink toward inverse-vol (diag) blend.

Notes
- V1 uses |w| as a volatility proxy in absence of a full risk model.
- Replace 'vols' with realized/forecasted vols or a covariance model in V2.
"""

from typing import Dict, Any

import numpy as np
import pandas as pd


def _normalize(w: np.ndarray, long_short: bool) -> np.ndarray:
    if long_short:
        s = float(np.sum(np.abs(w)))
        return w / s if s else w
    s = float(np.sum(np.clip(w, 0.0, None)))
    return w / s if s else w


def _risk_parity_diag(vols: np.ndarray, long_short: bool) -> np.ndarray:
    inv = np.divide(1.0, vols, out=np.zeros_like(vols), where=vols > 0)
    if inv.sum() > 0:
        w = inv / inv.sum()
    else:
        w = inv
    if long_short:
        n = len(w)
        half = n // 2
        signs = np.concatenate([np.ones(half), -np.ones(n - half)])
        w = w * signs
    return w


def _mean_variance_diag(w_curr: np.ndarray, vols: np.ndarray, shrink: float = 0.5) -> np.ndarray:
    inv = np.divide(1.0, vols, out=np.zeros_like(vols), where=vols > 0)
    if inv.sum() > 0:
        inv = inv / inv.sum()
    return shrink * w_curr + (1.0 - shrink) * inv


def refine_weights(prelim: pd.DataFrame, cfg: Dict[str, Any]) -> pd.DataFrame:
    """
    prelim: DataFrame [ticker, w]
    """
    rules = cfg.get("portfolio", {}) or {}
    optimizer = (rules.get("optimizer") or "none").lower()
    long_short = bool(rules.get("long_short", True))

    if optimizer == "none" or prelim.empty:
        return prelim

    w = prelim.set_index("ticker")["w"].astype(float)
    # V1 proxy: use |w| as a stand-in for vol; replace with risk model later
    vols = np.maximum(np.abs(w.values), 1e-6)

    if optimizer == "riskparity":
        w_new = _risk_parity_diag(vols, long_short)
    elif optimizer == "meanvar":
        w_new = _mean_variance_diag(w.values, vols, shrink=0.5)
    else:
        return prelim

    w_new = _normalize(w_new, long_short)
    return pd.DataFrame({"ticker": w.index, "w": w_new})
