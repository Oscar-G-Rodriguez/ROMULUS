#!/usr/bin/env python3
"""
Fetch daily OHLCV for a universe of tickers (yfinance) with incremental caching.

Examples:
  python src/ingest/fetch_prices.py --universe config/universe.yaml --years 5
  python src/ingest/fetch_prices.py --universe config/universe.yaml:test_12 --start 2018-01-01
  python src/ingest/fetch_prices.py --tickers AAPL MSFT SPY --years 10
"""

from __future__ import annotations
import argparse
import os
from datetime import timedelta
from typing import List, Optional

import pandas as pd

try:
    import yaml
except Exception as e:  # noqa: F841
    yaml = None

try:
    import yfinance as yf
except Exception:
    raise RuntimeError("yfinance not installed. pip install yfinance")

RAW_DIR_DEFAULT = "data/raw/daily"


def read_universe(universe_arg: str) -> List[str]:
    """
    universe_arg may be:
      - 'config/universe.yaml' (uses 'default' set in file)
      - 'config/universe.yaml:set_name'
    """
    if yaml is None:
        raise RuntimeError("PyYAML not installed. pip install pyyaml")
    if ":" in universe_arg:
        path, set_name = universe_arg.split(":", 1)
    else:
        path, set_name = universe_arg, None
    with open(path, "r") as f:
        cfg = yaml.safe_load(f)
    if set_name is None:
        set_name = cfg.get("default") or next(iter(cfg.get("sets", {}).keys()))
    tickers = [t.upper() for t in cfg["sets"][set_name]]
    # de-duplicate while preserving order
    seen, out = set(), []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def raw_path(ticker: str, raw_dir: str) -> str:
    return os.path.join(raw_dir, f"{ticker}.parquet")


def load_existing(ticker: str, raw_dir: str) -> Optional[pd.DataFrame]:
    p = raw_path(ticker, raw_dir)
    if not os.path.exists(p):
        return None
    df = pd.read_parquet(p)
    if "date" not in df.columns and "Date" in df.columns:
        df = df.rename(columns={"Date": "date"})
    if "Ticker" not in df.columns:
        df["Ticker"] = ticker
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    df = df.sort_values("date").drop_duplicates(subset=["date"])
    return df


def download_block(tickers: List[str], start: Optional[str], end: Optional[str], years: Optional[int]) -> pd.DataFrame:
    kwargs = dict(interval="1d", auto_adjust=False, actions=False, group_by="ticker")
    if start or end:
        kwargs.update(start=start, end=end)
    elif years:
        kwargs.update(period=f"{years}y")
    else:
        kwargs.update(period="5y")
    data = yf.download(tickers, **kwargs)
    if isinstance(data.columns, pd.MultiIndex):
        frames = []
        for t in tickers:
            if t not in data.columns.get_level_values(-1):
                continue
            sub = data.xs(t, axis=1, level=1)
            sub = sub.reset_index().rename(columns={"Date": "date"})
            sub["Ticker"] = t
            frames.append(sub[["date", "Open", "High", "Low", "Close", "Adj Close", "Volume", "Ticker"]])
        out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    else:
        out = data.reset_index().rename(columns={"Date": "date"})
        out["Ticker"] = tickers[0]
        out = out[["date", "Open", "High", "Low", "Close", "Adj Close", "Volume", "Ticker"]]
    if not out.empty:
        out["date"] = pd.to_datetime(out["date"]).dt.tz_localize(None)
        out = out.sort_values(["Ticker", "date"])
    return out


def merge_incremental(existing: Optional[pd.DataFrame], fresh: Optional[pd.DataFrame]) -> pd.DataFrame:
    if existing is None or existing.empty:
        return fresh if fresh is not None else pd.DataFrame()
    if fresh is None or fresh.empty:
        return existing
    first_new = fresh["date"].min()
    left = existing[existing["date"] < first_new]
    combined = pd.concat([left, fresh], ignore_index=True)
    combined = combined.drop_duplicates(subset=["Ticker", "date"], keep="last").sort_values(["Ticker", "date"])
    return combined


def fetch_and_save(
    tickers: List[str],
    raw_dir: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    years: Optional[int] = None,
    force_rebuild: bool = False,
) -> None:
    os.makedirs(raw_dir, exist_ok=True)
    for t in tickers:
        existing = None if force_rebuild else load_existing(t, raw_dir)
        if existing is not None and not existing.empty and not force_rebuild and start is None:
            last_date = existing["date"].max()
            inc_start = (last_date + timedelta(days=1)).strftime("%Y-%m-%d")
            fresh = download_block([t], start=inc_start, end=end, years=None)
            merged = merge_incremental(existing, fresh)
        else:
            merged = download_block([t], start=start, end=end, years=years)
        if merged is None or merged.empty:
            print(f"{t}: no data returned")
            continue
        merged = merged.dropna(subset=["Close", "Volume"])
        merged = merged.sort_values("date").drop_duplicates(subset=["date"])
        merged.to_parquet(raw_path(t, raw_dir), index=False)
        print(f"{t}: saved {len(merged)} rows to {raw_path(t, raw_dir)}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch daily OHLCV (yfinance) with incremental caching.")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--universe", type=str, help="Path to config/universe.yaml, optionally :set_name")
    g.add_argument("--tickers", nargs="+", help="Explicit tickers list")
    p.add_argument("--raw-dir", type=str, default=RAW_DIR_DEFAULT)
    p.add_argument("--start", type=str, help="YYYY-MM-DD (overrides --years)")
    p.add_argument("--end", type=str, help="YYYY-MM-DD")
    p.add_argument("--years", type=int, default=5)
    p.add_argument("--force-rebuild", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    if args.universe:
        tickers = read_universe(args.universe)
    else:
        tickers = [t.upper() for t in args.tickers]
    fetch_and_save(
        tickers=tickers,
        raw_dir=args.raw_dir,
        start=args.start,
        end=args.end,
        years=(None if args.start or args.end else args.years),
        force_rebuild=args.force_rebuild,
    )


main()
