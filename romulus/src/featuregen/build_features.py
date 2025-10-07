"""
Build engineered features for each timeframe defined in config/schema.yaml.

Inputs
- Resampled, PIT-safe panels per ticker:
  data/interim/resampled/<tf>/<TICKER>.parquet
  Required columns: timestamp, open, high, low, close, adj_close, volume, ticker
  Optional columns: is_synth, fund_*, macro_*

Config
- schema.yaml:
  featuresets:
    <name>:
      timeframe: "<tf>"
      indicators: [ {name:..., transform:..., window:...}, ... ]

Supported transforms (initial V1)
- SMA(window): simple moving average on 'adj_close'
- VWMA(window): volume-weighted moving average on 'adj_close' & 'volume'
- RSI(window): relative strength index using 'adj_close'
- MOMENTUM(window): adj_close / adj_close.shift(window) - 1
- ROLLING_VOL(window): rolling std of daily returns of 'adj_close'
- ATR(window): average true range using high, low, close

Output
- One feature file per ticker per timeframe:
  data/processed/features/<tf>/<TICKER>.parquet
  Columns: timestamp, ticker, <feature columns>, (plus base columns optionally if keep_base=True)

Notes
- All features are computed **without look-ahead** (purely backward-looking).
- We do not normalize here; normalization is a separate step.
- Missing values at the beginning of windows are expected; downstream will handle NaNs.
"""

import os
from typing import Dict, Any, List, Callable

import pandas as pd
import numpy as np
import yaml

from ..utils.io_utils import ensure_dir
from ..utils.io_utils import append_jsonl

RESAMPLED_ROOT = "data/interim/resampled"
OUT_ROOT = "data/processed/features"


# Transform implementations


def _sma(df: pd.DataFrame, window: int) -> pd.Series:
    return df["adj_close"].rolling(window=window, min_periods=window).mean()

def _vwma(df: pd.DataFrame, window: int) -> pd.Series:
    # Volume-weighted moving average on adj_close
    num = (df["adj_close"] * df["volume"]).rolling(window, min_periods=window).sum()
    den = df["volume"].rolling(window, min_periods=window).sum()
    out = num / den.replace(0, np.nan)
    return out.replace([np.inf, -np.inf], np.nan)


def _rsi(df: pd.DataFrame, window: int) -> pd.Series:
    # Wilder's RSI (safer implementation)
    delta = df["adj_close"].diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    alpha = 1.0 / float(window)
    avg_gain = up.ewm(alpha=alpha, adjust=False).mean()
    avg_loss = down.ewm(alpha=alpha, adjust=False).mean().replace(0, np.nan)
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.replace([np.inf, -np.inf], np.nan)

def _momentum(df: pd.DataFrame, window: int) -> pd.Series:
    return df["adj_close"].pct_change(periods=window)

def _rolling_vol(df: pd.DataFrame, window: int) -> pd.Series:
    ret = df["adj_close"].pct_change()
    return ret.rolling(window=window, min_periods=window).std()

# ATR uses unadjusted close for execution realism (not adj_close)
def _atr(df: pd.DataFrame, window: int) -> pd.Series:
    # True range using high, low, prev close (unadjusted, as execution uses trade close)
    prev_close = df["close"].shift(1)
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - prev_close).abs()
    tr3 = (df["low"] - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=window, min_periods=window).mean()

TRANSFORM_REGISTRY: Dict[str, Callable[[pd.DataFrame, int], pd.Series]] = {
    "SMA": _sma,
    "VWMA": _vwma,
    "RSI": _rsi,
    "MOMENTUM": _momentum,
    "ROLLING_VOL": _rolling_vol,
    "ATR": _atr,
}


# Helpers

def _log_provenance(timeframe: str, ticker: str, feature_cols: List[str], start_ts: pd.Timestamp, end_ts: pd.Timestamp) -> None:
    try:
        from ..utils.io_utils import append_jsonl
    except Exception:
        # Fallback: silent no-op if utils not available yet
        return

    record = {
        "timeframe": timeframe,
        "ticker": ticker,
        "features": feature_cols,
        "span": (
            pd.Timestamp(start_ts).strftime("%Y-%m-%d") if pd.notna(start_ts) else None,
            pd.Timestamp(end_ts).strftime("%Y-%m-%d") if pd.notna(end_ts) else None,
        ),
    }
    append_jsonl("data/meta/feature_provenance.jsonl", record)


