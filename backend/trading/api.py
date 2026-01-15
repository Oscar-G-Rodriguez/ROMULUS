"""
SOURCES:
- [SOURCE_PLACEHOLDER | LOCATION-TODO | trading API scaffolding guidance]
DECISIONS:
- Provide minimal auth and portfolio APIs -> Phase 0 scaffolding -> UNSUPPORTED: API scope
- Store API keys in SQLite plaintext (PROVISIONAL) -> simple local dev -> UNSUPPORTED: secure storage
- Import data manager scripts via sys.path injection -> reuse CLI logic -> UNSUPPORTED: integration approach
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sys
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, Header, HTTPException, status

from backend.trading.db import get_db, now_iso
from backend.trading.schemas import (
    ApiKeyRequest,
    ChampionRecord,
    FetchHistoryRequest,
    FetchHistoryResponse,
    IngestRequest,
    IngestResponse,
    LastIngestionResponse,
    LoginRequest,
    PortfolioResponse,
    RegisterRequest,
    TickerActionRequest,
    TokenResponse,
    TournamentRunRecord,
    TradeRecord,
)

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.append(str(SCRIPTS_DIR))

from import_user_market_data import run_import  # noqa: E402
from providers import provider_alpaca, provider_stooq, provider_yfinance  # noqa: E402
from universe_utils import add_ticker, ensure_universe_file, read_universe, remove_ticker  # noqa: E402

router = APIRouter()


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def get_current_user(
    authorization: str | None = Header(default=None),
    db=Depends(get_db),
):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    token = authorization.split(" ", 1)[1]
    row = db.execute("SELECT user_id FROM auth_tokens WHERE token = ?", (token,)).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = db.execute("SELECT id, email FROM users WHERE id = ?", (row["user_id"],)).fetchone()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user")
    return user


def safe_sources(value: str | None) -> str:
    return value if value else "UNSUPPORTED"


def table_exists(db, name: str) -> bool:
    row = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


@router.post("/auth/register", response_model=TokenResponse)
def register(request: RegisterRequest, db=Depends(get_db)) -> TokenResponse:
    existing = db.execute("SELECT id FROM users WHERE email = ?", (request.email,)).fetchone()
    if existing:
        raise HTTPException(status_code=400, detail="User already exists")

    password_hash = hash_password(request.password)
    db.execute(
        "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
        (request.email, password_hash, now_iso()),
    )
    user_id = db.execute("SELECT id FROM users WHERE email = ?", (request.email,)).fetchone()["id"]
    db.execute(
        "INSERT INTO portfolios (user_id, cash, created_at) VALUES (?, ?, ?)",
        (user_id, 0.0, now_iso()),
    )
    token = secrets.token_hex(16)
    db.execute(
        "INSERT INTO auth_tokens (user_id, token, created_at) VALUES (?, ?, ?)",
        (user_id, token, now_iso()),
    )
    db.commit()
    return TokenResponse(token=token)


@router.post("/auth/login", response_model=TokenResponse)
def login(request: LoginRequest, db=Depends(get_db)) -> TokenResponse:
    row = db.execute(
        "SELECT id, password_hash FROM users WHERE email = ?", (request.email,)
    ).fetchone()
    if row is None or row["password_hash"] != hash_password(request.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = secrets.token_hex(16)
    db.execute(
        "INSERT INTO auth_tokens (user_id, token, created_at) VALUES (?, ?, ?)",
        (row["id"], token, now_iso()),
    )
    db.commit()
    return TokenResponse(token=token)


@router.get("/portfolio", response_model=PortfolioResponse)
def get_portfolio(user=Depends(get_current_user), db=Depends(get_db)) -> PortfolioResponse:
    portfolio = db.execute(
        "SELECT cash FROM portfolios WHERE user_id = ?", (user["id"],)
    ).fetchone()
    cash = float(portfolio["cash"]) if portfolio else 0.0
    positions = db.execute(
        "SELECT symbol, quantity, avg_price FROM positions WHERE user_id = ?",
        (user["id"],),
    ).fetchall()
    return PortfolioResponse(
        cash=cash,
        positions=[
            {
                "symbol": row["symbol"],
                "quantity": float(row["quantity"]),
                "avg_price": float(row["avg_price"]),
            }
            for row in positions
        ],
    )


@router.get("/trades", response_model=List[TradeRecord])
def trade_history(user=Depends(get_current_user), db=Depends(get_db)) -> List[TradeRecord]:
    rows = db.execute(
        """
        SELECT id, symbol, side, quantity, price, traded_at, champion_id, run_id, decision_id
        FROM trades WHERE user_id = ? ORDER BY traded_at DESC
        """,
        (user["id"],),
    ).fetchall()
    return [
        TradeRecord(
            id=row["id"],
            symbol=row["symbol"],
            side=row["side"],
            quantity=float(row["quantity"]),
            price=float(row["price"]),
            traded_at=row["traded_at"],
            champion_id=row["champion_id"],
            run_id=row["run_id"],
            decision_id=row["decision_id"],
        )
        for row in rows
    ]


@router.get("/champions", response_model=List[ChampionRecord])
def list_champions(user=Depends(get_current_user), db=Depends(get_db)) -> List[ChampionRecord]:
    rows = db.execute(
        "SELECT id, name, status, created_at, sources FROM champions ORDER BY created_at DESC"
    ).fetchall()
    return [
        ChampionRecord(
            id=row["id"],
            name=row["name"],
            status=row["status"],
            created_at=row["created_at"],
            sources=safe_sources(row["sources"]),
        )
        for row in rows
    ]


@router.get("/tournaments", response_model=List[TournamentRunRecord])
def list_tournaments(user=Depends(get_current_user), db=Depends(get_db)) -> List[TournamentRunRecord]:
    rows = db.execute(
        "SELECT run_id, name, status, created_at, sources FROM tournament_runs ORDER BY created_at DESC"
    ).fetchall()
    return [
        TournamentRunRecord(
            run_id=row["run_id"],
            name=row["name"],
            status=row["status"],
            created_at=row["created_at"],
            sources=safe_sources(row["sources"]),
        )
        for row in rows
    ]


@router.get("/tournaments/{run_id}", response_model=TournamentRunRecord)
def tournament_detail(run_id: str, user=Depends(get_current_user), db=Depends(get_db)) -> TournamentRunRecord:
    row = db.execute(
        "SELECT run_id, name, status, created_at, sources FROM tournament_runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return TournamentRunRecord(
        run_id=row["run_id"],
        name=row["name"],
        status=row["status"],
        created_at=row["created_at"],
        sources=safe_sources(row["sources"]),
    )


@router.post("/settings/api-keys")
def set_api_keys(
    request: ApiKeyRequest, user=Depends(get_current_user), db=Depends(get_db)
) -> dict:
    db.execute(
        """
        INSERT INTO api_keys (user_id, provider, api_key, api_secret, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user["id"], request.provider, request.api_key, request.api_secret, now_iso()),
    )
    db.commit()
    return {
        "status": "stored",
        "warning": "PROVISIONAL: API keys stored in plaintext local SQLite",
    }


