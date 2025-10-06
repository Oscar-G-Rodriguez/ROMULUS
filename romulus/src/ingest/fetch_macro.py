#!/usr/bin/env python3
"""
Fetch macro/market-wide series without API keys.

Series:
  - ^VIX   : CBOE Volatility Index (close)
  - ^TNX   : 10-Year Treasury Note Yield Index (approx. 10y yield * 100)

Outputs:
  data/raw/macro/VIX.parquet
  data/raw/macro/TNX.parquet

Columns:
  date, value, series, release_ts, valid_from, valid_to
"""

from __future__ import annotations
import argparse
import os
from typing import Tuple

import pandas as pd
import yfinance as yf


OUT_DIR_DEFAULT = "data/raw/macro"


def _dl(symbol: str, years: int | None, start: str | None, end: str | None) -> pd.DataFrame:
    kwargs = dict(interval="1d", auto_adjust=False)
    if start or end:
        kwargs.update(start=start, end=end)
    elif years:
        kwargs.update(period=f"{years}y")
    else:
        kwargs.update(period="5y")
    df = yf.download(symbol, **kwargs).reset_index().rename(columns={"Date": "date", "Close": "value"})
    if "value" not in df.columns:
        raise RuntimeError(f"No 'Close' for {symbol}")
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    df = df[["date", "value"]].dropna().sort_values("date")
    return df


def _add_pit_fields(df: pd.DataFrame, series_name: str) -> pd.DataFrame:
    # For market indices, we treat availability as same-day close.
    out = df.copy()
    out["series"] = series_name
    # Release assumed at 21:00 UTC (post-close availability approximation)
    out["release_ts"] = pd.to_datetime(out["date"]) + pd.Timedelta(hours=21)
    out["valid_from"] = out["release_ts"]
    out["valid_to"] = pd.NaT
    return out


def fetch_vix_tnx(years: int | None, start: str | None, end: str | None) -> Tuple[pd.DataFrame, pd.DataFrame]:
    vix = _dl("^VIX", years, start, end)
    tnx = _dl("^TNX", years, start, end)
    return _add_pit_fields(vix, "VIX"), _add_pit_fields(tnx, "TNX")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch macro series (^VIX, ^TNX) for PIT joins.")
    p.add_argument("--out-dir", type=str, default=OUT_DIR_DEFAULT)
    p.add_argument("--years", type=int, default=5)
    p.add_argument("--start", type=str, help="YYYY-MM-DD")
    p.add_argument("--end", type=str, help="YYYY-MM-DD")
    return p.parse_args()


def main():
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    vix, tnx = fetch_vix_tnx(args.years if not args.start and not args.end else None, args.start, args.end)
    vix.to_parquet(os.path.join(args.out_dir, "VIX.parquet"), index=False)
    tnx.to_parquet(os.path.join(args.out_dir, "TNX.parquet"), index=False)
    print(f"Saved {len(vix)} VIX rows and {len(tnx)} TNX rows under {args.out_dir}")



main()
