"""
SOURCES:
- [SOURCE_PLACEHOLDER | LOCATION-TODO | data manager workflow]
DECISIONS:
- Provide a CLI for universe management and fetch/ingest workflow -> single-command usability -> UNSUPPORTED: workflow design
- Use provider modules to fetch and cache raw data -> traceability -> UNSUPPORTED: provider integration
"""

from __future__ import annotations

import argparse
import json
from typing import Dict, List

from import_user_market_data import run_import
from providers import provider_alpaca, provider_stooq, provider_yfinance
from universe_utils import (
    add_ticker,
    ensure_universe_file,
    read_universe,
    remove_ticker,
)

PROVIDERS = {
    "stooq": provider_stooq,
    "alpaca": provider_alpaca,
    "yfinance": provider_yfinance,
}


def _provider_or_exit(name: str):
    if name not in PROVIDERS:
        raise ValueError(f"Unknown provider: {name}")
    return PROVIDERS[name]


def cmd_init_universe(_: argparse.Namespace) -> int:
    symbols = ensure_universe_file()
    print(f"Universe size: {len(symbols)}")
    return 0


def cmd_add_ticker(args: argparse.Namespace) -> int:
    symbols = add_ticker(args.symbol)
    print(f"Universe size: {len(symbols)}")
    return 0


def cmd_remove_ticker(args: argparse.Namespace) -> int:
    symbols = remove_ticker(args.symbol)
    print(f"Universe size: {len(symbols)}")
    return 0


def cmd_fetch_history(args: argparse.Namespace) -> int:
    provider = _provider_or_exit(args.provider)
    result = provider.fetch_history(start=args.start, end=args.end)
    print(json.dumps(result, indent=2))
    return 0


def cmd_fetch_and_ingest(args: argparse.Namespace) -> int:
    provider = _provider_or_exit(args.provider)
    result = provider.fetch_history(start=args.start, end=args.end)
    fetch_run_id = result.get("fetch_run_id")
    if not fetch_run_id:
        print("Fetch failed: missing fetch_run_id")
        return 1

    vendor = args.provider
    dataset_id = f"{args.provider}_fetch_{fetch_run_id}"
    result = run_import(vendor=vendor, dataset_id=dataset_id, fetch_run_ids=[fetch_run_id])
    return int(result.get("code", 1))


def cmd_ingest(args: argparse.Namespace) -> int:
    result = run_import(
        vendor=args.vendor,
        dataset_id=args.dataset_id,
        fetch_run_ids=args.fetch_run_id,
    )
    return int(result.get("code", 1))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ROMULUS Data Manager")
    sub = parser.add_subparsers(dest="command", required=True)

    sub_init = sub.add_parser("init-universe", help="Ensure universe.csv exists")
    sub_init.set_defaults(func=cmd_init_universe)

    sub_add = sub.add_parser("add-ticker", help="Add a ticker to universe.csv")
    sub_add.add_argument("symbol", help="Ticker symbol")
    sub_add.set_defaults(func=cmd_add_ticker)

    sub_remove = sub.add_parser("remove-ticker", help="Remove a ticker from universe.csv")
    sub_remove.add_argument("symbol", help="Ticker symbol")
    sub_remove.set_defaults(func=cmd_remove_ticker)

    sub_fetch = sub.add_parser("fetch-history", help="Fetch daily OHLCV for universe")
    sub_fetch.add_argument("--provider", default="stooq", choices=PROVIDERS.keys())
    sub_fetch.add_argument("--start", default=None, help="YYYY-MM-DD")
    sub_fetch.add_argument("--end", default=None, help="YYYY-MM-DD")
    sub_fetch.set_defaults(func=cmd_fetch_history)

    sub_ingest = sub.add_parser("ingest", help="Ingest data/import into ROMULUS")
    sub_ingest.add_argument("--vendor", default="user_import")
    sub_ingest.add_argument("--dataset-id", default="user_import")
    sub_ingest.add_argument("--fetch-run-id", action="append", default=[])
    sub_ingest.set_defaults(func=cmd_ingest)

    sub_fetch_ingest = sub.add_parser(
        "fetch-and-ingest", help="Fetch history then ingest"
    )
    sub_fetch_ingest.add_argument("--provider", default="stooq", choices=PROVIDERS.keys())
    sub_fetch_ingest.add_argument("--start", default=None, help="YYYY-MM-DD")
    sub_fetch_ingest.add_argument("--end", default=None, help="YYYY-MM-DD")
    sub_fetch_ingest.set_defaults(func=cmd_fetch_and_ingest)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
