"""Data ingestion and caching utilities."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, List

import pandas as pd
import numpy as np
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


def load_cached_daily_data(tickers: List[str], start: str, end: str, cache_dir: str) -> pd.DataFrame:
    """Load cached history without making a network request."""
    frames: List[pd.DataFrame] = []
    cache_path = Path(cache_dir)
    for ticker in tickers:
        parts = []
        for path in sorted(cache_path.glob(f"{ticker}_*.parquet")):
            parts.append(_normalize_columns(pd.read_parquet(path), ticker))
        if not parts:
            raise FileNotFoundError(f"No cached price data found for {ticker} in {cache_path}")
        frame = pd.concat(parts).sort_index()
        frame = frame[~frame.index.duplicated(keep="last")]
        frame = frame.loc[pd.Timestamp(start):pd.Timestamp(end)]
        if frame.empty:
            raise ValueError(f"Cached data for {ticker} does not cover {start} to {end}")
        frames.append(frame)
    return pd.concat(frames, axis=1).sort_index()


def generate_synthetic_daily_data(tickers: List[str], start: str, end: str) -> pd.DataFrame:
    """Create deterministic, non-market OHLCV fixtures for offline demonstrations."""
    index = pd.bdate_range(start, end)
    frames: List[pd.DataFrame] = []
    for ordinal, ticker in enumerate(tickers):
        seed = int(hashlib.sha256(ticker.encode("utf-8")).hexdigest()[:8], 16)
        rng = np.random.default_rng(seed)
        cycle = np.sin(np.arange(len(index)) / (13.0 + ordinal)) * 0.0015
        innovations = rng.normal(0.00015 + ordinal * 0.00001, 0.007 + ordinal * 0.0002, len(index))
        close = 100.0 * np.exp(np.cumsum(innovations + cycle))
        overnight = rng.normal(0.0, 0.0015, len(index))
        open_price = close * np.exp(overnight)
        spread = np.abs(rng.normal(0.003, 0.001, len(index)))
        frame = pd.DataFrame(
            {
                "Open": open_price,
                "Close": close,
                "High": np.maximum(open_price, close) * (1.0 + spread),
                "Low": np.minimum(open_price, close) * (1.0 - spread),
                "Volume": 1_000_000 + rng.integers(0, 250_000, len(index)),
            },
            index=index,
        )
        frames.append(_normalize_columns(frame, ticker))
    return pd.concat(frames, axis=1).sort_index() if frames else pd.DataFrame()


def load_price_data(
    tickers: List[str], start: str, end: str, cache_dir: str, source: str = "yfinance"
) -> pd.DataFrame:
    """Load the configured data source with explicit offline semantics."""
    if source == "synthetic":
        return generate_synthetic_daily_data(tickers, start, end)
    if source == "cache":
        return load_cached_daily_data(tickers, start, end, cache_dir)
    return fetch_daily_data(tickers, start, end, cache_dir)
