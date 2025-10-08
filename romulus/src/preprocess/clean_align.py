"""
Clean and align raw price data.

Steps
1. Read config/universe.yaml to get tickers and active windows.
2. Read raw daily OHLCV Parquets from data/raw/prices/1d/.
3. Drop rows outside each tickers active_start to active_end window.
4. Remove duplicates, sort by timestamp, and fill obvious missing fields.
5. Reindex all tickers to a shared market calendar (NYSE-like) to guarantee alignment.
6. Save cleaned Parquets to data/interim/prices/1d_clean/.

This is the first preprocessing stage; pit_join.py and resample.py depend on these outputs.
"""

import os
import pandas as pd
import numpy as np
from typing import Dict, Any

from ..utils.io_utils import load_configs, ensure_dir
from ..utils.exchange_calendars import get_calendar  # we'll implement this helper

RAW_DIR = "data/raw/prices/1d"
OUT_DIR = "data/interim/prices/1d_clean"


def _load_universe_meta(cfg: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Return {ticker: metadata dict} from config/universe.yaml."""
    uni_root = cfg.get("universe", {})
    uni = uni_root.get("universe", uni_root)
    return uni.get("metadata", {})


def _trim_active_window(df: pd.DataFrame, meta: Dict[str, Any]) -> pd.DataFrame:
    """Trim rows outside active_start–active_end (survivorship guard)."""
    start = pd.Timestamp(meta.get("active_start", "1900-01-01"))
    end = pd.Timestamp(meta.get("active_end", "2262-04-11"))
    df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
    return df[(df["timestamp"] >= start) & (df["timestamp"] <= end)]


def _fill_and_validate_aligned(df: pd.DataFrame) -> pd.DataFrame:
    """
    Assumes df is already merged onto a proper exchange calendar index (one row per
    session). Only forward-fill SINGLE isolated missing days for prices; never bridge
    multi-day gaps. Mark synthetic rows and zero their volume.
    """
    df = df.sort_values("timestamp").drop_duplicates(subset=["timestamp"])
    df["is_synth"] = df[["open","high","low","close","adj_close"]].isna().all(axis=1)

    # Identify isolated single-day gaps (NaNs flanked by non-NaNs)
    price_cols = ["open","high","low","close","adj_close"]
    

    # A helper mask: missing today but present yesterday and tomorrow
    prev_has = df[price_cols].notna().shift(1).all(axis=1)
    next_has = df[price_cols].notna().shift(-1).all(axis=1)
    isolated_gap = df[price_cols].isna().all(axis=1) & prev_has & next_has

    # Fill only those isolated gaps with previous close (OHLC = prev close)
    prev_close = df["close"].shift(1)
    for c in ["open","high","low","close","adj_close"]:
        if c in df.columns:
            df.loc[isolated_gap, c] = prev_close[isolated_gap].values

    # Volumes: zero on synthetic rows
    if "volume" in df.columns:
        df["volume"] = df["volume"].fillna(0.0)
        df.loc[isolated_gap, "volume"] = 0.0

    # Enforce OHLC sanity (clamp within [low, high] using close as anchor)
    if all(c in df.columns for c in ["open","high","low","close"]):
        # Ensure bounds exist
        df["high"] = np.maximum(df["high"], df["close"])
        df["low"] = np.minimum(df["low"], df["close"])
        # Clamp open into [low, high]
        df["open"] = np.clip(df["open"], df["low"], df["high"])

    # Final drop of rows still missing close
    df = df.dropna(subset=["close"]).copy()
    return df


def main() -> None:
    cfg = load_configs()
    meta = _load_universe_meta(cfg)

    if not os.path.exists(RAW_DIR):
        print(f"No raw price dir at {RAW_DIR}")
        return

    # Full NYSE session calendar (DatetimeIndex)
    full_cal = get_calendar("NYSE")
    ensure_dir(OUT_DIR)

    for fname in os.listdir(RAW_DIR):
        if not fname.endswith(".parquet"):
            continue
        tkr = fname[:-8].upper()  # strip ".parquet"
        src = os.path.join(RAW_DIR, fname)
        dst = os.path.join(OUT_DIR, fname)

        try:
            df = pd.read_parquet(src)
            if df.empty:
                continue

            # Enforce active window bounds early (survivorship guard)
            if tkr in meta:
                df = _trim_active_window(df, meta[tkr])

            if df.empty:
                continue

            # Prepare calendar slice for this ticker’s window to keep it fast
            ts = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
            start = ts.min().normalize()
            end = ts.max().normalize()
            # If universe metadata has tighter bounds, respect those too
            if tkr in meta:
                ms = pd.to_datetime(meta[tkr].get("active_start", start)).normalize()
                me = pd.to_datetime(meta[tkr].get("active_end", end)).normalize()
                start = max(start, ms)
                end = min(end, me)

            cal = full_cal[(full_cal >= start) & (full_cal <= end)]

            # Align to exchange calendar: one row per session
            df["timestamp"] = ts
            df = df.sort_values("timestamp")
            frame_cal = pd.DataFrame({"timestamp": cal})
            df = pd.merge(frame_cal, df, on="timestamp", how="left")

            # Set ticker column then validate/fill isolated gaps only
            df["ticker"] = tkr

            # require core price columns post-merge; otherwise skip
            required = ["open", "high", "low", "close", "adj_close"]
            missing = [c for c in required if c not in df.columns]
            if missing:
                print(f"Skip {tkr}: missing columns {missing}")
                continue

            # enforce numeric types
            for c in ["open","high","low","close","adj_close","volume"]:
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce")

            df = _fill_and_validate_aligned(df)

            ensure_dir(os.path.dirname(dst))
            df.to_parquet(dst, index=False)
            print(f"Cleaned {tkr} -> {dst}")

        except Exception as e:
            print(f"Error cleaning {tkr}: {e}")

    print("Clean-align complete.")



main()

