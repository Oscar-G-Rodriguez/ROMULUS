#!/usr/bin/env python3
"""
Build a liquid equity universe from public seed lists and recent trading stats.

Seed sources (scraped):
  - sp500       : Wikipedia S&P 500 constituents
  - nasdaq100   : Wikipedia NASDAQ-100 constituents
  - file:<path> : One-ticker-per-line text file (custom)

Metrics:
  - avg_dollar_vol (USD): mean over last N trading days of Close * Volume
  - market_cap (USD): from yfinance (best-effort)

Outputs:
  - data/meta/universe_snapshot_<YYYYMMDD>.parquet  (tickers + metrics)
  - optionally updates config/universe.yaml with a new set

Examples:
  python src/ingest/build_universe.py --source sp500 --lookback-days 60 --min-dollar-vol 10000000 \
      --set-name sp500_liq10m_v1 --update-universe-yaml

  python src/ingest/build_universe.py --source nasdaq100 --top-n 80 --set-name ndx80 --update-universe-yaml
"""

from __future__ import annotations
import argparse
import os
import sys
import io
from datetime import datetime, timedelta
from typing import List, Tuple, Optional

import pandas as pd

try:
    import yfinance as yf
except Exception:
    raise RuntimeError("yfinance not installed. pip install yfinance")

try:
    import yaml
except Exception:
    yaml = None

META_DIR_DEFAULT = "data/meta"
UNIVERSE_YAML_DEFAULT = "config/universe.yaml"


def _ensure_dirs() -> None:
    os.makedirs(META_DIR_DEFAULT, exist_ok=True)


def _scrape_sp500() -> List[str]:
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    tables = pd.read_html(url)
    # first table typically has the constituents; look for 'Symbol' column
    for t in tables:
        if "Symbol" in t.columns:
            syms = t["Symbol"].astype(str).str.upper().str.strip().tolist()
            # Normalize BRK.B -> BRK-B for yfinance, same for BF.B -> BF-B
            syms = [s.replace(".", "-") for s in syms]
            return syms
    raise RuntimeError("Could not find S&P 500 symbol table on Wikipedia")


def _scrape_nasdaq100() -> List[str]:
    url = "https://en.wikipedia.org/wiki/NASDAQ-100"
    tables = pd.read_html(url)
    # look for a table with a 'Ticker' or 'Symbol' column
    for t in tables:
        cols = [c.lower() for c in t.columns]
        if "ticker" in cols or "symbol" in cols:
            col = "Ticker" if "Ticker" in t.columns else ("Symbol" if "Symbol" in t.columns else t.columns[0])
            syms = t[col].astype(str).str.upper().str.strip().tolist()
            syms = [s.replace(".", "-") for s in syms]
            return syms
    raise RuntimeError("Could not find NASDAQ-100 ticker table on Wikipedia")


def _read_custom_file(path: str) -> List[str]:
    with open(path, "r") as f:
        syms = [ln.strip().upper().replace(".", "-") for ln in f if ln.strip()]
    if not syms:
        raise ValueError(f"No tickers found in {path}")
    return syms


def _seed_tickers(source: str) -> List[str]:
    if source == "sp500":
        return _dedupe(_scrape_sp500())
    if source == "nasdaq100":
        return _dedupe(_scrape_nasdaq100())
    if source.startswith("file:"):
        return _dedupe(_read_custom_file(source.split(":", 1)[1]))
    raise ValueError(f"Unknown source '{source}'. Use sp500, nasdaq100, or file:<path>.")


def _dedupe(tickers: List[str]) -> List[str]:
    seen, out = set(), []
    for t in tickers:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _recent_panel(tickers: List[str], lookback_days: int) -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame(columns=["date", "Ticker", "Close", "Volume"])
    end = datetime.utcnow().date()
    start = end - timedelta(days=max(lookback_days + 30, 90))  # pad for weekends/holidays
    data = yf.download(
        tickers=tickers,
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        interval="1d",
        auto_adjust=False,
        group_by="ticker",
        actions=False,
        threads=True,
    )
    frames = []
    if isinstance(data.columns, pd.MultiIndex):
        for t in tickers:
            if t not in data.columns.get_level_values(-1):
                continue
            sub = data.xs(t, axis=1, level=1).reset_index().rename(columns={"Date": "date"})
            sub["Ticker"] = t
            frames.append(sub[["date", "Ticker", "Close", "Volume"]])
    else:
        # single ticker case
        sub = data.reset_index().rename(columns={"Date": "date"})
        sub["Ticker"] = tickers[0]
        frames.append(sub[["date", "Ticker", "Close", "Volume"]])
    panel = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["date", "Ticker", "Close", "Volume"])
    panel["date"] = pd.to_datetime(panel["date"]).dt.tz_localize(None)
    panel = panel.sort_values(["Ticker", "date"])
    # keep only last N calendar days with data
    min_keep = panel["date"].max() - pd.Timedelta(days=lookback_days + 7)
    panel = panel[panel["date"] >= min_keep]
    return panel


