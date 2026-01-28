"""Storage utilities for Parquet and JSON."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict

import pandas as pd


def save_parquet(df: pd.DataFrame, path: str) -> None:
    """Save a DataFrame to a Parquet file."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)


def load_parquet(path: str) -> pd.DataFrame:
    """Load a DataFrame from a Parquet file."""
    return pd.read_parquet(path)


def save_json(data: Dict[str, Any], path: str) -> None:
    """Save a dictionary to a JSON file."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)


def load_json(path: str) -> Dict[str, Any]:
    """Load a dictionary from a JSON file."""
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def compute_dataframe_hash(df: pd.DataFrame) -> str:
    """Compute an MD5 hash for a DataFrame's structure and boundary rows."""
    if df.empty:
        return hashlib.md5(b"").hexdigest()

    columns = sorted(df.columns, key=lambda col: str(col))
    meta = [f"{col}:{df[col].dtype}" for col in columns]
    head = df.head(1).to_csv(index=True)
    tail = df.tail(1).to_csv(index=True)
    payload = "|".join(meta) + "|" + head + "|" + tail
    return hashlib.md5(payload.encode("utf-8")).hexdigest()
