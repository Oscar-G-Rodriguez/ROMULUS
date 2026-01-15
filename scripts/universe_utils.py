"""
SOURCES:
- [SOURCE_PLACEHOLDER | LOCATION-TODO | universe policy]
DECISIONS:
- Universe is defined only by data/import/universe.csv with column symbol -> manual control -> UNSUPPORTED: universe policy
- Default starter list is a small US mega-cap set -> usability -> UNSUPPORTED: default universe
- Normalize symbols to uppercase + trimmed -> consistent deduping -> UNSUPPORTED: symbol normalization
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path
from typing import Iterable, List

UNIVERSE_PATH = Path("data/import/universe.csv")
DEFAULT_TICKERS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"]


def normalize_symbol(symbol: str) -> str:
    if symbol is None:
        return ""
    return str(symbol).strip().upper()


def compute_universe_hash(symbols: Iterable[str]) -> str:
    cleaned = sorted({normalize_symbol(s) for s in symbols if s and s.strip()})
    joined = ",".join(cleaned)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def ensure_universe_file() -> List[str]:
    if UNIVERSE_PATH.exists():
        return read_universe(UNIVERSE_PATH)

    UNIVERSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_universe(DEFAULT_TICKERS)
    print("WARNING: data/import/universe.csv missing. Created with a starter list.")
    return list(DEFAULT_TICKERS)


def read_universe(path: Path) -> List[str]:
    if not path.exists():
        raise FileNotFoundError(f"Universe file not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if "symbol" not in (reader.fieldnames or []):
            raise ValueError("universe.csv must have a 'symbol' column")
        symbols = [normalize_symbol(row.get("symbol", "")) for row in reader]

    return sorted({s for s in symbols if s})


def write_universe(symbols: Iterable[str]) -> None:
    cleaned = sorted({normalize_symbol(s) for s in symbols if s and s.strip()})
    UNIVERSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with UNIVERSE_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["symbol"])
        for symbol in cleaned:
            writer.writerow([symbol])


def add_ticker(symbol: str) -> List[str]:
    symbols = ensure_universe_file()
    symbols.append(symbol)
    write_universe(symbols)
    return read_universe(UNIVERSE_PATH)


def remove_ticker(symbol: str) -> List[str]:
    symbols = ensure_universe_file()
    normalized = normalize_symbol(symbol)
    filtered = [s for s in symbols if s != normalized]
    write_universe(filtered)
    return read_universe(UNIVERSE_PATH)