def _avg_dollar_vol(panel: pd.DataFrame) -> pd.DataFrame:
    if panel.empty:
        return pd.DataFrame(columns=["Ticker", "avg_dollar_vol"])
    tmp = panel.dropna(subset=["Close", "Volume"]).copy()
    tmp["dollar_vol"] = tmp["Close"] * tmp["Volume"]
    agg = tmp.groupby("Ticker")["dollar_vol"].mean().rename("avg_dollar_vol").reset_index()
    return agg


def _market_caps(tickers: List[str]) -> pd.DataFrame:
    caps = []
    for t in tickers:
        try:
            info = yf.Ticker(t).fast_info  # faster than .info in recent yfinance
            mc = getattr(info, "market_cap", None)
            if mc is None:
                # fall back to .info if needed
                mc = yf.Ticker(t).info.get("marketCap")
        except Exception:
            mc = None
        caps.append({"Ticker": t, "market_cap": float(mc) if mc is not None else None})
    return pd.DataFrame(caps)


def _rank_and_filter(df: pd.DataFrame, min_dollar_vol: float, top_n: Optional[int]) -> pd.DataFrame:
    df = df.copy()
    df["rank_liquidity"] = df["avg_dollar_vol"].rank(ascending=False, method="first")
    # prefer cap if missing dollar_vol for some reason
    if "market_cap" in df and df["market_cap"].notna().any():
        df["rank_mcap"] = df["market_cap"].rank(ascending=False, method="first")
        df["rank_combo"] = df[["rank_liquidity", "rank_mcap"]].mean(axis=1, skipna=True)
        df = df.sort_values(["rank_combo", "rank_liquidity"])
    else:
        df = df.sort_values("avg_dollar_vol", ascending=False)
    if min_dollar_vol is not None:
        df = df[df["avg_dollar_vol"] >= float(min_dollar_vol)]
    if top_n is not None:
        df = df.head(int(top_n))
    return df.reset_index(drop=True)


def _write_snapshot(df: pd.DataFrame) -> str:
    _ensure_dirs()
    ts = datetime.utcnow().strftime("%Y%m%d")
    path = os.path.join(META_DIR_DEFAULT, f"universe_snapshot_{ts}.parquet")
    meta = df.copy()
    meta["snapshot_utc"] = pd.Timestamp.utcnow()
    meta.to_parquet(path, index=False)
    return path


def _update_universe_yaml(set_name: str, tickers: List[str], yaml_path: str) -> None:
    if yaml is None:
        raise RuntimeError("PyYAML not installed. pip install pyyaml")
    os.makedirs(os.path.dirname(yaml_path), exist_ok=True)
    cfg = {"default": set_name, "sets": {}}  # default if file missing
    if os.path.exists(yaml_path):
        with open(yaml_path, "r") as f:
            try:
                cfg_file = yaml.safe_load(f) or {}
                cfg.update(cfg_file)
            except Exception:
                pass
    sets = cfg.get("sets", {})
    sets[set_name] = [str(t).upper() for t in tickers]
    cfg["sets"] = sets
    if "default" not in cfg or not cfg["default"]:
        cfg["default"] = set_name
    with open(yaml_path, "w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
    print(f"Updated {yaml_path} with set '{set_name}' ({len(tickers)} tickers)")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build a liquid universe from seed lists and recent trading stats.")
    p.add_argument("--source", required=True, help="sp500 | nasdaq100 | file:<path>")
    p.add_argument("--lookback-days", type=int, default=60, help="Days of history to average dollar volume")
    p.add_argument("--min-dollar-vol", type=float, default=None, help="Minimum average dollar volume in USD")
    p.add_argument("--top-n", type=int, default=None, help="Keep only top N by liquidity/market cap")
    p.add_argument("--set-name", type=str, default=None, help="Optional set name to insert into config/universe.yaml")
    p.add_argument("--update-universe-yaml", action="store_true", help="Write the set into config/universe.yaml")
    p.add_argument("--universe-yaml", type=str, default=UNIVERSE_YAML_DEFAULT)
    return p.parse_args()


def main():
    args = parse_args()
    tickers = _seed_tickers(args.source)
    if not tickers:
        print("No tickers from source.", file=sys.stderr)
        return

    panel = _recent_panel(tickers, args.lookback_days)
    liq = _avg_dollar_vol(panel)
    caps = _market_caps(liq["Ticker"].tolist())
    merged = liq.merge(caps, on="Ticker", how="left")

    ranked = _rank_and_filter(merged, args.min_dollar_vol, args.top_n)
    if ranked.empty:
        print("No tickers passed filters.", file=sys.stderr)
        return

    snapshot_path = _write_snapshot(ranked)
    print(f"Wrote snapshot: {snapshot_path}")
    print(ranked.head(10).to_string(index=False))

    if args.update_universe_yaml:
        set_name = args.set_name or f"{args.source}_liq"
        _update_universe_yaml(set_name, ranked["Ticker"].tolist(), args.universe_yaml)


main()
