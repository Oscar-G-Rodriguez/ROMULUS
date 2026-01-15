"""
SOURCES:
- [SOURCE_PLACEHOLDER | LOCATION-TODO | data ingestion rules]
DECISIONS:
- Accept CSV/Parquet from data/import -> user-provided data source -> UNSUPPORTED: ingest formats
- Require universe.csv as the sole universe definition -> manual ticker control -> UNSUPPORTED: universe policy
- Normalize to prices_daily schema -> consistent research feed -> UNSUPPORTED: schema choice
- Write provenance and quality report artifacts -> traceability requirement -> UNSUPPORTED: provenance rules
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

import pandas as pd

from ingestion_utils import (
    CANONICAL_REQUIRED_COLUMNS,
    connect_db,
    ensure_runtime_dirs,
    init_ingestion_tables,
    insert_prices,
    new_run_id,
    normalize_prices_df,
    write_provenance,
    write_quality_report,
)
from universe_utils import compute_universe_hash, ensure_universe_file, read_universe


def collect_input_files(import_dir: Path) -> List[Path]:
    files = []
    for ext in ("*.csv", "*.parquet", "*.pq"):
        files.extend(import_dir.glob(ext))
    return [f for f in files if f.is_file() and f.name.lower() != "universe.csv"]


def read_file(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    return pd.read_parquet(path)


def run_import(
    *, vendor: str, dataset_id: str, fetch_run_ids: List[str] | None = None
) -> Dict:
    import_dir = Path("data/import")
    if not import_dir.exists():
        print("Missing data/import directory")
        return {"code": 1, "error": "missing data/import"}

    files = collect_input_files(import_dir)
    if not files:
        print("No CSV/Parquet files found in data/import")
        return {"code": 1, "error": "no input files"}

    ensure_universe_file()
    universe = read_universe(import_dir / "universe.csv")

    ensure_runtime_dirs()
    conn = connect_db()
    init_ingestion_tables(conn)

    run_id = new_run_id()
    total_rows = 0
    file_reports: List[Dict] = []
    errors: List[str] = []
    date_min = None
    date_max = None
    symbols_total = set()
    dropped_not_in_universe = 0

    for path in files:
        try:
            df = read_file(path)
            df, stats = normalize_prices_df(df, vendor, run_id)

            before_count = len(df)
            df = df[df["symbol"].isin(universe)]
            dropped_not_in_universe += max(0, before_count - len(df))

            insert_prices(conn, df)

            total_rows += len(df)
            if stats.date_min:
                date_min = stats.date_min if date_min is None else min(date_min, stats.date_min)
            if stats.date_max:
                date_max = stats.date_max if date_max is None else max(date_max, stats.date_max)
            symbols_total.update(df["symbol"].unique())

            file_reports.append(
                {
                    "file": path.name,
                    "rows": len(df),
                    "duplicates_dropped": stats.duplicates_dropped,
                    "invalid_rows": stats.invalid_rows,
                    "date_min": stats.date_min,
                    "date_max": stats.date_max,
                    "symbols": stats.symbols,
                }
            )
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")

    universe_hash = compute_universe_hash(universe)

    quality_report = {
        "run_id": run_id,
        "dataset_id": dataset_id,
        "vendor": vendor,
        "files": [p.name for p in files],
        "total_rows": total_rows,
        "date_min": date_min,
        "date_max": date_max,
        "symbols": sorted(symbols_total),
        "universe_hash": universe_hash,
        "universe_size": len(universe),
        "universe_symbols": universe,
        "dropped_not_in_universe": dropped_not_in_universe,
        "file_reports": file_reports,
        "errors": errors,
        "required_columns": CANONICAL_REQUIRED_COLUMNS,
        "fetch_run_ids": fetch_run_ids or [],
    }

    sources = [
        "[SOURCE_PLACEHOLDER | LOCATION-TODO | data ingestion rules]",
        "[SOURCE_PLACEHOLDER | LOCATION-TODO | data contract guidance]",
    ]

    write_provenance(
        conn,
        run_id=run_id,
        vendor=vendor,
        dataset_id=json.dumps({"dataset_id": dataset_id, "files": [p.name for p in files]}),
        universe=json.dumps(universe),
        universe_hash=universe_hash,
        universe_size=len(universe),
        fetch_run_ids=fetch_run_ids or [],
        adjustment_policy="as_provided (PROVISIONAL)",
        cutoff_policy="as_of_import (PROVISIONAL)",
        quality_gates=(
            "required columns; non-negative prices/volume; duplicate (symbol,date) removed; "
            "filtered to universe.csv"
        ),
        sources=sources,
        notes="PROVISIONAL: ingest rules pending citations",
    )

    write_quality_report(conn, run_id=run_id, report=quality_report)

    report_path = Path("artifacts/ingestion_reports") / f"{run_id}.json"
    report_path.write_text(json.dumps(quality_report, indent=2), encoding="ascii")

    print(f"Ingestion run_id: {run_id}")
    print(f"Quality report: {report_path}")
    if errors:
        print("Errors:")
        for err in errors:
            print(f"- {err}")

    return {
        "code": 0,
        "run_id": run_id,
        "report_path": str(report_path),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Import user market data into ROMULUS")
    parser.add_argument("--vendor", default="user_import", help="Vendor/source name")
    parser.add_argument("--dataset-id", default="user_import", help="Dataset identifier")
    parser.add_argument("--fetch-run-id", action="append", default=[], help="Fetch run id")
    args = parser.parse_args()

    result = run_import(
        vendor=args.vendor,
        dataset_id=args.dataset_id,
        fetch_run_ids=args.fetch_run_id,
    )
    return int(result.get("code", 1))


if __name__ == "__main__":
    raise SystemExit(main())
