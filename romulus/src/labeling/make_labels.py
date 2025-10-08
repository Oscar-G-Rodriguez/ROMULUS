"""
Create forward-return labels per timeframe, with signal delay and SPY-relative (alpha) labels.

Inputs
- Resampled panels per timeframe:
  data/interim/resampled/<tf>/<TICKER>.parquet
  Required columns: timestamp, adj_close, ticker

Config (config.yaml)
labels:
  horizons_periods: [1, 2, 4]        # label horizons in *periods* of that timeframe
  signal_delay_periods: 1            # delay between signal time and entry
benchmark: "SPY"                     # used for alpha (excess) labels

Outputs
- data/processed/labels/<tf>/<TICKER>.parquet
  Columns:
    timestamp, ticker,
    y_p1, y_p2, ...                  # forward returns over horizons
    y_alpha_p1, y_alpha_p2, ...      # excess over benchmark (same horizon)

Notes
- If a ticker is the benchmark itself, y_alpha_* will be 0 (by definition).
- All labels are aligned at time t with future info strictly after a delay.
  Entry price at t + signal_delay; exit at t + signal_delay + horizon.
"""

import os
from typing import Dict, Any, List

import pandas as pd
import numpy as np

from ..utils.io_utils import load_configs, ensure_dir

RESAMPLED_ROOT = "data/interim/resampled"
OUT_ROOT       = "data/processed/labels"

def _cfg_labels(cfg: Dict[str, Any]) -> Dict[str, Any]:
    lb = cfg.get("labels", {}) or {}
    horizons = lb.get("horizons_periods", [1, 2, 4])
    delay = int(lb.get("signal_delay_periods", 1))
    return {"horizons": [int(h) for h in horizons], "delay": delay}

def _load_series(tf: str, ticker: str) -> pd.DataFrame:
    path = os.path.join(RESAMPLED_ROOT, tf, f"{ticker}.parquet")
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_parquet(path)
    if df.empty:
        return df
    df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df[["timestamp", "adj_close", "ticker"]]

def _forward_return(ac: pd.Series, delay: int, horizon: int) -> pd.Series:
    """
    Label at time t is return from entry=t+delay to exit=t+delay+horizon:
      (adj_close[t+delay+h] / adj_close[t+delay]) - 1
    """
    entry = ac.shift(-delay)
    exit_ = ac.shift(-(delay + horizon))
    y = (exit_ / entry) - 1.0
    return y

def _make_labels_for_ticker(tf: str, ticker: str, cfg: Dict[str, Any]) -> pd.DataFrame:
    series = _load_series(tf, ticker)
    if series.empty:
        return pd.DataFrame()

    horizons = cfg["labels"]["horizons"]
    delay = cfg["labels"]["delay"]

    out = series[["timestamp", "ticker"]].copy()

    # Benchmark series for alpha
    bench = (cfg.get("benchmark") or "SPY").upper()
    if bench == ticker:
        bench_df = series.copy()
    else:
        bench_df = _load_series(tf, bench)

    # Build raw forward returns
    for h in horizons:
        out[f"y_p{h}"] = _forward_return(series["adj_close"], delay, h)

    # Excess over benchmark
    if not bench_df.empty:
        aligned = out[["timestamp"]].merge(bench_df[["timestamp", "adj_close"]], on="timestamp", how="left")
        b_ac = aligned["adj_close"]
        for h in horizons:
            b_y = _forward_return(b_ac, delay, h)
            # if ticker is the benchmark, b_y equals its own; y - b_y = 0
            out[f"y_alpha_p{h}"] = out[f"y_p{h}"] - b_y
    else:
        # If no benchmark data, still emit columns with NaN
        for h in horizons:
            out[f"y_alpha_p{h}"] = np.nan

    # Drop rows where the future window is incomplete (tails)
    last_valid = max(horizons) + delay
    out = out.iloc[:-last_valid] if len(out) > last_valid else out.iloc[0:0]

    return out

def main() -> None:
    cfg = load_configs()
    cfg = {"labels": _cfg_labels(cfg), "benchmark": cfg.get("benchmark", "SPY")}

    if not os.path.exists(RESAMPLED_ROOT):
        print(f"No resampled root at {RESAMPLED_ROOT}. Run preprocess/resample first.")
        return

    tfs = [d for d in os.listdir(RESAMPLED_ROOT) if os.path.isdir(os.path.join(RESAMPLED_ROOT, d))]
    if not tfs:
        print("No timeframes found to label.")
        return

    for tf in tfs:
        in_dir = os.path.join(RESAMPLED_ROOT, tf)
        files = [f for f in os.listdir(in_dir) if f.endswith(".parquet")]
        if not files:
            print(f"No files to label for {tf}")
            continue

        out_dir = os.path.join(OUT_ROOT, tf)
        ensure_dir(out_dir)

        print(f"Labeling {len(files)} tickers at tf={tf} with horizons={cfg['labels']['horizons']} delay={cfg['labels']['delay']}")
        for fname in files:
            tkr = fname[:-8].upper()
            try:
                out = _make_labels_for_ticker(tf, tkr, cfg)
                if out.empty:
                    continue
                dst = os.path.join(out_dir, fname)
                out.to_parquet(dst, index=False)
                print(f"Wrote {dst}")
            except Exception as e:
                print(f"Error labeling {tkr} ({tf}): {e}")

    print("Labeling complete.")


main()