def _load_schema(path: str = "config/schema.yaml") -> Dict[str, Any]:
    with open(path, "r") as f:
        return yaml.safe_load(f)

def _featuresets_by_timeframe(schema: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Returns mapping timeframe -> list of indicator dicts.
    """
    out: Dict[str, List[Dict[str, Any]]] = {}
    for _, spec in (schema.get("featuresets") or {}).items():
        tf = str(spec.get("timeframe", "")).strip().lower()
        indicators = spec.get("indicators", [])
        if tf and indicators:
            out.setdefault(tf, []).extend(indicators)
    return out

def _compute_features(panel: pd.DataFrame, indicators: List[Dict[str, Any]]) -> pd.DataFrame:
    # Compute features declared in schema; protect against duplicate names.
    feats = pd.DataFrame(index=panel.index)
    seen = set()

    for ind in indicators:
        name = ind.get("name")
        transform = ind.get("transform")
        window = int(ind.get("window", 0)) if "window" in ind else None

        if not name or not transform or transform not in TRANSFORM_REGISTRY:
            continue

        # Prevent duplicate feature names from clobbering each other
        if name in seen:
            base = name
            k = 2
            while f"{base}__{k}" in seen:
                k += 1
            name = f"{base}__{k}"
        seen.add(name)

        func = TRANSFORM_REGISTRY[transform]
        try:
            series = func(panel, window) if window is not None else func(panel, 0)
            feats[name] = series
        except Exception:
            # If a feature fails, skip it (keep pipeline running)
            continue

    return feats






def main() -> None:
    schema = _load_schema()
    tf_map = _featuresets_by_timeframe(schema)

    if not tf_map:
        print("No featuresets defined in config/schema.yaml. Nothing to build.")
        return

    for tf, indicators in tf_map.items():
        tf_dir = os.path.join(RESAMPLED_ROOT, tf)
        if not os.path.exists(tf_dir):
            print(f"Resampled data for timeframe {tf} not found at {tf_dir}. Skipping.")
            continue

        out_dir = os.path.join(OUT_ROOT, tf)
        ensure_dir(out_dir)

        files = [f for f in os.listdir(tf_dir) if f.endswith(".parquet")]
        print(f"Building features for {tf} from {len(files)} tickers...")
        for fname in files:
            src = os.path.join(tf_dir, fname)
            dst = os.path.join(out_dir, fname)
            try:
                df = pd.read_parquet(src)
                if df.empty:
                    continue

                # Index by timestamp for rolling ops
                df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
                panel = df.sort_values("timestamp").set_index("timestamp")
                
                # Check for Required Columns
                required = ["adj_close","close","high","low","volume"]
                missing = [c for c in required if c not in panel.columns]
                if missing:
                    print(f"Skip {fname}: missing columns {missing}")
                    continue
                for c in required:
                    panel[c] = pd.to_numeric(panel[c], errors="coerce")

                
                # Compute features per schema
                feats = _compute_features(panel, indicators)
                feats["ticker"] = df["ticker"].iloc[0]
                feats = feats.reset_index().rename(columns={"index": "timestamp"})

                # Merge feature frame with timestamp/ticker only (keep it lean here)
                out = feats[["timestamp", "ticker"] + [c for c in feats.columns if c not in ("timestamp", "ticker")]]

                ensure_dir(os.path.dirname(dst))
                out.to_parquet(dst, index=False)
                _log_provenance(
                    timeframe=tf,
                    ticker=df["ticker"].iloc[0],
                    feature_cols=[c for c in out.columns if c not in ("timestamp", "ticker")],
                    start_ts=panel.index.min(),
                    end_ts=panel.index.max(),
                    )
                print(f"Wrote {dst}")

            except Exception as e:
                print(f"Error building features for {fname}: {e}")

    print("Feature build complete.")



main()
