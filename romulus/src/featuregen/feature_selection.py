"""
Feature selection to prune redundant or weak features.

Modes
1) Unsupervised (default): drop highly correlated features among themselves.
   - Correlation computed per ticker across the available sample.
   - Threshold set in this file (default 0.95) or could be moved to config later.
   - Output: data/processed/features_sel/<tf>/<TICKER>.parquet

2) Supervised (optional): if labels exist at
   data/processed/labels/<tf>/<TICKER>.parquet with column 'y' or 'target',
   compute Information Coefficient (Spearman) per feature and drop those with
   abs(IC) below a threshold (e.g., 0.02). Then apply correlation pruning.

Notes
- We keep 'timestamp' and 'ticker' always.
- This stage doesn’t normalize; it expects features already normalized if desired.
"""

import os
from typing import List, Optional

import pandas as pd
import numpy as np
from scipy.stats import spearmanr

from ..utils.io_utils import ensure_dir

IN_ROOT   = "data/processed/features_norm"     # can switch to features/ if you skip normalization
LABEL_ROOT= "data/processed/labels"            # optional, may not exist yet
OUT_ROOT  = "data/processed/features_sel"

CORR_THRESHOLD = 0.95
IC_THRESHOLD   = 0.02  # abs(IC) minimum to keep (only if labels available)

def _list_timeframes(root: str) -> List[str]:
    return [d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))]

def _load_labels(tf: str, fname: str) -> Optional[pd.Series]:
    path = os.path.join(LABEL_ROOT, tf, fname)
    if not os.path.exists(path):
        return None
    df = pd.read_parquet(path)
    # allow common names
    for col in ("y","target","label"):
        if col in df.columns:
            return pd.Series(df[col].values, index=pd.to_datetime(df["timestamp"]))
    return None

def _corr_prune(df: pd.DataFrame, thresh: float) -> List[str]:
    cols = [c for c in df.columns if c not in ("timestamp", "ticker")]
    if len(cols) <= 1:
        return cols
    mat = df[cols].corr(method="pearson").abs().fillna(0)
    if mat.isna().values.mean() > 0.25:
        return cols  # skip prune if mostly NaNs
    keep = []
    drop = set()
    for i, c in enumerate(cols):
        if c in drop:
            continue
        keep.append(c)
        high = mat.index[(mat[c] > thresh) & (mat.index != c)].tolist()
        drop.update(high)
    return keep


def _ic_prune(df: pd.DataFrame, y: pd.Series, thresh: float) -> List[str]:
    # Align on timestamps and drop rows missing X or y
    x = df.set_index("timestamp")
    x.index = pd.to_datetime(x.index)
    y = y.copy()
    y.index = pd.to_datetime(y.index)

    both = x.join(y.rename("y"), how="inner").dropna()
    # Guard against tiny overlaps; if too few samples, skip IC pruning
    if len(both) < 30:
        return [c for c in df.columns if c not in ("timestamp", "ticker")]

    cols = [c for c in x.columns if c != "ticker"]
    keep: List[str] = []

    for c in cols:
        try:
            ic, p = spearmanr(both[c].values, both["y"].values, nan_policy="omit")
            if ic is not None and np.isfinite(ic) and abs(ic) >= thresh:
                keep.append(c)
        except Exception:
            continue

    return keep


def main() -> None:
    if not os.path.exists(IN_ROOT):
        print(f"No normalized features at {IN_ROOT}. Run normalize_features first (or switch IN_ROOT).")
        return

    tfs = _list_timeframes(IN_ROOT)
    for tf in tfs:
        in_dir = os.path.join(IN_ROOT, tf)
        out_dir = os.path.join(OUT_ROOT, tf)
        ensure_dir(out_dir)

        files = [f for f in os.listdir(in_dir) if f.endswith(".parquet")]
        print(f"Selecting features for {tf} across {len(files)} tickers...")

        for fname in files:
            src = os.path.join(in_dir, fname)
            dst = os.path.join(out_dir, fname)
            try:
                df = pd.read_parquet(src)
                if df.empty:
                    continue

                # Optional supervised prune (if labels exist)
                y = _load_labels(tf, fname)
                if y is not None:
                    keep = _ic_prune(df, y, IC_THRESHOLD)
                    # Put timestamp/ticker back
                    keep = ["timestamp", "ticker"] + [c for c in keep if c not in ("timestamp","ticker")]
                    pruned = df[keep].copy()
                else:
                    pruned = df.copy()

                # Unsupervised correlation prune
                keep_corr = _corr_prune(pruned, CORR_THRESHOLD)
                keep_final = ["timestamp", "ticker"] + [c for c in keep_corr if c not in ("timestamp","ticker")]
                out = pruned[keep_final].copy()

                ensure_dir(os.path.dirname(dst))
                out.to_parquet(dst, index=False)
                print(f"Wrote {dst}")
            except Exception as e:
                print(f"Error selecting features for {fname}: {e}")

    print("Feature selection complete.")


main()
