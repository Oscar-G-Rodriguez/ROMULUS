"""
Point-in-time (PIT) join of fundamentals and macro data onto cleaned daily prices.

Inputs
- Cleaned daily prices per ticker:
    data/interim/prices/1d_clean/<TICKER>.parquet
  Columns: timestamp, open, high, low, close, adj_close, volume, ticker, is_synth

Optional inputs (if present; otherwise skipped)
- Fundamentals (per-ticker, point-in-time):
    data/raw/fundamentals.parquet        OR   data/interim/fundamentals.parquet
  Expected columns (case-insensitive; best-effort normalization):
    ticker, release_ts, asof_date, <any number of fundamental fields...>
  We require either `release_ts` (preferred, precise) OR `asof_date` (treated as a
  same-day release at 16:00 local/naive).

- Macro / cross-ticker data (global series):
    data/raw/macros.parquet              OR   data/interim/macros.parquet
  Expected columns:
    timestamp, <macro fields...>

Behavior
- For each ticker, we `merge_asof` fundamentals where `release_ts <= price.timestamp`.
  That ensures NO look-ahead. The most recent release as of each session is used.
- Macro series are merged as-of on `timestamp` for every ticker.
- Outputs one PIT-joined file per ticker:
    data/interim/pit/1d/<TICKER>.parquet

Notes
- If fundamentals or macros are missing, the join falls back to prices only.
- We prefix joined columns to avoid collisions:
    fundamentals -> "fund_<col>"
    macros       -> "macro_<col>"
- We do not change the active window here (already enforced in clean_align).
- We maintain `is_synth` column from price alignment.

Downstream
- Feature generation reads these PIT-joined files per ticker.
"""

import os
from typing import Dict, Any, List, Optional, Tuple

import pandas as pd

from ..utils.io_utils import load_configs, ensure_dir

PRICES_DIR = "data/interim/prices/1d_clean"
OUT_DIR    = "data/interim/pit/1d"

# Optional sources (first existing path wins for each)
FUND_PATHS = [
    "data/interim/fundamentals.parquet",
    "data/raw/fundamentals.parquet",
]
MACRO_PATHS = [
    "data/interim/macros.parquet",
    "data/raw/macros.parquet",
]


def _first_existing(paths: List[str]) -> Optional[str]:
    for p in paths:
        if os.path.exists(p):
            return p
    return None


def _load_fundamentals() -> Optional[pd.DataFrame]:
    """
    Load fundamentals if available and normalize columns:
    - Force `ticker` uppercase
    - Build a `release_ts` datetime column:
        prefer existing 'release_ts' (datetime-like)
        else derive from 'asof_date' at 16:00 (naive)
    - Sort by ['ticker','release_ts'] for merge_asof.
    """
    path = _first_existing(FUND_PATHS)
    if not path:
        return None

    f = pd.read_parquet(path)
    if f.empty:
        return None

    # Normalize column names to lowercase
    f.columns = [c.lower() for c in f.columns]

    if "ticker" not in f.columns:
        return None
    f["ticker"] = f["ticker"].astype(str).str.upper().str.strip()

    # Build release_ts
    if "release_ts" in f.columns:
        rel = pd.to_datetime(f["release_ts"], errors="coerce")
    elif "asof_date" in f.columns:
        # Treat as released at 16:00 on asof_date (naive)
        rel = pd.to_datetime(f["asof_date"], errors="coerce") + pd.Timedelta(hours=16)
    else:
        # No timing info => cannot do PIT join
        return None

    f["release_ts"] = rel.dt.tz_localize(None)
    f = f.dropna(subset=["release_ts"])

    # Drop any non-informative columns we handled
    keep_cols = [c for c in f.columns if c not in {"asof_date"}]
    f = f[keep_cols]

    # Sort for merge_asof
    f = f.sort_values(["ticker", "release_ts"]).reset_index(drop=True)
    return f


