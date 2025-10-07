#!/usr/bin/env python3
"""
Point-in-time (PIT) join utilities for Romulus.

Capabilities
- As-of join slow-moving series to a fast panel without look-ahead:
  * Mode A (timestamp):   use `release_ts` (available from this instant onward)
  * Mode B (intervals):   use `valid_from`, `valid_to` windows
- Optional per-entity joins via `by` keys (e.g., ["Ticker"]); if not present in the
  slow table, performs a global join (same slow series for all).
- Adds age columns (days since release/valid_from) when requested.
- Works for macro (single series with `series`, `value`) or wide fundamentals.

Typical usage
    fast = pd.read_parquet("data/interim/daily_panel.parquet")
    slow = pd.read_parquet("data/raw/macro/VIX.parquet")  # columns: date,value,series,release_ts,...
    out  = pit_asof_join(
              fast_df=fast,
              slow_df=slow.rename(columns={"value":"VIX"}),
              fast_time_col="date",
              slow_time_col="release_ts",
              by=None,
              add_age_days=True,
              age_col_name="VIX_age_days",
              keep_cols=["VIX"]
           )

Notes
- Input frames MUST be timezone-naive UTC per CONVENTIONS.md.
- For interval mode, rows with fast_time >= valid_to are treated as not available.
"""

from __future__ import annotations
from typing import Iterable, List, Optional, Sequence, Tuple, Dict

import numpy as np
import pandas as pd


def _ensure_cols(df: pd.DataFrame, cols: Iterable[str], name: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"{name} is missing required columns: {missing}")


def _normalize_time(df: pd.DataFrame, cols: Iterable[str]) -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        if c in out.columns:
            out[c] = pd.to_datetime(out[c]).dt.tz_localize(None)
    return out


def _merge_asof_simple(
    fast: pd.DataFrame,
    slow: pd.DataFrame,
    fast_time_col: str,
    slow_time_col: str,
) -> pd.DataFrame:
    # Assumes already filtered to the appropriate 'by' key if needed
    f = fast.sort_values(fast_time_col)
    s = slow.sort_values(slow_time_col)
    return pd.merge_asof(
        f,
        s,
        left_on=fast_time_col,
        right_on=slow_time_col,
        direction="backward",
        allow_exact_matches=True,
    )


def _interval_join_per_group(
    fast: pd.DataFrame,
    slow: pd.DataFrame,
    fast_time_col: str,
    valid_from_col: str,
    valid_to_col: str,
) -> pd.DataFrame:
    """
    Interval availability: a slow row applies when
        valid_from <= fast_time < valid_to (or valid_to is NaT)
    Strategy: merge_asof on valid_from, then mask rows where fast_time >= valid_to.
    """
    f = fast.sort_values(fast_time_col)
    s = slow.sort_values(valid_from_col)

    tmp = pd.merge_asof(
        f,
        s,
        left_on=fast_time_col,
        right_on=valid_from_col,
        direction="backward",
        allow_exact_matches=True,
    )

    if valid_to_col in tmp.columns:
        mask_invalid = tmp[valid_to_col].notna() & (tmp[fast_time_col] >= tmp[valid_to_col])
        tmp.loc[mask_invalid, [c for c in s.columns if c not in {valid_from_col, valid_to_col}]] = np.nan
    return tmp


def _maybe_filter_by_keys(slow: pd.DataFrame, by: Optional[Sequence[str]], key_vals: Tuple) -> pd.DataFrame:
    if not by:
        return slow
    # Keys present in slow? If not, treat as global series.
    missing = [k for k in by if k not in slow.columns]
    if missing:
        return slow
    cond = pd.Series(True, index=slow.index)
    for k, v in zip(by, key_vals):
        cond &= (slow[k] == v)
    return slow.loc[cond]


def _compute_age_days(fast_time: pd.Series, event_ts: pd.Series) -> pd.Series:
    delta = (fast_time - event_ts).dt.total_seconds() / 86400.0
    return pd.Series(delta).where(event_ts.notna(), np.nan)


