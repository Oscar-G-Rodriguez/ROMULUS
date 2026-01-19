"""ETF universe loading and inception-date gating."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, List


@dataclass(frozen=True)
class UniverseEntry:
    """Represents a single ETF in the universe."""

    ticker: str
    name: str
    inception_date: date


class Universe:
    """ETF universe with inception-date gating."""

    def __init__(self, entries: List[UniverseEntry]) -> None:
        """Initialize universe with validated entries."""
        self._entries = entries
        self._by_ticker: Dict[str, UniverseEntry] = {}
        for entry in entries:
            if entry.ticker in self._by_ticker:
                raise ValueError(f"Duplicate ticker in universe: {entry.ticker}")
            self._by_ticker[entry.ticker] = entry

    @classmethod
    def load_from_json(cls, path: str) -> "Universe":
        """Load universe definitions from a JSON file."""
        json_path = Path(path)
        if not json_path.exists():
            raise FileNotFoundError(f"Universe file not found: {path}")

        with json_path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)

        if "etfs" not in raw or not isinstance(raw["etfs"], list):
            raise ValueError("Universe JSON must contain a list under 'etfs'")

        entries: List[UniverseEntry] = []
        for item in raw["etfs"]:
            ticker = item.get("ticker")
            name = item.get("name")
            inception = item.get("inception_date")
            if not ticker or not name or not inception:
                raise ValueError("Each ETF must have ticker, name, and inception_date")
            entries.append(
                UniverseEntry(
                    ticker=str(ticker),
                    name=str(name),
                    inception_date=date.fromisoformat(str(inception)),
                )
            )

        return cls(entries)

    def get_eligible_tickers(self, as_of_date: date) -> List[str]:
        """Return tickers eligible as of the given date."""
        return [
            entry.ticker
            for entry in self._entries
            if as_of_date >= entry.inception_date
        ]

    def get_inception_date(self, ticker: str) -> date:
        """Return the inception date for a ticker."""
        if ticker not in self._by_ticker:
            raise KeyError(f"Ticker not found in universe: {ticker}")
        return self._by_ticker[ticker].inception_date
