"""
SOURCES:
- [SOURCE_PLACEHOLDER | LOCATION-TODO | data contract guidance]
DECISIONS:
- Use local SQLite for ingestion provenance and canonical tables -> simple local default -> UNSUPPORTED: database choice
- Require explicit provenance fields for every ingest run -> auditability -> UNSUPPORTED: provenance schema
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import pandas as pd


CANONICAL_REQUIRED_COLUMNS = [
    "symbol",
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
]

COLUMN_ALIASES = {
    "ticker": "symbol",
    "symbol": "symbol",
    "date": "date",
    "datetime": "date",
    "time": "date",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
    "adjclose": "adj_close",
    "adj close": "adj_close",
    "adj_close": "adj_close",
}


@dataclass
class QualityStats:
    total_rows: int
    duplicates_dropped: int
    missing_required: List[str]
    invalid_rows: int
    date_min: Optional[str]
    date_max: Optional[str]
    symbols: int


def ensure_runtime_dirs() -> None:
    Path("data").mkdir(parents=True, exist_ok=True)
    Path("artifacts/ingestion_reports").mkdir(parents=True, exist_ok=True)


def get_db_path() -> Path:
    override = os.getenv("ROMULUS_DB_PATH")
    if override:
        return Path(override)
    return Path("data/romulus.db")


def connect_db() -> sqlite3.Connection:
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(db_path))


def init_ingestion_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS prices_daily (
            symbol TEXT NOT NULL,
            date TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            adj_close REAL,
            source TEXT NOT NULL,
            ingest_run_id TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_prices_daily_unique
        ON prices_daily (symbol, date, source)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS corporate_actions (
            symbol TEXT NOT NULL,
            date TEXT NOT NULL,
            action_type TEXT NOT NULL,
            value REAL NOT NULL,
            source TEXT NOT NULL,
            ingest_run_id TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS macro (
            series TEXT NOT NULL,
            date TEXT NOT NULL,
            value REAL NOT NULL,
            source TEXT NOT NULL,
            ingest_run_id TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ingestion_provenance (
            run_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            vendor TEXT NOT NULL,
            dataset_id TEXT NOT NULL,
            universe TEXT NOT NULL,
            universe_hash TEXT NOT NULL,
            universe_size INTEGER NOT NULL,
            fetch_run_ids TEXT,
            adjustment_policy TEXT NOT NULL,
            cutoff_policy TEXT NOT NULL,
            quality_gates TEXT NOT NULL,
            sources TEXT NOT NULL,
            notes TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ingestion_quality_report (
            run_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            report_json TEXT NOT NULL
        )
        """
    )
    ensure_column(conn, "ingestion_provenance", "universe_hash", "TEXT")
    ensure_column(conn, "ingestion_provenance", "universe_size", "INTEGER")
    ensure_column(conn, "ingestion_provenance", "fetch_run_ids", "TEXT")
    conn.commit()


def ensure_column(conn: sqlite3.Connection, table: str, column: str, col_type: str) -> None:
    cur = conn.execute(f"PRAGMA table_info({table})")
    cols = {row[1] for row in cur.fetchall()}
    if column in cols:
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")


def normalize_prices_df(
    df: pd.DataFrame,
    source: str,
    run_id: str,
) -> Tuple[pd.DataFrame, QualityStats]:
    if df.empty:
        raise ValueError("Empty dataframe")

    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    df = df.rename(columns={c: COLUMN_ALIASES.get(c, c) for c in df.columns})

    missing = [c for c in CANONICAL_REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    invalid_rows = int(df["date"].isna().sum())
    df = df.dropna(subset=["date", "symbol"])

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    invalid_rows += int(df[CANONICAL_REQUIRED_COLUMNS].isna().any(axis=1).sum())

    df = df.dropna(subset=CANONICAL_REQUIRED_COLUMNS)
    df = df[df["open"] >= 0]
    df = df[df["high"] >= 0]
    df = df[df["low"] >= 0]
    df = df[df["close"] >= 0]
    df = df[df["volume"] >= 0]

    duplicates = int(df.duplicated(subset=["symbol", "date"]).sum())
    df = df.drop_duplicates(subset=["symbol", "date"])  # keep first

    df["source"] = source
    df["ingest_run_id"] = run_id

    date_min = df["date"].min() if not df.empty else None
    date_max = df["date"].max() if not df.empty else None

    stats = QualityStats(
        total_rows=int(len(df)),
        duplicates_dropped=duplicates,
        missing_required=missing,
        invalid_rows=invalid_rows,
        date_min=date_min,
        date_max=date_max,
        symbols=int(df["symbol"].nunique()),
    )

    return df, stats


def insert_prices(conn: sqlite3.Connection, df: pd.DataFrame) -> None:
    df.to_sql("prices_daily", conn, if_exists="append", index=False)


def write_provenance(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    vendor: str,
    dataset_id: str,
    universe: str,
    universe_hash: str,
    universe_size: int,
    fetch_run_ids: Optional[List[str]],
    adjustment_policy: str,
    cutoff_policy: str,
    quality_gates: str,
    sources: List[str],
    notes: Optional[str] = None,
) -> None:
    conn.execute(
        """
        INSERT INTO ingestion_provenance (
            run_id, created_at, vendor, dataset_id, universe, universe_hash,
            universe_size, fetch_run_ids, adjustment_policy, cutoff_policy,
            quality_gates, sources, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            datetime.utcnow().isoformat() + "Z",
            vendor,
            dataset_id,
            universe,
            universe_hash,
            universe_size,
            json.dumps(fetch_run_ids or []),
            adjustment_policy,
            cutoff_policy,
            quality_gates,
            json.dumps(sources),
            notes,
        ),
    )
    conn.commit()


def write_quality_report(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    report: dict,
) -> None:
    conn.execute(
        """
        INSERT INTO ingestion_quality_report (run_id, created_at, report_json)
        VALUES (?, ?, ?)
        """,
        (
            run_id,
            datetime.utcnow().isoformat() + "Z",
            json.dumps(report, indent=2),
        ),
    )
    conn.commit()


def new_run_id() -> str:
    return str(uuid.uuid4())
