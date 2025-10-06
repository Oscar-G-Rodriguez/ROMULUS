#!/usr/bin/env python3
"""
Resampling utilities and CLI: daily → weekly.

Rules:
- Price-like columns (Open, High, Low, Close, Adj Close): take last close of the week
- Returns (r1 = log daily return): sum over the week (r1_sum) and std over the week (r1_std)
- Volume, dollar_vol: sum over the week

CLI examples:
  python src/preprocess/resample.py \
      --in data/interim/daily_panel.parquet \
      --out data/interim/weekly_panel.parquet

  # If your daily panel lacks r1, add it on the fly:
  python src/preprocess/resample.py --in ... --out ... --ensure-r1
"""

from __future__ import annotations
import argparse
import os
from typing import Iterable

import numpy as np
import pandas as pd


def ensure_required_cols(df: pd.DataFrame, required: Iterable[str]) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")


def add_daily_log_return(panel_daily: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure column r1 exists as log return of Close, per ticker.
    r1[t] = log(Close[t] / Close[t-1]); first value per ticker is NaN and kept.
    """
    df = panel_daily.sort_values(["Ticker", "date"]).copy()
    ensure_required_cols(df, ["Ticker", "date", "Close"])
    df["r1"] = (
        df.groupby("Ticker")["Close"]
          .apply(lambda s: np.log(s / s.shift(1)))
          .values
    )
    return df


def daily_to_weekly(panel_daily: pd.DataFrame) -> pd.DataFrame:
    """
    Input schema:
      date, Open, High, Low, Close, Adj Close, Volume, Ticker
      optional: dollar_vol, r1

    Output schema:
      week_end_date, Ticker, Open, High, Low, Close, Adj Close, Volume, dollar_vol, r1_sum, r1_std
    """
    df = panel_daily.copy()
    ensure_required_cols(df, ["Ticker", "date", "Close", "Volume"])
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    # Friday week-end (weekday=4)
    df["week_end_date"] = df["date"] + pd.offsets.Week(weekday=4)

    # Base aggregations
    agg_map = {
        "Close": "last",
        "Open": "last" if "Open" in df.columns else "last",
        "High": "last" if "High" in df.columns else "last",
        "Low": "last" if "Low" in df.columns else "last",
        "Adj Close": "last" if "Adj Close" in df.columns else "last",
        "Volume": "sum",
    }
    if "dollar_vol" in df.columns:
        agg_map["dollar_vol"] = "sum"

    base = (
        df.groupby(["Ticker", "week_end_date"], as_index=False)
          .agg({k: v for k, v in agg_map.items() if k in df.columns})
          .sort_values(["Ticker", "week_end_date"])
    )

    # Returns: if r1 absent, compute from Close only for weekly metrics
    if "r1" not in df.columns:
        tmp = df.sort_values(["Ticker", "date"]).copy()
        tmp["r1"] = tmp.groupby("Ticker")["Close"].apply(lambda s: np.log(s / s.shift(1))).values
    else:
        tmp = df

    r_agg = (
        tmp.groupby(["Ticker", "week_end_date"], as_index=False)
           .agg(r1_sum=("r1", "sum"), r1_std=("r1", "std"))
    )

    out = base.merge(r_agg, on=["Ticker", "week_end_date"], how="left")
    return out.sort_values(["Ticker", "week_end_date"]).reset_index(drop=True)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Daily → Weekly resampling CLI for Romulus.")
    p.add_argument("--in", dest="inp", required=True, help="Path to daily panel parquet (e.g., data/interim/daily_panel.parquet)")
    p.add_argument("--out", dest="out", required=True, help="Path to write weekly panel parquet")
    p.add_argument("--ensure-r1", action="store_true", help="Add r1 to daily panel before resampling if missing")
    return p.parse_args()


def main():
    args = parse_args()
    if not os.path.exists(args.inp):
        raise FileNotFoundError(f"Input not found: {args.inp}")

    daily = pd.read_parquet(args.inp)
    if args.ensure_r1 and "r1" not in daily.columns:
        daily = add_daily_log_return(daily)

    weekly = daily_to_weekly(daily)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    weekly.to_parquet(args.out, index=False)
    print(f"Wrote {len(weekly):,} rows to {args.out}")


main()

