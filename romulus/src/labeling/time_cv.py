"""
Build time-based CV splits with purging and embargo, per timeframe.

We use the benchmark (e.g., SPY) resampled timestamps as the master calendar
to define split date ranges. Each split is a dict with:
  { "train_start", "train_end", "test_start", "test_end", "embargo_days" }

Config (config.yaml)
cv:
  n_splits: 5
  train_years: 5
  test_years: 1
  embargo_days: 5

Inputs
- data/interim/resampled/<tf>/<BENCHMARK>.parquet    (e.g., SPY)

Outputs
- data/processed/cv/<tf>/splits.json
"""

import os
import json
from typing import Dict, Any, List
import pandas as pd

from ..utils.io_utils import load_configs, ensure_dir

RESAMPLED_ROOT = "data/interim/resampled"
OUT_ROOT       = "data/processed/cv"

def _cfg_cv(cfg: Dict[str, Any]) -> Dict[str, Any]:
    block = cfg.get("cv", {}) or {}
    return {
        "n_splits": int(block.get("n_splits", 5)),
        "train_years": int(block.get("train_years", 5)),
        "test_years": int(block.get("test_years", 1)),
        "embargo_days": int(block.get("embargo_days", 5)),
    }

def _load_benchmark_series(tf: str, bench: str) -> pd.DataFrame:
    path = os.path.join(RESAMPLED_ROOT, tf, f"{bench}.parquet")
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_parquet(path)
    if df.empty:
        return df
    df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df[["timestamp"]]

def _year_offset(ts: pd.Timestamp, years: int) -> pd.Timestamp:
    try:
        return ts + pd.DateOffset(years=years)
    except Exception:
        # Fallback if DateOffset fails
        return pd.Timestamp(ts.year + years, ts.month, min(ts.day, 28))

def _build_splits(idx: pd.DatetimeIndex, n_splits: int, train_y: int, test_y: int, embargo_days: int) -> List[Dict[str, str]]:
    splits: List[Dict[str, str]] = []
    if len(idx) == 0:
        return splits

    start = idx.min().normalize()
    end   = idx.max().normalize()

    # Rolling windows forward
    for k in range(n_splits):
        train_start = _year_offset(start, k)  # move start forward each split
        train_end   = _year_offset(train_start, train_y)
        test_start  = train_end + pd.Timedelta(days=embargo_days)
        test_end    = _year_offset(test_start, test_y)

        # cap within available range
        if test_start >= end:
            break

        train_end = min(train_end, end)
        test_end  = min(test_end, end)

        # require non-empty ranges
        if train_start >= train_end or test_start >= test_end:
            continue

        spl = {
            "train_start": train_start.strftime("%Y-%m-%d"),
            "train_end":   train_end.strftime("%Y-%m-%d"),
            "test_start":  test_start.strftime("%Y-%m-%d"),
            "test_end":    test_end.strftime("%Y-%m-%d"),
            "embargo_days": int(embargo_days),
        }
        splits.append(spl)

    return splits

def main() -> None:
    cfg = load_configs()
    cv_cfg = _cfg_cv(cfg)
    bench = (cfg.get("benchmark") or "SPY").upper()

    if not os.path.exists(RESAMPLED_ROOT):
        print(f"No resampled root at {RESAMPLED_ROOT}. Run preprocess/resample first.")
        return

    tfs = [d for d in os.listdir(RESAMPLED_ROOT) if os.path.isdir(os.path.join(RESAMPLED_ROOT, d))]
    if not tfs:
        print("No timeframes found for CV splits.")
        return

    for tf in tfs:
        df = _load_benchmark_series(tf, bench)
        if df.empty:
            print(f"Skip {tf}: missing benchmark series {bench}")
            continue

        idx = pd.to_datetime(df["timestamp"]).dt.normalize().unique()
        idx = pd.DatetimeIndex(idx)

        splits = _build_splits(idx, cv_cfg["n_splits"], cv_cfg["train_years"], cv_cfg["test_years"], cv_cfg["embargo_days"])
        if not splits:
            print(f"No valid splits for {tf}")
            continue

        out_dir = os.path.join(OUT_ROOT, tf)
        ensure_dir(out_dir)
        dst = os.path.join(out_dir, "splits.json")
        with open(dst, "w", encoding="utf-8") as f:
            json.dump({"benchmark": bench, "splits": splits}, f, indent=2)
        print(f"Wrote {dst}")

    print("Time CV split generation complete.")


main()
