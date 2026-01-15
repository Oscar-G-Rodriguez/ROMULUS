"""
SOURCES:
- [SOURCE_PLACEHOLDER | LOCATION-TODO | citation enforcement policy]
DECISIONS:
- Enforce SOURCES/DECISIONS blocks in meaningful modules -> traceability requirement -> UNSUPPORTED: enforcement rules
- Fail if ADRs lack citations -> documentation completeness -> UNSUPPORTED: ADR citation policy
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Set

CITATION_PATTERN = re.compile(r"\[[^\]]+\|[^\]]+\|[^\]]+\]")


def find_meaningful_files() -> Set[Path]:
    files: Set[Path] = set()

    backend = Path("backend")
    if backend.exists():
        for path in backend.rglob("*.py"):
            lower = str(path).lower()
            if "research" in lower or "trading" in lower or "data" in lower:
                files.add(path)

    scripts = Path("scripts")
    if scripts.exists():
        for path in scripts.glob("download*.py"):
            files.add(path)
        for path in scripts.glob("data_manager.py"):
            files.add(path)
        for path in scripts.glob("universe_utils.py"):
            files.add(path)
        providers = scripts / "providers"
        if providers.exists():
            for path in providers.glob("*.py"):
                files.add(path)

    for path in Path(".").rglob("*.py"):
        lower = str(path).lower()
        if any(k in lower for k in ["/risk/", "\\risk\\", "cost", "tournament", "validation"]):
            files.add(path)

    return files


def has_sources_block(path: Path) -> bool:
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return False

    head = "\n".join(lines[:60])
    return "SOURCES:" in head and "DECISIONS:" in head


def check_adrs() -> List[str]:
    issues: List[str] = []
    adr_dir = Path("docs/adr")
    if not adr_dir.exists():
        return issues

    for path in adr_dir.glob("*.md"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if not CITATION_PATTERN.search(text):
            issues.append(f"ADR missing citation: {path}")
    return issues


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    )
    return cur.fetchone() is not None


def table_columns(conn: sqlite3.Connection, name: str) -> List[str]:
    cur = conn.execute(f"PRAGMA table_info({name})")
    return [row[1] for row in cur.fetchall()]


def check_db() -> List[str]:
    issues: List[str] = []
    db_path = Path("data/romulus.db")
    if not db_path.exists():
        return issues

    conn = sqlite3.connect(str(db_path))

    if table_exists(conn, "ingestion_provenance"):
        cur = conn.execute("SELECT run_id, sources FROM ingestion_provenance")
        for run_id, sources in cur.fetchall():
            if sources is None:
                issues.append(f"Ingestion provenance missing SOURCES: run_id={run_id}")
                continue
            try:
                parsed = json.loads(sources)
            except json.JSONDecodeError:
                issues.append(f"Ingestion provenance SOURCES not JSON: run_id={run_id}")
                continue
            if not parsed:
                issues.append(f"Ingestion provenance SOURCES empty: run_id={run_id}")

    if table_exists(conn, "tournament_runs"):
        cols = table_columns(conn, "tournament_runs")
        if "sources" not in cols:
            issues.append("tournament_runs table missing sources column")
        else:
            cur = conn.execute("SELECT run_id, sources FROM tournament_runs")
            for run_id, sources in cur.fetchall():
                if sources is None:
                    issues.append(f"Tournament run missing SOURCES: run_id={run_id}")

    for table in ["trade_ledger", "decision_ledger"]:
        if table_exists(conn, table):
            cols = table_columns(conn, table)
            required = {"champion_id", "run_id"}
            if not required.issubset(set(cols)):
                issues.append(f"{table} missing champion_id/run_id columns")
                continue
            cur = conn.execute(
                f"SELECT id, champion_id, run_id FROM {table}"
            )
            for row_id, champion_id, run_id in cur.fetchall():
                if champion_id is None or run_id is None:
                    issues.append(f"{table} row missing champion/run linkage: id={row_id}")

    conn.close()
    return issues


def main() -> int:
    issues: List[str] = []

    for path in sorted(find_meaningful_files()):
        if not has_sources_block(path):
            issues.append(f"Missing SOURCES/DECISIONS block: {path}")

    issues.extend(check_adrs())
    issues.extend(check_db())

    if issues:
        print("Citation enforcement failed:")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("Citation enforcement passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
