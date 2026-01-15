"""
SOURCES:
- [SOURCE_PLACEHOLDER | LOCATION-TODO | Stooq connector usage]
- [SOURCE_PLACEHOLDER | LOCATION-TODO | fetch provenance requirements]
DECISIONS:
- Fetch daily OHLCV for each symbol in universe.csv -> manual universe policy -> UNSUPPORTED: universe policy
- Cache raw provider output under data/cache/stooq -> reproducibility -> UNSUPPORTED: cache policy
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Dict, List, Optional

from providers.provider_utils import ensure_cache_dir, write_fetch_provenance
from universe_utils import ensure_universe_file, read_universe


def _new_run_id() -> str:
    return str(uuid.uuid4())


def fetch_history(
    *, symbols: Optional[List[str]] = None, start: Optional[str] = None, end: Optional[str] = None
) -> Dict:
    run_id = _new_run_id()
    if symbols is None:
        ensure_universe_file()
        symbols = read_universe(Path("data/import/universe.csv"))

    cache_dir = ensure_cache_dir("stooq", run_id)
    import_dir = Path("data/import")
    import_dir.mkdir(parents=True, exist_ok=True)

    per_ticker_status: Dict[str, Dict[str, str]] = {}
    import_files: List[str] = []

    try:
        from pandas_datareader.data import StooqDailyReader
    except Exception as exc:
        for symbol in symbols:
            per_ticker_status[symbol] = {
                "status": "failed",
                "message": f"missing pandas_datareader: {exc}",
            }
        provenance_path = write_fetch_provenance(
            run_id=run_id,
            provider="stooq",
            symbols=symbols,
            date_start=start,
            date_end=end,
            per_ticker_status=per_ticker_status,
            sources=["[SOURCE_PLACEHOLDER | LOCATION-TODO | Stooq connector usage]"],
            notes="PROVISIONAL: connector usage pending citations",
        )
        return {
            "fetch_run_id": run_id,
            "provider": "stooq",
            "provenance_path": str(provenance_path),
            "cache_dir": str(cache_dir),
            "import_files": import_files,
            "per_ticker_status": per_ticker_status,
        }

    for symbol in symbols:
        try:
            df = StooqDailyReader(symbol, start=start, end=end).read()
            if df.empty:
                per_ticker_status[symbol] = {"status": "no_data", "message": "empty"}
                continue

            df_reset = df.reset_index()
            raw_path = cache_dir / f"{symbol}.csv"
            df_reset.to_csv(raw_path, index=False)

            df_import = df_reset.copy()
            if "symbol" not in df_import.columns:
                df_import["symbol"] = symbol

            import_path = import_dir / f"stooq_{run_id}_{symbol}.csv"
            df_import.to_csv(import_path, index=False)
            import_files.append(str(import_path))

            per_ticker_status[symbol] = {"status": "ok", "rows": str(len(df_import))}
        except Exception as exc:
            per_ticker_status[symbol] = {"status": "failed", "message": str(exc)}

    provenance_path = write_fetch_provenance(
        run_id=run_id,
        provider="stooq",
        symbols=symbols,
        date_start=start,
        date_end=end,
        per_ticker_status=per_ticker_status,
        sources=["[SOURCE_PLACEHOLDER | LOCATION-TODO | Stooq connector usage]"],
        notes="PROVISIONAL: connector usage pending citations",
    )

    return {
        "fetch_run_id": run_id,
        "provider": "stooq",
        "provenance_path": str(provenance_path),
        "cache_dir": str(cache_dir),
        "import_files": import_files,
        "per_ticker_status": per_ticker_status,
    }


def update_latest(*, symbols: Optional[List[str]] = None) -> Dict:
    return fetch_history(symbols=symbols, start=None, end=None)
