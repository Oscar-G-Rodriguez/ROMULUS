#!/usr/bin/env python3
"""
Create labels for a daily-anchored panel.

Reads:
  - data/interim/daily_panel.parquet
  - config/schema.yaml (label spec for 'daily_5d')

Writes:
  - data/labels/daily_5d/y.parquet with columns: date, Ticker, y_5
"""

from __future__ import annotations
import os
from typing import Dict, Any

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


def make_labels(
    schema_path: str = "config/schema.yaml",
    interim_path: str = "data/interim/daily_panel.parquet",
    out_dir: str = "data/labels",
    label_block: str = "daily_5d",
) -> str:
    schema = _read_yaml(schema_path)
    df = pd.read_parquet(interim_path).sort_values(["Ticker", "date"]).reset_index(drop=True)

    spec = schema.get("labels", {}).get(label_block)
    if not spec or spec.get("anchor") != "daily":
        raise ValueError(f"Label block '{label_block}' not found or not daily-anchored in schema.yaml")

    definition = spec["definition"]
    name = definition["name"]
    params = definition.get("params", {})
    col = params.get("col", "Close")
    horizon_days = int(params.get("horizon_days", 5))

    # forward log return: log(C[t+H] / C[t]) within each ticker
    if col not in df.columns:
        raise ValueError(f"Column '{col}' not in interim panel")
    df[name] = (
        df.groupby("Ticker")[col]
          .apply(lambda s: np.log(s.shift(-horizon_days) / s))
          .values
    )

    out = df[["date", "Ticker", name]].dropna().reset_index(drop=True)

    # write
    target_dir = os.path.join(out_dir, label_block)
    os.makedirs(target_dir, exist_ok=True)
    out_path = os.path.join(target_dir, "y.parquet")
    out.to_parquet(out_path, index=False)
    return out_path


def main():
    path = make_labels()
    print(f"Wrote labels to {path}")


main()
