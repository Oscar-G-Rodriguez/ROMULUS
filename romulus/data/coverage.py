"""Point-in-time data coverage inspection used by the engine and desktop UI."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Literal

import pandas as pd

from romulus.data.ingestion import _normalize_columns
from romulus.calendar.trading_days import get_trading_days


REQUIRED_FIELDS = ("Open", "Close", "High", "Low", "Volume")


@dataclass(frozen=True)
class TickerCoverage:
    ticker: str
    first_date: str | None
    last_date: str | None
    observations: int
    missing_fields: tuple[str, ...]
    gap_count: int
    checksum: str


@dataclass(frozen=True)
class CoverageIndex:
    source: str
    policy: str
    proxy: str | None
    minimum_date: str | None
    maximum_date: str | None
    tickers: tuple[TickerCoverage, ...]

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["tickers"] = [asdict(item) for item in self.tickers]
        return payload


def _checksum(frame: pd.DataFrame) -> str:
    if frame.empty:
        return hashlib.sha256(b"").hexdigest()
    hashed = pd.util.hash_pandas_object(frame, index=True).to_numpy().tobytes()
    return hashlib.sha256(hashed).hexdigest()


def build_coverage_index(
    data: pd.DataFrame,
    tickers: Iterable[str],
    *,
    source: str,
    policy: Literal["dynamic", "common"] = "dynamic",
    proxy: str | None = "SPY",
    minimum_observations: int = 1,
) -> CoverageIndex:
    """Summarize usable OHLCV coverage without inventing or forward-filling data."""
    rows: list[TickerCoverage] = []
    valid_dates: dict[str, pd.DatetimeIndex] = {}
    for ticker in tickers:
        available = []
        missing_fields = []
        for field in REQUIRED_FIELDS:
            key = (ticker, field)
            if key not in data.columns:
                missing_fields.append(field)
            else:
                available.append(pd.to_numeric(data[key], errors="coerce").rename(field))
        if missing_fields or not available:
            rows.append(TickerCoverage(ticker, None, None, 0, tuple(missing_fields), 0, ""))
            continue
        complete = pd.concat(available, axis=1).dropna()
        complete = complete[(complete[["Open", "Close", "High", "Low"]] > 0).all(axis=1)]
        dates = pd.DatetimeIndex(pd.to_datetime(complete.index)).normalize().unique().sort_values()
        gaps = 0
        if len(dates) > 1:
            expected = pd.DatetimeIndex(
                pd.to_datetime(get_trading_days(dates[0].date().isoformat(), dates[-1].date().isoformat()))
            )
            gaps = max(0, len(expected.difference(dates)))
        valid_dates[ticker] = dates
        rows.append(
            TickerCoverage(
                ticker=ticker,
                first_date=dates[0].date().isoformat() if len(dates) else None,
                last_date=dates[-1].date().isoformat() if len(dates) else None,
                observations=len(dates),
                missing_fields=(),
                gap_count=gaps,
                checksum=_checksum(complete),
            )
        )

    valid = [row for row in rows if row.first_date and row.last_date]
    proxy_row = next((row for row in valid if row.ticker == proxy), None)
    if proxy_row is None and valid:
        proxy_row = valid[0]
        proxy = proxy_row.ticker
    if not valid or proxy_row is None:
        minimum = maximum = None
    else:
        usable_starts = {
            row.ticker: valid_dates[row.ticker][minimum_observations - 1].date().isoformat()
            for row in valid
            if len(valid_dates[row.ticker]) >= minimum_observations
        }
        if proxy_row.ticker not in usable_starts:
            return CoverageIndex(source, policy, proxy, None, None, tuple(rows))
        if policy == "common":
            if len(usable_starts) != len(valid):
                return CoverageIndex(source, policy, proxy, None, None, tuple(rows))
            minimum = max(usable_starts.values())
        else:
            minimum = max(usable_starts[proxy_row.ticker], min(usable_starts.values()))
        # A common safe end prevents stale-price valuation of a selected asset.
        maximum = min(row.last_date for row in valid)
        if minimum > maximum:
            minimum = maximum = None
    return CoverageIndex(source, policy, proxy, minimum, maximum, tuple(rows))


def snap_date(value: date, available_dates: Iterable[date], direction: Literal["forward", "backward"]) -> date:
    """Snap a requested date to a real available date in the requested direction."""
    ordered = sorted(set(available_dates))
    if not ordered:
        raise ValueError("No available dates")
    candidates = [item for item in ordered if item >= value] if direction == "forward" else [item for item in ordered if item <= value]
    if not candidates:
        raise ValueError(f"No available date {direction} from {value.isoformat()}")
    return candidates[0] if direction == "forward" else candidates[-1]


def inspect_cached_coverage(
    cache_dir: str | Path,
    tickers: Iterable[str],
    *,
    policy: Literal["dynamic", "common"] = "dynamic",
    proxy: str | None = "SPY",
    minimum_observations: int = 1,
) -> CoverageIndex:
    """Inspect cached parquet files only; this function never downloads data."""
    cache = Path(cache_dir)
    frames: list[pd.DataFrame] = []
    for ticker in tickers:
        parts = []
        for path in sorted(cache.glob(f"{ticker}_*.parquet")):
            try:
                parts.append(pd.read_parquet(path))
            except (OSError, ValueError):
                continue
        if parts:
            ticker_frame = pd.concat(parts).sort_index()
            ticker_frame = ticker_frame[~ticker_frame.index.duplicated(keep="last")]
            frames.append(_normalize_columns(ticker_frame, ticker))
    if not frames:
        return CoverageIndex("cache", policy, proxy, None, None, ())
    combined = pd.concat(frames, axis=1).sort_index()
    return build_coverage_index(
        combined,
        tickers,
        source="cache",
        policy=policy,
        proxy=proxy,
        minimum_observations=minimum_observations,
    )
