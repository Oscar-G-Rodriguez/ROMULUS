"""
SOURCES:
- [SOURCE_PLACEHOLDER | LOCATION-TODO | yfinance usage]
- [SOURCE_PLACEHOLDER | LOCATION-TODO | fetch provenance requirements]
DECISIONS:
- Use yfinance only when explicitly selected -> unofficial fallback -> UNSUPPORTED: fallback policy
- Mark yfinance runs as best-effort in provenance -> transparency -> UNSUPPORTED: best-effort policy
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

    cache_dir = ensure_cache_dir("yfinance", run_id)
    import_dir = Path("data/import")
    import_dir.mkdir(parents=True, exist_ok=True)

    per_ticker_status: Dict[str, Dict[str, str]] = {}
    import_files: List[str] = []

    try:
        import yfinance as yf
    except Exception as exc:
        for symbol in symbols:
            per_ticker_status[symbol] = {
                "status": "failed",
                "message": f"missing yfinance: {exc}",
            }
        provenance_path = write_fetch_provenance(
            run_id=run_id,
            provider="yfinance",
            symbols=symbols,
            date_start=start,
            date_end=end,
            per_ticker_status=per_ticker_status,
            sources=["[SOURCE_PLACEHOLDER | LOCATION-TODO | yfinance usage]"],
            notes="PROVISIONAL: connector usage pending citations",
            best_effort=True,
        )
        return {
            "fetch_run_id": run_id,
            "provider": "yfinance",
            "provenance_path": str(provenance_path),
            "cache_dir": str(cache_dir),
            "import_files": import_files,
            "per_ticker_status": per_ticker_status,
        }

    for symbol in symbols:
        try:
            df = yf.download(symbol, start=start, end=end, auto_adjust=False)
            if df.empty:
                per_ticker_status[symbol] = {"status": "no_data", "message": "empty"}
                continue

            df = df.reset_index()
            raw_path = cache_dir / f"{symbol}.csv"
            df.to_csv(raw_path, index=False)

            df.columns = [str(c).strip().lower() for c in df.columns]
            if "adj close" in df.columns:
                df = df.rename(columns={"adj close": "adj_close"})
            if "date" not in df.columns and "datetime" in df.columns:
                df = df.rename(columns={"datetime": "date"})
            if "symbol" not in df.columns:
                df["symbol"] = symbol

            import_path = import_dir / f"yfinance_{run_id}_{symbol}.csv"
            df.to_csv(import_path, index=False)
            import_files.append(str(import_path))

            per_ticker_status[symbol] = {"status": "ok", "rows": str(len(df))}
        except Exception as exc:
            per_ticker_status[symbol] = {"status": "failed", "message": str(exc)}

    provenance_path = write_fetch_provenance(
        run_id=run_id,
        provider="yfinance",
        symbols=symbols,
        date_start=start,
        date_end=end,
        per_ticker_status=per_ticker_status,
        sources=["[SOURCE_PLACEHOLDER | LOCATION-TODO | yfinance usage]"],
        notes="PROVISIONAL: connector usage pending citations",
        best_effort=True,
    )

    return {
        "fetch_run_id": run_id,
        "provider": "yfinance",
        "provenance_path": str(provenance_path),
        "cache_dir": str(cache_dir),
        "import_files": import_files,
        "per_ticker_status": per_ticker_status,
    }


def update_latest(*, symbols: Optional[List[str]] = None) -> Dict:
    return fetch_history(symbols=symbols, start=None, end=None)
