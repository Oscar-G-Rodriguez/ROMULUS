"""
SOURCES:
- [SOURCE_PLACEHOLDER | LOCATION-TODO | Alpaca market data usage]
- [SOURCE_PLACEHOLDER | LOCATION-TODO | fetch provenance requirements]
DECISIONS:
- Use alpaca-py for recent bars when keys are provided -> supported provider -> UNSUPPORTED: connector choice
- Default update_latest lookback is 30 days -> operational default -> UNSUPPORTED: update window
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from providers.provider_utils import ensure_cache_dir, write_fetch_provenance
from universe_utils import ensure_universe_file, read_universe


def _new_run_id() -> str:
    return str(uuid.uuid4())


def _missing_keys_status(symbols: List[str], message: str) -> Dict:
    run_id = _new_run_id()
    per_ticker_status = {symbol: {"status": "failed", "message": message} for symbol in symbols}
    provenance_path = write_fetch_provenance(
        run_id=run_id,
        provider="alpaca",
        symbols=symbols,
        date_start=None,
        date_end=None,
        per_ticker_status=per_ticker_status,
        sources=["[SOURCE_PLACEHOLDER | LOCATION-TODO | Alpaca market data usage]"],
        notes="PROVISIONAL: missing keys",
    )
    return {
        "fetch_run_id": run_id,
        "provider": "alpaca",
        "provenance_path": str(provenance_path),
        "cache_dir": "",
        "import_files": [],
        "per_ticker_status": per_ticker_status,
        "warning": "Missing APCA_API_KEY_ID/APCA_API_SECRET_KEY",
    }


def fetch_history(
    *, symbols: Optional[List[str]] = None, start: Optional[str] = None, end: Optional[str] = None
) -> Dict:
    run_id = _new_run_id()
    if symbols is None:
        ensure_universe_file()
        symbols = read_universe(Path("data/import/universe.csv"))

    api_key = os.getenv("APCA_API_KEY_ID")
    api_secret = os.getenv("APCA_API_SECRET_KEY")
    if not api_key or not api_secret:
        return _missing_keys_status(symbols, "Missing APCA_API_KEY_ID/APCA_API_SECRET_KEY")

    cache_dir = ensure_cache_dir("alpaca", run_id)
    import_dir = Path("data/import")
    import_dir.mkdir(parents=True, exist_ok=True)

    per_ticker_status: Dict[str, Dict[str, str]] = {}
    import_files: List[str] = []

    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
    except Exception as exc:
        for symbol in symbols:
            per_ticker_status[symbol] = {
                "status": "failed",
                "message": f"missing alpaca-py: {exc}",
            }
        provenance_path = write_fetch_provenance(
            run_id=run_id,
            provider="alpaca",
            symbols=symbols,
            date_start=start,
            date_end=end,
            per_ticker_status=per_ticker_status,
            sources=["[SOURCE_PLACEHOLDER | LOCATION-TODO | Alpaca market data usage]"],
            notes="PROVISIONAL: connector usage pending citations",
        )
        return {
            "fetch_run_id": run_id,
            "provider": "alpaca",
            "provenance_path": str(provenance_path),
            "cache_dir": str(cache_dir),
            "import_files": import_files,
            "per_ticker_status": per_ticker_status,
        }

    client = StockHistoricalDataClient(api_key, api_secret)
    request = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
    )

    bars = client.get_stock_bars(request)
    df = bars.df

    if df.empty:
        for symbol in symbols:
            per_ticker_status[symbol] = {"status": "no_data", "message": "empty"}
    else:
        df = df.reset_index()
        if "timestamp" in df.columns:
            df = df.rename(columns={"timestamp": "date"})
        if "symbol" not in df.columns and "symbol" in df.index.names:
            df = df.reset_index()

        for symbol in symbols:
            df_symbol = df[df["symbol"] == symbol]
            if df_symbol.empty:
                per_ticker_status[symbol] = {"status": "no_data", "message": "empty"}
                continue

            raw_path = cache_dir / f"{symbol}.csv"
            df_symbol.to_csv(raw_path, index=False)

            import_path = import_dir / f"alpaca_{run_id}_{symbol}.csv"
            df_symbol.to_csv(import_path, index=False)
            import_files.append(str(import_path))

            per_ticker_status[symbol] = {"status": "ok", "rows": str(len(df_symbol))}

    provenance_path = write_fetch_provenance(
        run_id=run_id,
        provider="alpaca",
        symbols=symbols,
        date_start=start,
        date_end=end,
        per_ticker_status=per_ticker_status,
        sources=["[SOURCE_PLACEHOLDER | LOCATION-TODO | Alpaca market data usage]"],
        notes="PROVISIONAL: connector usage pending citations",
    )

    return {
        "fetch_run_id": run_id,
        "provider": "alpaca",
        "provenance_path": str(provenance_path),
        "cache_dir": str(cache_dir),
        "import_files": import_files,
        "per_ticker_status": per_ticker_status,
    }


def update_latest(
    *, symbols: Optional[List[str]] = None, lookback_days: int = 30
) -> Dict:
    start = (datetime.utcnow() - timedelta(days=lookback_days)).date().isoformat()
    end = datetime.utcnow().date().isoformat()
    return fetch_history(symbols=symbols, start=start, end=end)