@router.get("/data/tickers")
def get_tickers(user=Depends(get_current_user)) -> dict:
    ensure_universe_file()
    symbols = read_universe(Path("data/import/universe.csv"))
    return {"symbols": symbols}


@router.post("/data/tickers")
def update_tickers(request: TickerActionRequest, user=Depends(get_current_user)) -> dict:
    action = request.action.lower().strip()
    if action == "add":
        symbols = add_ticker(request.symbol)
    elif action == "remove":
        symbols = remove_ticker(request.symbol)
    else:
        raise HTTPException(status_code=400, detail="action must be add or remove")
    return {"symbols": symbols}


@router.post("/data/fetch-history", response_model=FetchHistoryResponse)
def fetch_history(request: FetchHistoryRequest, user=Depends(get_current_user)) -> FetchHistoryResponse:
    providers = {
        "stooq": provider_stooq,
        "alpaca": provider_alpaca,
        "yfinance": provider_yfinance,
    }
    provider = providers.get(request.provider)
    if provider is None:
        raise HTTPException(status_code=400, detail="Unknown provider")

    mode = (request.mode or "full").lower()
    if mode == "latest" and hasattr(provider, "update_latest"):
        result = provider.update_latest()
    else:
        result = provider.fetch_history(start=request.start, end=request.end)

    return FetchHistoryResponse(**result)


@router.post("/data/ingest", response_model=IngestResponse)
def ingest_data(request: IngestRequest, user=Depends(get_current_user)) -> IngestResponse:
    result = run_import(
        vendor=request.vendor,
        dataset_id=request.dataset_id,
        fetch_run_ids=request.fetch_run_ids,
    )
    if result.get("code") != 0:
        raise HTTPException(status_code=400, detail=result.get("error", "Ingest failed"))
    return IngestResponse(
        run_id=result["run_id"],
        report_path=result["report_path"],
        errors=result.get("errors", []),
    )


@router.get("/data/last-ingestion", response_model=LastIngestionResponse)
def last_ingestion(user=Depends(get_current_user), db=Depends(get_db)) -> LastIngestionResponse:
    if not table_exists(db, "ingestion_provenance"):
        raise HTTPException(status_code=404, detail="No ingestion runs found")
    row = db.execute(
        """
        SELECT run_id, created_at, vendor, dataset_id, universe_hash, universe_size,
               fetch_run_ids, sources
        FROM ingestion_provenance
        ORDER BY created_at DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="No ingestion runs found")

    fetch_run_ids = []
    if row["fetch_run_ids"]:
        try:
            fetch_run_ids = json.loads(row["fetch_run_ids"])
        except json.JSONDecodeError:
            fetch_run_ids = []

    report_path = str(Path("artifacts/ingestion_reports") / f"{row['run_id']}.json")
    provenance_ref = f"db:ingestion_provenance:{row['run_id']}"

    universe_hash = row["universe_hash"] or "UNSUPPORTED"
    universe_size = int(row["universe_size"] or 0)

    return LastIngestionResponse(
        run_id=row["run_id"],
        created_at=row["created_at"],
        vendor=row["vendor"],
        dataset_id=row["dataset_id"],
        universe_hash=universe_hash,
        universe_size=universe_size,
        fetch_run_ids=fetch_run_ids,
        sources=safe_sources(row["sources"]),
        report_path=report_path,
        provenance_ref=provenance_ref,
    )
