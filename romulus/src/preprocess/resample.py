"""
Resample 1d PIT-joined panels to coarser timeframes with correct OHLCV semantics.

Inputs
- data/interim/pit/1d/<TICKER>.parquet

Outputs
- data/interim/resampled/<tf>/<TICKER>.parquet for each tf in config.timeframes
  excluding '1d' and intraday frames (30m/60m) which require intraday ingest.

Rules
- OHLCV aggregation:
    open      = first open in period
    high      = max high
    low       = min low
    close     = last close
    adj_close = last adj_close
    volume    = sum
    is_synth  = any(is_synth) within bucket
- Non-price columns (fund_*, macro_*): forward-fill within the 1d frame then take LAST
  at period end (point-in-time safe).
- Weekly bars: anchored to Friday (or last session in week).
- Monthly bars: calendar month end.
- N-day bars (2d/3d/5d/2w/2m): rolling window bins starting from first available date.

Notes
- Only uses timeframes declared in config.config.yaml under `timeframes`.
- Skips intraday frames unless intraday ingest is enabled in the future.
"""

import os
from typing import Dict, Any, List, Tuple

import pandas as pd
import numpy as np

from ..utils.io_utils import load_configs, ensure_dir

PIT_1D_DIR = "data/interim/pit/1d"
OUT_ROOT   = "data/interim/resampled"


def _wanted_timeframes(cfg: Dict[str, Any]) -> List[str]:
    tfs = cfg.get("timeframes", [])
    # Keep only coarser-than-daily frames for now
    keep = []
    for tf in tfs:
        if tf in ("30m", "60m"):  # intraday not supported yet
            continue
        if tf == "1d":
            continue
        keep.append(tf)
    # Preserve order from config
    return keep


def _parse_tf(tf: str) -> Tuple[int, str]:
    """
    Return (n, unit) where unit in {'d','w','m'}.
    Examples: '2d'->(2,'d'), '1w'->(1,'w'), '2m'->(2,'m')
    """
    tf = tf.strip().lower()
    if tf.endswith("d"):
        return int(tf[:-1]), "d"
    if tf.endswith("w"):
        return int(tf[:-1]), "w"
    if tf.endswith("m"):
        return int(tf[:-1]), "m"
    raise ValueError(f"Unsupported timeframe: {tf}")


def _aggregate_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """
    Expect df indexed by timestamp within a single resample group.
    Compute OHLCV + adj_close + is_synth per group.
    """
    out = {}
    # Prices
    for col in ["open", "high", "low", "close", "adj_close"]:
        if col not in df.columns:
            continue
    # first/last helpers
    first_valid_idx = df["open"].first_valid_index()
    last_valid_idx  = df["close"].last_valid_index()

    out["open"]      = df["open"].iloc[0] if "open" in df.columns else np.nan
    out["high"]      = df["high"].max()   if "high" in df.columns else np.nan
    out["low"]       = df["low"].min()    if "low" in df.columns else np.nan
    out["close"]     = df["close"].iloc[-1] if "close" in df.columns else np.nan
    out["adj_close"] = df["adj_close"].iloc[-1] if "adj_close" in df.columns else np.nan
    out["volume"]    = df["volume"].sum() if "volume" in df.columns else 0.0
    out["is_synth"]  = bool(df.get("is_synth", pd.Series(False, index=df.index)).any())
    return pd.Series(out)


def _resample_ndays(panel: pd.DataFrame, n: int) -> pd.DataFrame:
    """
    N-day bins starting from the first timestamp.
    """
    g = (np.arange(len(panel)) // n)
    agg = panel.groupby(g).apply(_aggregate_ohlcv)
    agg.index = panel.index.to_series().groupby(g).last()  # label by last date in bin
    return agg


def _resample_weekly(panel: pd.DataFrame, n: int) -> pd.DataFrame:
    """
    Weekly resample anchored to Friday. For n>1, every n-th week.
    """
    # Ensure business day frequency; use pandas weekly with Fri anchor 'W-FRI'
    agg = panel.resample("W-FRI").apply(_aggregate_ohlcv)
    if n > 1:
        # Take every n-th period
        agg = agg.iloc[(np.arange(len(agg)) + 1) % n == 0]
    return agg


def _resample_monthly(panel: pd.DataFrame, n: int) -> pd.DataFrame:
    """
    Monthly resample anchored to calendar month end. For n>1, every n-th month end.
    """
    agg = panel.resample("M").apply(_aggregate_ohlcv)
    if n > 1:
        # Take every n-th month end
        agg = agg.iloc[(np.arange(len(agg)) + 1) % n == 0]
    return agg


def _forward_fill_nonprice(panel: pd.DataFrame, resampled: pd.DataFrame) -> pd.DataFrame:
    """
    Forward-fill non-price cols (fund_*, macro_*) within 1d, then take last
    observed within each resample bucket via asof alignment at period end.
    """
    nonprice_cols = [c for c in panel.columns if c.startswith("fund_") or c.startswith("macro_")]
    if not nonprice_cols:
        return resampled

    # As-of align last known values at each resampled index (period end)
    npanel = panel[nonprice_cols].copy()
    npanel = npanel.ffill()
    npanel = npanel.loc[~npanel.index.duplicated(keep="last")]

    aligned = pd.merge_asof(
        resampled.sort_index(),
        npanel.sort_index(),
        left_index=True,
        right_index=True,
        direction="backward",
    )
    return aligned


def main() -> None:
    cfg = load_configs()
    tfs = _wanted_timeframes(cfg)

    if not os.path.exists(PIT_1D_DIR):
        print(f"No PIT directory at {PIT_1D_DIR}. Run pit_join first.")
        return

    files = [f for f in os.listdir(PIT_1D_DIR) if f.endswith(".parquet")]
    if not files:
        print(f"No PIT files found in {PIT_1D_DIR}.")
        return

    print(f"Resampling {len(files)} tickers to: {tfs}")
    for fname in files:
        tkr = fname[:-8].upper()
        src = os.path.join(PIT_1D_DIR, fname)

        try:
            df = pd.read_parquet(src)
            if df.empty:
                continue

            # Set timestamp index
            df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
            df = df.sort_values("timestamp").set_index("timestamp")

            # Keep canonical columns we know how to aggregate
            # (We preserve any joined non-price columns by ffill later)
            base_cols = [c for c in ["open","high","low","close","adj_close","volume","is_synth","ticker"] if c in df.columns]
            panel = df[base_cols].copy()
            # Carry non-price cols separately
            other_cols = [c for c in df.columns if c not in base_cols]

            for tf in tfs:
                n, unit = _parse_tf(tf)
                out_dir = os.path.join(OUT_ROOT, tf)
                ensure_dir(out_dir)
                dst = os.path.join(out_dir, fname)

                if unit == "d":
                    agg = _resample_ndays(panel, n)
                elif unit == "w":
                    agg = _resample_weekly(panel, n)
                elif unit == "m":
                    agg = _resample_monthly(panel, n)
                else:
                    raise ValueError(f"Unsupported unit: {unit}")

                # Restore ticker then align non-price fields at period end
                agg["ticker"] = tkr
                if other_cols:
                    df_other = df[other_cols].copy()
                    agg = _forward_fill_nonprice(df_other, agg)

                # Finalize schema and write
                agg = agg.reset_index().rename(columns={"index":"timestamp"})
                agg = agg.dropna(subset=["close"])  # guard
                agg.to_parquet(dst, index=False)
                print(f"Wrote {dst}")

        except Exception as e:
            print(f"Error resampling {tkr}: {e}")

    print("Resample complete.")



main()
