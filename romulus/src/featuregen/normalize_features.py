"""
Normalize features in a leak-free way (rolling normalization).

Behavior
- Loads features from data/processed/features/<tf>/<TICKER>.parquet
- Applies normalization per ticker using rolling window from config/schema.yaml:
    normalization:
      method: "rolling_z"
      window: 252
- Writes normalized features to:
    data/processed/features_norm/<tf>/<TICKER>.parquet

Notes
- Rolling z-score: (x - rolling_mean) / rolling_std with min_periods=window
- We do NOT normalize timestamp or ticker.
- NaNs at the head are expected when the rolling window hasn't filled yet.
"""

import os
from typing import Dict, Any

import pandas as pd
import yaml
import numpy as np

from ..utils.io_utils import ensure_dir

IN_ROOT  = "data/processed/features"
OUT_ROOT = "data/processed/features_norm"

def _load_norm_cfg(path: str = "config/schema.yaml") -> Dict[str, Any]:
    with open(path, "r") as f:
        s = yaml.safe_load(f)
    return (s or {}).get("normalization", {"method": "rolling_z", "window": 252})

def _rolling_zscore(df: pd.DataFrame, window: int) -> pd.DataFrame:
    out = df.copy()
    # Only normalize numeric feature columns (exclude timestamp, ticker)
    numeric_cols = [c for c in out.columns if c not in ("timestamp", "ticker")]
    out = out.sort_values("timestamp")
    for c in numeric_cols:
        series = out[c].astype(float)
        mean = series.rolling(window=window, min_periods=window).mean()
        std = series.rolling(window=window, min_periods=window).std(ddof=0)
        out[c] = (series - mean) / std.replace(0, np.nan)
    return out

def main() -> None:
    norm_cfg = _load_norm_cfg()
    method = norm_cfg.get("method", "rolling_z")
    window = int(norm_cfg.get("window", 252))

    if not os.path.exists(IN_ROOT):
        print(f"No feature directory at {IN_ROOT}. Run build_features first.")
        return

    tfs = [d for d in os.listdir(IN_ROOT) if os.path.isdir(os.path.join(IN_ROOT, d))]
    for tf in tfs:
        in_dir = os.path.join(IN_ROOT, tf)
        out_dir = os.path.join(OUT_ROOT, tf)
        ensure_dir(out_dir)

        files = [f for f in os.listdir(in_dir) if f.endswith(".parquet")]
        print(f"Normalizing features for {tf} across {len(files)} tickers...")

        for fname in files:
            src = os.path.join(in_dir, fname)
            dst = os.path.join(out_dir, fname)
            try:
                df = pd.read_parquet(src)
                if df.empty:
                    continue

                if method == "rolling_z":
                    out = _rolling_zscore(df, window=window)
                else:
                    out = df  # future: add quantile/robust methods

                # Warn if excessive NaNs (short history or window too long)
                nan_pct = out.isna().mean().mean()
                if nan_pct > 0.5:
                    print(f"Warning: {fname} has {nan_pct:.0%} NaNs post-normalization (likely short history).")


                ensure_dir(os.path.dirname(dst))
                out.to_parquet(dst, index=False)
                print(f"Wrote {dst}")
            except Exception as e:
                print(f"Error normalizing {fname}: {e}")

    print("Feature normalization complete.")


main()
