"""Data ingestion and caching utilities."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, List

import pandas as pd
import yfinance as yf


def compute_checksum(df: pd.DataFrame) -> str:
    """Compute an MD5 checksum for a DataFrame."""
    if df.empty:
        return hashlib.md5(b"").hexdigest()

    hashed = pd.util.hash_pandas_object(df, index=True).values
    return hashlib.md5(hashed.tobytes()).hexdigest()


def _load_checksums(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _save_checksums(path: Path, checksums: Dict[str, str]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(checksums, handle, indent=2, sort_keys=True)


def _normalize_columns(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        level0 = df.columns.get_level_values(0)
        level1 = df.columns.get_level_values(1)
        price_fields = {"Open", "High", "Low", "Close", "Adj Close", "Volume"}
        if set(level0).intersection(price_fields):
            return df.swaplevel(0, 1, axis=1).sort_index(axis=1)
        if set(level1).intersection(price_fields):
            return df.copy()
        return df.copy()
    normalized = df.copy()
    normalized.columns = pd.MultiIndex.from_product([[ticker], df.columns])
    return normalized


def fetch_daily_data(
    tickers: List[str],
    start: str,
    end: str,
    cache_dir: str,
) -> pd.DataFrame:
    """Fetch daily data for tickers with per-ticker caching."""
    if not tickers:
        return pd.DataFrame()

    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)

    checksums_path = cache_path / "checksums.json"
    checksums = _load_checksums(checksums_path)

    frames: List[pd.DataFrame] = []
    for ticker in tickers:
        cache_file = cache_path / f"{ticker}_{start}_{end}.parquet"
        if cache_file.exists():
            df = pd.read_parquet(cache_file)
        else:
            df = yf.download(
                ticker,
                start=start,
                end=end,
                auto_adjust=True,
                progress=False,
            )
            df.to_parquet(cache_file)

        checksums[cache_file.name] = compute_checksum(df)
        frames.append(_normalize_columns(df, ticker))

    _save_checksums(checksums_path, checksums)

    combined = pd.concat(frames, axis=1).sort_index()
    return combined
