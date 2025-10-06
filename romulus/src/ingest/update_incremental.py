#!/usr/bin/env python3
"""
Incrementally update all cached tickers to the latest available date.

Example:
  python src/ingest/update_incremental.py --universe config/universe.yaml
"""

from __future__ import annotations
import argparse
import os
from typing import List

from ingest.fetch_prices import read_universe, fetch_and_save, RAW_DIR_DEFAULT  # type: ignore


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Incrementally update cached OHLCV for a universe.")
    p.add_argument("--universe", type=str, required=True, help="config/universe.yaml or file:set_name")
    p.add_argument("--raw-dir", type=str, default=RAW_DIR_DEFAULT)
    return p.parse_args()


def main():
    args = parse_args()
    tickers: List[str] = read_universe(args.universe)
    # start=None and years=None signals "increment from last cached date"
    fetch_and_save(tickers=tickers, raw_dir=args.raw_dir, start=None, end=None, years=None, force_rebuild=False)



main()
