"""
SOURCES:
- [SOURCE_PLACEHOLDER | LOCATION-TODO | Alpaca market data usage]
- [SOURCE_PLACEHOLDER | LOCATION-TODO | data contract guidance]
DECISIONS:
- Use alpaca-py for recent/current bars -> supported market data API -> UNSUPPORTED: connector choice
- Require API keys via env vars -> avoid hardcoding secrets -> UNSUPPORTED: key handling
- Enforce universe.csv as source of truth (write if --symbols provided) -> manual universe policy -> UNSUPPORTED: universe policy
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import List

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from ingestion_utils import (
    connect_db,
    ensure_runtime_dirs,
    init_ingestion_tables,
    insert_prices,
    new_run_id,
    normalize_prices_df,
    write_provenance,
    write_quality_report,
)
from universe_utils import (
    compute_universe_hash,
    ensure_universe_file,
    read_universe,
    write_universe,
)


def load_symbols(symbols_arg: str | None) -> List[str]:
    if symbols_arg:
        symbols = [s.strip() for s in symbols_arg.split(",") if s.strip()]
        write_universe(symbols)
        print("WARNING: manual universe policy enforces universe.csv as source of truth.")
    ensure_universe_file()
    return read_universe(Path("data/import/universe.csv"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Download daily bars from Alpaca")
    parser.add_argument("--symbols", help="Comma-separated symbols")
    parser.add_argument("--start", help="Start date YYYY-MM-DD", default=None)
    parser.add_argument("--end", help="End date YYYY-MM-DD", default=None)
    args = parser.parse_args()

    api_key = os.getenv("APCA_API_KEY_ID")
    api_secret = os.getenv("APCA_API_SECRET_KEY")
    if not api_key or not api_secret:
        print("Missing APCA_API_KEY_ID/APCA_API_SECRET_KEY env vars")
        return 1

    symbols = load_symbols(args.symbols)

    ensure_runtime_dirs()
    conn = connect_db()
    init_ingestion_tables(conn)

    client = StockHistoricalDataClient(api_key, api_secret)
    run_id = new_run_id()

    request = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Day,
        start=args.start,
        end=args.end,
    )

    bars = client.get_stock_bars(request)
    df = bars.df
    if df.empty:
        print("No bars returned")
        return 1

    df = df.reset_index()
    if "timestamp" in df.columns:
        df = df.rename(columns={"timestamp": "date"})
    if "symbol" not in df.columns and "symbol" in df.index.names:
        df = df.reset_index()

    df, _stats = normalize_prices_df(df, "alpaca", run_id)
    insert_prices(conn, df)

    sources = [
        "[SOURCE_PLACEHOLDER | LOCATION-TODO | Alpaca market data usage]",
        "[SOURCE_PLACEHOLDER | LOCATION-TODO | data contract guidance]",
    ]

    universe_hash = compute_universe_hash(symbols)
    write_provenance(
        conn,
        run_id=run_id,
        vendor="alpaca",
        dataset_id=json.dumps({"dataset_id": "alpaca_daily", "symbols": symbols}),
        universe=json.dumps(symbols),
        universe_hash=universe_hash,
        universe_size=len(symbols),
        fetch_run_ids=[],
        adjustment_policy="alpaca_default (PROVISIONAL)",
        cutoff_policy="as_of_download (PROVISIONAL)",
        quality_gates="required columns; non-negative prices/volume; duplicate (symbol,date) removed",
        sources=sources,
        notes="PROVISIONAL: connector policy pending citations",
    )

    report = {
        "run_id": run_id,
        "vendor": "alpaca",
        "symbols": symbols,
        "total_rows": int(len(df)),
    }
    write_quality_report(conn, run_id=run_id, report=report)

    report_path = Path("artifacts/ingestion_reports") / f"{run_id}.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="ascii")

    print(f"Alpaca ingestion run_id: {run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
