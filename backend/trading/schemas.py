"""
SOURCES:
- [SOURCE_PLACEHOLDER | LOCATION-TODO | API schema guidance]
DECISIONS:
- Use minimal request/response schemas for Phase 0 -> scaffolding only -> UNSUPPORTED: schema design
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class RegisterRequest(BaseModel):
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    token: str


class PortfolioPosition(BaseModel):
    symbol: str
    quantity: float
    avg_price: float


class PortfolioResponse(BaseModel):
    cash: float
    positions: List[PortfolioPosition]


class TradeRecord(BaseModel):
    id: int
    symbol: str
    side: str
    quantity: float
    price: float
    traded_at: str
    champion_id: Optional[str]
    run_id: Optional[str]
    decision_id: Optional[str]


class ChampionRecord(BaseModel):
    id: str
    name: str
    status: str
    created_at: str
    sources: str


class TournamentRunRecord(BaseModel):
    run_id: str
    name: str
    status: str
    created_at: str
    sources: str


class ApiKeyRequest(BaseModel):
    provider: str
    api_key: str
    api_secret: str


class TickerActionRequest(BaseModel):
    action: str
    symbol: str


class FetchHistoryRequest(BaseModel):
    provider: str = "stooq"
    start: Optional[str] = None
    end: Optional[str] = None
    mode: Optional[str] = "full"


class FetchHistoryResponse(BaseModel):
    fetch_run_id: str
    provider: str
    provenance_path: str
    cache_dir: str
    import_files: List[str]
    per_ticker_status: dict


class IngestRequest(BaseModel):
    vendor: str = "user_import"
    dataset_id: str = "user_import"
    fetch_run_ids: List[str] = []


class IngestResponse(BaseModel):
    run_id: str
    report_path: str
    errors: List[str]


class LastIngestionResponse(BaseModel):
    run_id: str
    created_at: str
    vendor: str
    dataset_id: str
    universe_hash: str
    universe_size: int
    fetch_run_ids: List[str]
    sources: str
    report_path: str
    provenance_ref: str
