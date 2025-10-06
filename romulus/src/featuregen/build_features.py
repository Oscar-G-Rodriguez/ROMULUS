#!/usr/bin/env python3
"""
Build model features for a daily-anchored panel.

Reads:
  - config/params.yaml (paths)
  - config/schema.yaml (feature list, params)
  - data/interim/daily_panel.parquet

Writes:
  - data/features/daily_5d/X.parquet (default horizon folder)
"""

from __future__ import annotations
import os
from typing import Dict, Any, List, Callable

import numpy as np
import pandas as pd

try:
    import yaml
except Exception:
    yaml = None


def _read_yaml(path: str) -> Dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML not installed. pip install pyyaml")
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


def _log_return_nd(close: pd.Series, n: int) -> pd.Series:
    return np.log(close / close.shift(n))


def _rolling_std(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=window).std()


def _rolling_mean(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=window).mean()


def _rsi(price: pd.Series, window: int = 14) -> pd.Series:
    delta = price.diff()
    up = delta.clip(lower=0.0)
    down = (-delta).clip(lower=0.0)
    roll_up = up.rolling(window, min_periods=window).mean()
    roll_down = down.rolling(window, min_periods=window).mean()
    rs = roll_up / roll_down.replace(0.0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


TRANSFORMS: Dict[str, Callable[..., pd.Series]] = {
    "log_return_1d": lambda close: np.log(close / close.shift(1)),
    "log_return_nd": _log_return_nd,
    "rolling_std": _rolling_std,
    "rolling_mean": _rolling_mean,
    "rsi": _rsi,
    "pct_change_n": lambda s, n: s.pct_change(n),
}


def _ensure_cols(df: pd.DataFrame, cols: List[str]) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")


def build_features(
    params_path: str = "config/params.yaml",
    schema_path: str = "config/schema.yaml",
    interim_path: str = "data/interim/daily_panel.parquet",
    out_dir: str = "data/features",
    feature_block: str = "daily_5d",
) -> str:
    params = _read_yaml(params_path)
    schema = _read_yaml(schema_path)

    df = pd.read_parquet(interim_path)
    _ensure_cols(df, ["date", "Ticker", "Close", "Volume"])

    spec = schema.get("features", {}).get(feature_block)
    if not spec or spec.get("anchor") != "daily":
        raise ValueError(f"Feature block '{feature_block}' not found or not daily-anchored in schema.yaml")

    # base frame
    out = df[["date", "Ticker", "Close", "Volume"]].copy()

    for item in spec.get("include", []):
        name = item["name"]
        src = item["source"]
        if item.get("passthrough"):
            # passthrough from interim.daily_panel
            if name not in df.columns and name != "dollar_vol":
                raise ValueError(f"Passthrough column '{name}' not found in interim panel")
            col = df[name] if name in df.columns else (df["Close"] * df["Volume"])
            out[name] = col
            continue

        transform = item.get("transform")
        if transform not in TRANSFORMS:
            raise ValueError(f"Unknown transform '{transform}' for feature '{name}'")

        params_local = item.get("params", {})
        if src == "daily_prices":
            # use Close unless a different col specified
            col_name = params_local.get("col", "Close")
            _ensure_cols(df, [col_name])
            series = df[col_name]
        elif src == "interim.daily_panel":
            # reference a column already in interim panel
            col_name = params_local.get("col", name)
            if col_name not in df.columns:
                raise ValueError(f"Column '{col_name}' not in interim panel for feature '{name}'")
            series = df[col_name]
        else:
            raise ValueError(f"Unsupported source '{src}' in feature '{name}'")

        # apply transform
        fn = TRANSFORMS[transform]
        feat = fn(series, **{k: v for k, v in params_local.items() if k != "col"}) if params_local else fn(series)
        out[name] = feat

    # housekeeping
    out = out.sort_values(["Ticker", "date"]).dropna().reset_index(drop=True)

    # write
    target_dir = os.path.join(out_dir, feature_block)
    os.makedirs(target_dir, exist_ok=True)
    out_path = os.path.join(target_dir, "X.parquet")
    out.to_parquet(out_path, index=False)
    return out_path


def main():
    path = build_features()
    print(f"Wrote features to {path}")


main()
