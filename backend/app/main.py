"""
SOURCES:
- [SOURCE_PLACEHOLDER | LOCATION-TODO | backend scaffolding guidance]
DECISIONS:
- Use FastAPI for local API service -> simple local dev -> UNSUPPORTED: framework choice
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.trading.api import router as trading_router

app = FastAPI(title="ROMULUS", version="0.0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(trading_router, prefix="/api")
