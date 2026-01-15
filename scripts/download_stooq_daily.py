"""
SOURCES:
- [SOURCE_PLACEHOLDER | LOCATION-TODO | Stooq connector usage]
- [SOURCE_PLACEHOLDER | LOCATION-TODO | data contract guidance]
DECISIONS:
- Use StooqDailyReader for historical daily OHLCV -> free data source -> UNSUPPORTED: connector choice
- Enforce universe.csv as source of truth (write if --symbols provided) -> manual universe policy -> UNSUPPORTED: universe policy
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List

import pandas as pd
from pandas_datareader.data import StooqDailyReader

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
    parser = argparse.ArgumentParser(description="Download daily OHLCV from Stooq")
    parser.add_argument("--symbols", help="Comma-separated symbols")
    parser.add_argument("--start", help="Start date YYYY-MM-DD", default=None)
    parser.add_argument("--end", help="End date YYYY-MM-DD", default=None)
    args = parser.parse_args()

    symbols = load_symbols(args.symbols)

    ensure_runtime_dirs()
    conn = connect_db()
    init_ingestion_tables(conn)

    run_id = new_run_id()
    total_rows = 0
    errors = []

    for symbol in symbols:
        try:
            df = StooqDailyReader(symbol, start=args.start, end=args.end).read()
            df = df.reset_index()
            df.columns = [str(c).strip().lower() for c in df.columns]
            if "date" not in df.columns and "datetime" in df.columns:
                df = df.rename(columns={"datetime": "date"})
            df["symbol"] = symbol
            df, _stats = normalize_prices_df(df, "stooq", run_id)
            insert_prices(conn, df)
            total_rows += len(df)
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")

    sources = [
        "[SOURCE_PLACEHOLDER | LOCATION-TODO | Stooq connector usage]",
        "[SOURCE_PLACEHOLDER | LOCATION-TODO | data contract guidance]",
    ]

    universe_hash = compute_universe_hash(symbols)
    write_provenance(
        conn,
        run_id=run_id,
        vendor="stooq",
        dataset_id=json.dumps({"dataset_id": "stooq_daily", "symbols": symbols}),
        universe=json.dumps(symbols),
        universe_hash=universe_hash,
        universe_size=len(symbols),
        fetch_run_ids=[],
        adjustment_policy="stooq_default (PROVISIONAL)",
        cutoff_policy="as_of_download (PROVISIONAL)",
        quality_gates="required columns; non-negative prices/volume; duplicate (symbol,date) removed",
        sources=sources,
        notes="PROVISIONAL: connector policy pending citations",
    )

    report = {
        "run_id": run_id,
        "vendor": "stooq",
        "symbols": symbols,
        "total_rows": total_rows,
        "errors": errors,
    }
    write_quality_report(conn, run_id=run_id, report=report)

    report_path = Path("artifacts/ingestion_reports") / f"{run_id}.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="ascii")

    print(f"Stooq ingestion run_id: {run_id}")
    if errors:
        print("Errors:")
        for err in errors:
            print(f"- {err}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