def _load_macros() -> Optional[pd.DataFrame]:
    """
    Load macro series if available. Normalize:
    - Must have 'timestamp' (datetime-like)
    - Any other columns are treated as macro fields and prefixed later
    """
    path = _first_existing(MACRO_PATHS)
    if not path:
        return None

    m = pd.read_parquet(path)
    if m.empty:
        return None

    m.columns = [c.lower() for c in m.columns]
    if "timestamp" not in m.columns:
        return None

    m["timestamp"] = pd.to_datetime(m["timestamp"], errors="coerce").dt.tz_localize(None)
    m = m.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

    # Keep only timestamp + data cols
    data_cols = [c for c in m.columns if c != "timestamp"]
    if not data_cols:
        return None
    return m[["timestamp"] + data_cols]


def _prefix_cols(df: pd.DataFrame, prefix: str, exclude: List[str]) -> pd.DataFrame:
    rename = {c: f"{prefix}{c}" for c in df.columns if c not in exclude}
    return df.rename(columns=rename)


def _pit_join_one(
    prices: pd.DataFrame,
    fundamentals: Optional[pd.DataFrame],
    macros: Optional[pd.DataFrame],
    ticker: str,
) -> pd.DataFrame:
    """
    PIT join fundamentals (per ticker) and macros (global) onto price frame.
    """
    p = prices.copy()
    p["timestamp"] = pd.to_datetime(p["timestamp"]).dt.tz_localize(None)
    p = p.sort_values("timestamp")

    # Fundamentals: filter to ticker, then merge_asof on release_ts <= timestamp
    if fundamentals is not None and not fundamentals.empty:
        f_tkr = fundamentals[fundamentals["ticker"] == ticker]
        if not f_tkr.empty:
            f_use = f_tkr.drop(columns=["ticker"])
            f_use = f_use.sort_values("release_ts")
            f_use = _prefix_cols(f_use, "fund_", exclude=["release_ts"])
            # merge_asof expects both frames sorted by the key
            p = pd.merge_asof(
                p.sort_values("timestamp"),
                f_use.sort_values("fund_release_ts"),
                left_on="timestamp",
                right_on="fund_release_ts",
                direction="backward",
            )
            # We don't need the key column afterward
            p = p.drop(columns=["fund_release_ts"])

    # Macros: asof merge on timestamp for all tickers
    if macros is not None and not macros.empty:
        m_use = _prefix_cols(macros, "macro_", exclude=["timestamp"])
        p = pd.merge_asof(
            p.sort_values("timestamp"),
            m_use.sort_values("timestamp"),
            on="timestamp",
            direction="backward",
        )

    return p


def main() -> None:
    cfg = load_configs()

    # Load optional sources once
    fundamentals = _load_fundamentals()
    macros = _load_macros()

    if not os.path.exists(PRICES_DIR):
        print(f"No cleaned prices directory at {PRICES_DIR}. Run clean_align first.")
        return

    ensure_dir(OUT_DIR)

    files = [f for f in os.listdir(PRICES_DIR) if f.endswith(".parquet")]
    if not files:
        print(f"No cleaned price files found in {PRICES_DIR}.")
        return

    print(f"PIT-joining fundamentals/macros onto {len(files)} tickers...")
    for fname in files:
        tkr = fname[:-8].upper()  # strip '.parquet'
        src = os.path.join(PRICES_DIR, fname)
        dst = os.path.join(OUT_DIR, fname)

        try:
            prices = pd.read_parquet(src)
            if prices.empty:
                continue

            pit = _pit_join_one(prices, fundamentals, macros, tkr)

            ensure_dir(os.path.dirname(dst))
            pit.to_parquet(dst, index=False)
            print(f"PIT joined {tkr} -> {dst}")
        except Exception as e:
            print(f"Error PIT-joining {tkr}: {e}")

    print("PIT join complete.")



main()
