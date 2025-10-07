"""
Fetch daily OHLCV for the current universe with incremental updates.

Behavior
- First run: downloads ALL available daily history for each ticker and saves to:
    data/raw/prices/1d/<TICKER>.parquet
- Subsequent runs: reads the last saved timestamp for each ticker and ONLY fetches
  bars after that timestamp, then appends & de-duplicates.
- Force full refresh: set ROMULUS_FORCE_REFRESH=1

Notes
- Benchmark (e.g., SPY) is ensured even if not in universe.
- We fetch only daily; coarser bars are built later in preprocess/resample.py
"""

import os
import time
from typing import Dict, Any, List, Optional

import pandas as pd

from ..utils.io_utils import load_configs, ensure_dir

try:
    import yfinance as yf
    HAVE_YF = True
except Exception:
    HAVE_YF = False


DATA_SUBDIR = "prices"
INTERVAL = "1d"
HISTORY_PERIOD = "max"  # used for initial fetch
MAX_RETRIES = 3
RETRY_SLEEP_SEC = 2.0


def _out_dir(cfg: Dict[str, Any], interval_key: str = "1d") -> str:
    base = cfg["paths"]["raw"]
    return os.path.join(base, DATA_SUBDIR, interval_key)


def _load_universe_tickers(cfg: Dict[str, Any]) -> List[str]:
    uni_root = cfg.get("universe", {})
    uni = uni_root.get("universe", uni_root)
    tickers = uni.get("tickers", [])
    return [str(t).upper() for t in tickers if isinstance(t, str) and t.strip()]


def _maybe_add_benchmark(tickers: List[str], benchmark: Optional[str]) -> List[str]:
    if benchmark and benchmark.upper() not in tickers:
        return tickers + [benchmark.upper()]
    return tickers


def _download_history(ticker: str, start: Optional[pd.Timestamp] = None) -> Optional[pd.DataFrame]:
    """Download daily bars (all history or just after `start`)."""
    if not HAVE_YF:
        return None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if start is None:
                hist = yf.download(
                    ticker, interval=INTERVAL, period=HISTORY_PERIOD,
                    auto_adjust=False, progress=False, threads=False
                )
            else:
                # yfinance expects a string date; end=None -> through latest
                hist = yf.download(
                    ticker, interval=INTERVAL, start=start.strftime("%Y-%m-%d"),
                    auto_adjust=False, progress=False, threads=False
                )
            if hist is None or hist.empty:
                return None
            hist = hist.rename(
                columns={"Open":"open","High":"high","Low":"low","Close":"close","Adj Close":"adj_close","Volume":"volume"}
            )
            hist.index = pd.to_datetime(hist.index).tz_localize(None)
            hist = hist.reset_index().rename(columns={"index":"timestamp","Date":"timestamp"})
            hist["ticker"] = ticker
            cols = ["timestamp","open","high","low","close","adj_close","volume","ticker"]
            hist = hist[[c for c in cols if c in hist.columns]]
            return hist
        except Exception as e:
            if attempt == MAX_RETRIES:
                print(f"Failed {ticker} after {MAX_RETRIES} attempts: {e}")
                return None
            time.sleep(RETRY_SLEEP_SEC)
    return None


def _append_update(out_path: str, new_df: pd.DataFrame) -> None:
    """Append and de-duplicate on (timestamp,ticker)."""
    ensure_dir(os.path.dirname(out_path))
    if os.path.exists(out_path):
        try:
            old = pd.read_parquet(out_path)
            combo = pd.concat([old, new_df], ignore_index=True)
        except Exception:
            combo = new_df
    else:
        combo = new_df
    # Drop dups, sort
    combo["timestamp"] = pd.to_datetime(combo["timestamp"]).dt.tz_localize(None)
    combo = combo.drop_duplicates(subset=["timestamp","ticker"]).sort_values("timestamp")
    combo.to_parquet(out_path, index=False)


def main() -> None:
    cfg = load_configs()
    out_dir = _out_dir(cfg, "1d")
    ensure_dir(out_dir)

    if not HAVE_YF:
        print("yfinance not installed. pip install yfinance pandas pyarrow")
        return

    tickers = _maybe_add_benchmark(_load_universe_tickers(cfg), cfg.get("benchmark","SPY"))
    if not tickers:
        print("No tickers found in config/universe.yaml. Run build_universe.py first.")
        return

    force = os.environ.get("ROMULUS_FORCE_REFRESH","0") == "1"
    print(f"Incremental daily fetch for {len(tickers)} tickers (force={force})")

    for t in tickers:
        out_path = os.path.join(out_dir, f"{t}.parquet")
        start = None
        if (not force) and os.path.exists(out_path):
            try:
                last_ts = pd.read_parquet(out_path)["timestamp"].max()
                if pd.notna(last_ts):
                    # Fetch strictly after last saved bar
                    last_dt = pd.to_datetime(last_ts)
                    start = (last_dt + pd.Timedelta(days=1))
            except Exception:
                start = None

        df = _download_history(t, start=start)
        if df is None or df.empty:
            print(f"No new data for {t}")
            continue

        try:
            _append_update(out_path, df)
            print(f"Updated {out_path}")
        except Exception as e:
            print(f"Failed to write {t}: {e}")

    print("Fetch complete.")



main()
