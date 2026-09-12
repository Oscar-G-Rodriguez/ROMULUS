"""External feature ingestion (Nasdaq Data Link + pytrends)."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd
import requests

try:
    from pytrends.request import TrendReq
except Exception:  # pragma: no cover - optional dependency
    TrendReq = None

from romulus.data.ingestion import compute_checksum


DEFAULT_MACRO_SERIES = [
    "FRED/GDP",
    "FRED/CPIAUCSL",
    "FRED/UNRATE",
    "FRED/FEDFUNDS",
    "FRED/DGS10",
    "FRED/DGS2",
    "FRED/T10Y2Y",
    "FRED/DCOILWTICO",
]


def _slugify(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return safe.strip("_") or "series"


def _checksums_path(cache_dir: Path) -> Path:
    return cache_dir / "feature_checksums.json"


def _load_checksums(cache_dir: Path) -> Dict[str, str]:
    path = _checksums_path(cache_dir)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_checksums(cache_dir: Path, checksums: Dict[str, str]) -> None:
    path = _checksums_path(cache_dir)
    path.write_text(json.dumps(checksums, indent=2, sort_keys=True), encoding="utf-8")


def _update_checksum(cache_dir: Path, name: str, df: pd.DataFrame) -> None:
    checksums = _load_checksums(cache_dir)
    checksums[name] = compute_checksum(df)
    _save_checksums(cache_dir, checksums)


def fetch_quandl_series(
    codes: Iterable[str],
    api_key: str,
    cache_dir: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> pd.DataFrame:
    """Fetch macro series from Nasdaq Data Link (Quandl) with caching."""
    cache_path = Path(cache_dir) / "quandl"
    cache_path.mkdir(parents=True, exist_ok=True)

    frames: List[pd.DataFrame] = []
    for code in codes:
        safe_code = _slugify(code)
        cache_file = cache_path / f"{safe_code}.parquet"
        if cache_file.exists():
            df = pd.read_parquet(cache_file)
        else:
            params = {"api_key": api_key}
            if start:
                params["start_date"] = start
            if end:
                params["end_date"] = end
            url = f"https://data.nasdaq.com/api/v3/datasets/{code}.json"
            response = requests.get(url, params=params, timeout=30)
            if response.status_code != 200:
                print(f"Warning: Nasdaq Data Link fetch failed for {code}: {response.status_code}")
                continue
            payload = response.json()
            dataset = payload.get("dataset") or payload.get("dataset_data")
            if dataset is None:
                print(f"Warning: Nasdaq Data Link payload missing dataset for {code}")
                continue
            data = dataset.get("data")
            columns = dataset.get("column_names")
            if not data or not columns or "Date" not in columns:
                print(f"Warning: Nasdaq Data Link payload missing data for {code}")
                continue
            df = pd.DataFrame(data, columns=columns)
            df["Date"] = pd.to_datetime(df["Date"]).dt.date
            value_cols = [col for col in df.columns if col != "Date"]
            if not value_cols:
                continue
            df = df[["Date", value_cols[0]]].rename(columns={value_cols[0]: code})
            df = df.sort_values("Date").set_index("Date")
            df.to_parquet(cache_file)

        if df.empty:
            continue
        df.index = pd.to_datetime(df.index).date
        frames.append(df.rename(columns={df.columns[0]: code}))
        _update_checksum(Path(cache_dir), f"quandl:{code}", df)

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, axis=1).sort_index()
    return combined


def fetch_pytrends_series(
    keywords: Iterable[str],
    cache_dir: str,
    start: str,
    end: str,
    sleep_seconds: float = 1.0,
) -> pd.DataFrame:
    """Fetch pytrends series (cached per keyword)."""
    if TrendReq is None:
        raise ValueError("pytrends is not installed; install with extras [ml]")

    cache_path = Path(cache_dir) / "pytrends"
    cache_path.mkdir(parents=True, exist_ok=True)

    timeframe = f"{start} {end}"
    frames: List[pd.DataFrame] = []
    client = TrendReq(hl="en-US", tz=0)

    for keyword in keywords:
        safe_kw = _slugify(keyword)
        cache_file = cache_path / f"{safe_kw}_{start}_{end}.parquet"
        if cache_file.exists():
            df = pd.read_parquet(cache_file)
        else:
            client.build_payload([keyword], timeframe=timeframe)
            df = client.interest_over_time()
            if df.empty:
                continue
            if "isPartial" in df.columns:
                df = df.drop(columns=["isPartial"])
            df.to_parquet(cache_file)
            time.sleep(max(0.0, sleep_seconds))

        if df.empty:
            continue
        df.index = pd.to_datetime(df.index).date
        series = df.rename(columns={df.columns[0]: keyword})
        frames.append(series)
        _update_checksum(Path(cache_dir), f"pytrends:{keyword}", series)

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, axis=1).sort_index()
    return combined


def align_features_to_dates(
    df: pd.DataFrame,
    target_dates: Iterable,
    availability_column: str = "available_date",
) -> pd.DataFrame:
    """Align features by publication/availability date, never observation date.

    Point-in-time safety cannot be recovered from an observation timestamp.
    Callers must supply an explicit availability date (for example from a
    vintage-aware macro export); otherwise the feature is rejected.
    """
    if df.empty:
        return df
    if availability_column not in df.columns:
        raise ValueError(
            f"External features require an explicit {availability_column!r} column; "
            "observation-date alignment is not point-in-time safe."
        )
    target_index = pd.Index(pd.to_datetime(list(target_dates)).date)
    aligned = df.copy()
    aligned.index = pd.to_datetime(aligned.pop(availability_column)).dt.date
    aligned = aligned[~aligned.index.duplicated(keep="last")].sort_index()
    aligned = aligned.reindex(target_index, method="ffill").fillna(0.0)
    return aligned
