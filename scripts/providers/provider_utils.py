"""
SOURCES:
- [SOURCE_PLACEHOLDER | LOCATION-TODO | fetch provenance requirements]
DECISIONS:
- Store fetch provenance as JSON artifacts -> auditability -> UNSUPPORTED: provenance format
- Compute universe hash from sorted symbols -> stable traceability -> UNSUPPORTED: hash policy
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional


def compute_universe_hash(symbols: Iterable[str]) -> str:
    cleaned = sorted({s.strip().upper() for s in symbols if s and str(s).strip()})
    joined = ",".join(cleaned)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def ensure_cache_dir(provider: str, run_id: str) -> Path:
    base = Path("data/cache") / provider / run_id
    base.mkdir(parents=True, exist_ok=True)
    return base


def ensure_fetch_dir(provider: str) -> Path:
    base = Path("artifacts/fetch_runs") / provider
    base.mkdir(parents=True, exist_ok=True)
    return base


def write_fetch_provenance(
    *,
    run_id: str,
    provider: str,
    symbols: List[str],
    date_start: Optional[str],
    date_end: Optional[str],
    per_ticker_status: Dict[str, Dict[str, str]],
    sources: List[str],
    notes: str,
    best_effort: bool = False,
) -> Path:
    universe_hash = compute_universe_hash(symbols)
    universe_symbols = sorted(
        {str(s).strip().upper() for s in symbols if s and str(s).strip()}
    )
    record = {
        "fetch_run_id": run_id,
        "provider": provider,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "universe_hash": universe_hash,
        "universe_size": len(universe_symbols),
        "universe_symbols": universe_symbols,
        "date_start": date_start,
        "date_end": date_end,
        "per_ticker_status": per_ticker_status,
        "sources": sources,
        "notes": notes,
        "best_effort": best_effort,
    }

    fetch_dir = ensure_fetch_dir(provider)
    path = fetch_dir / f"{run_id}.json"
    path.write_text(json.dumps(record, indent=2), encoding="ascii")

    latest_path = Path("artifacts/fetch_runs/last_fetch.json")
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(
        json.dumps(
            {
                "fetch_run_id": run_id,
                "provider": provider,
                "path": str(path),
                "created_at": record["created_at"],
            },
            indent=2,
        ),
        encoding="ascii",
    )

    return path