def pit_asof_join(
    fast_df: pd.DataFrame,
    slow_df: pd.DataFrame,
    *,
    fast_time_col: str = "date",
    slow_time_col: Optional[str] = None,           # e.g., "release_ts" for timestamp mode
    valid_from_col: Optional[str] = None,          # set both valid_from and valid_to for interval mode
    valid_to_col: Optional[str] = None,
    by: Optional[Sequence[str]] = None,            # e.g., ["Ticker"]; if missing in slow_df, uses global join
    keep_cols: Optional[Sequence[str]] = None,     # slow columns to retain (besides time/keys)
    add_age_days: bool = True,
    age_col_name: Optional[str] = None,            # if None, will create <col>_age_days for each keep col (timestamp mode)
    prefix: Optional[str] = None,                  # optional prefix for retained slow columns
) -> pd.DataFrame:
    """so
    Generic PIT join: joins slow_df to fast_df without look-ahead.

    Returns fast_df plus selected slow columns.
    """
    if (slow_time_col is None) == (valid_from_col is None or valid_to_col is None):
        raise ValueError("Specify either slow_time_col (timestamp mode) OR both valid_from_col and valid_to_col (interval mode), but not both.")

    if by and not isinstance(by, (list, tuple)):
        by = [by]  # type: ignore

    # Normalize time columns
    fast = _normalize_time(fast_df, [fast_time_col])
    slow = _normalize_time(
        slow_df,
        [c for c in [slow_time_col, valid_from_col, valid_to_col] if c],
    )

    # Decide which slow columns to keep
    exclude = set([c for c in [slow_time_col, valid_from_col, valid_to_col] if c] + list(by or []))
    if keep_cols is None:
        keep_cols = [c for c in slow.columns if c not in exclude]
    keep_cols = list(keep_cols)

    # Prepare output frame
    out_frames: List[pd.DataFrame] = []

    if by:
        # group by keys from fast; for keys absent in slow we fallback to global
        for key_vals, fast_grp in fast.groupby(list(by), dropna=False):
            if not isinstance(key_vals, tuple):
                key_vals = (key_vals,)
            slow_sel = _maybe_filter_by_keys(slow, by, key_vals)

            if slow_time_col:
                joined = _merge_asof_simple(fast_grp, slow_sel, fast_time_col, slow_time_col)
                event_col = slow_time_col
            else:
                joined = _interval_join_per_group(fast_grp, slow_sel, fast_time_col, valid_from_col, valid_to_col)  # type: ignore
                event_col = valid_from_col  # best proxy for "age since availability"

            cols_to_keep = list(fast_grp.columns) + [c for c in keep_cols if c in joined.columns]
            if add_age_days and event_col in joined.columns:
                base_name = age_col_name or None
                if base_name:
                    joined[base_name] = _compute_age_days(joined[fast_time_col], joined[event_col])
                    cols_to_keep += [base_name]
                else:
                    # add per-feature ages in timestamp mode; for interval mode, one age vs valid_from
                    age_base = (event_col or "event_ts")
                    joined[f"{age_base}_age_days"] = _compute_age_days(joined[fast_time_col], joined[event_col])
                    cols_to_keep += [f"{age_base}_age_days"]

            out_frames.append(joined[cols_to_keep])
    else:
        # global series
        if slow_time_col:
            joined = _merge_asof_simple(fast, slow, fast_time_col, slow_time_col)
            event_col = slow_time_col
        else:
            joined = _interval_join_per_group(fast, slow, fast_time_col, valid_from_col, valid_to_col)  # type: ignore
            event_col = valid_from_col

        cols_to_keep = list(fast.columns) + [c for c in keep_cols if c in joined.columns]
        if add_age_days and event_col in joined.columns:
            base_name = age_col_name or None
            if base_name:
                joined[base_name] = _compute_age_days(joined[fast_time_col], joined[event_col])
                cols_to_keep += [base_name]
            else:
                age_base = (event_col or "event_ts")
                joined[f"{age_base}_age_days"] = _compute_age_days(joined[fast_time_col], joined[event_col])
                cols_to_keep += [f"{age_base}_age_days"]
        out_frames.append(joined[cols_to_keep])

    out = pd.concat(out_frames, axis=0, ignore_index=True) if out_frames else fast.copy()

    # Optional prefixing for slow columns to avoid collisions
    if prefix:
        rename_map = {c: f"{prefix}{c}" for c in keep_cols if c in out.columns}
        out = out.rename(columns=rename_map)

    # Sort back to canonical order
    sort_cols = [c for c in ["Ticker", fast_time_col] if c in out.columns]
    return out.sort_values(sort_cols).reset_index(drop=True)


def pivot_series_to_wide(
    slow_df: pd.DataFrame,
    series_col: str = "series",
    value_col: str = "value",
    keep_time: str = "release_ts",
    extra_cols: Optional[Sequence[str]] = None,
    prefix: str = "",
) -> pd.DataFrame:
    """
    Turn a tall macro table (series,value,release_ts,...) into wide columns per series.
    Example input:
        date | value | series | release_ts | valid_from | valid_to
    Output columns (wide):
        release_ts | <prefix>VIX | <prefix>TNX | ...
    """
    cols = [keep_time, series_col, value_col] + list(extra_cols or [])
    _ensure_cols(slow_df, cols, "slow_df")
    df = slow_df[cols].copy()
    wide = df.pivot_table(index=keep_time, columns=series_col, values=value_col, aggfunc="last").reset_index()
    if prefix:
        wide = wide.rename(columns={c: f"{prefix}{c}" for c in wide.columns if c != keep_time})
    return wide


def main():
    # Library module: no side effects when called.
    # You can import and use:
    #   - pit_asof_join()
    #   - pivot_series_to_wide()
    print("pit_join utilities ready")
    return


main()
