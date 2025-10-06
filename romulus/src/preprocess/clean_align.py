#!/usr/bin/env python3
"""
Clean and align raw daily OHLCV into a single panel.

- Reads: data/raw/daily/*.parquet
- Applies: schema normalization, sorting, de-dupe, dollar_vol, liquidity gate
- Writes: data/interim/daily_panel.parquet
"""

from __future__ import annotations
import argparse
import glob
import os
from typing import Optional, Dict, Any

import pandas as pd

try:
    import yaml
except Exception:
    yaml = None


def read_yaml(path: str) -> Dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML not installed. pip install pyyaml")
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


def load_all_raw(raw_dir: str) -> pd.DataFrame:
    files = sorted(glob.glob(os.path.join(raw_dir, "*.parquet")))
    frames = []
    for p in files:
        try:
            df = pd.read_parquet(p)
        except Exception:
            continue
        # Normalize
        if "Date" in df.columns and "date" not in df.columns:
            df = df.rename(columns={"Date": "date"})
        if "Ticker" not in df.columns:
            ticker = os.path.splitext(os.path.basename(p))[0].upper()
            df["Ticker"] = ticker
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        keep = ["date", "Open", "High", "Low", "Close", "Adj Close", "Volume", "Ticker"]
        df = df[[c for c in keep if c in df.columns]]
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["date", "Open", "High", "Low", "Close", "Adj Close", "Volume", "Ticker"])
    out = pd.concat(frames, ignore_index=True)
    # Basic hygiene
    out = out.dropna(subset=["Close", "Volume"])
    out = out.sort_values(["Ticker", "date"]).drop_duplicates(subset=["Ticker", "date"], keep="last")
    return out


def add_derived(panel: pd.DataFrame) -> pd.DataFrame:
    panel = panel.copy()
    panel["dollar_vol"] = panel["Close"] * panel["Volume"]
    return panel


def apply_liquidity_gate(panel: pd.DataFrame, min_lookback_days: int, min_dollar_vol: Optional[float]) -> pd.DataFrame:
    if not min_dollar_vol:
        return panel
    df = panel.copy()
    # Compute rolling average dollar_vol per ticker over last N calendar days per each row
    df = df.sort_values(["Ticker", "date"])
    df["avg_dollar_vol_lk"] = (
        df.groupby("Ticker")["dollar_vol"]
          .transform(lambda s: s.rolling(min_lookback_days, min_periods=min_lookback_days).mean())
    )
    filtered = df[(df["avg_dollar_vol_lk"].notna()) & (df["avg_dollar_vol_lk"] >= float(min_dollar_vol))]
    # Keep all earlier rows for tickers that eventually pass? No—gate applies per-row (time-varying membership)
    # If you want a static gate, compute on a trailing window at a single anchor date before filtering.
    return filtered.drop(columns=["avg_dollar_vol_lk"])


def write_panel(panel: pd.DataFrame, out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    panel.to_parquet(out_path, index=False)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Clean and align raw daily OHLCV into a single panel.")
    p.add_argument("--params", type=str, default="config/params.yaml")
    p.add_argument("--raw-dir", type=str, default="data/raw/daily")
    p.add_argument("--out", type=str, default="data/interim/daily_panel.parquet")
    p.add_argument("--disable-liquidity-gate", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    params = read_yaml(args.params)

    panel = load_all_raw(args.raw_dir)
    if panel.empty:
        print("No raw daily files found. Did you run ingest/fetch_prices.py?")
        return

    panel = add_derived(panel)

    if not args.disable_liquidity_gate:
        lk_days = int(params.get("liquidity", {}).get("min_dollar_vol_lookback_days", 60))
        lk_min = params.get("liquidity", {}).get("min_dollar_vol_usd", None)
        panel = apply_liquidity_gate(panel, lk_days, lk_min)

    # Final schema checks
    assert panel.duplicated(subset=["Ticker", "date"]).sum() == 0, "Duplicate (Ticker,date) rows found"
    assert {"date", "Close", "Volume", "Ticker"}.issubset(panel.columns), "Missing required columns"

    write_panel(panel, args.out)
    print(f"Wrote {len(panel):,} rows to {args.out}")


main()
