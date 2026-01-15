# ROMULUS

ROMULUS is a full-stack trading research + execution app with strict boundaries between the Research Truth System (Lab) and the Trading Truth System (Execution/App). It focuses on traceability, risk controls, and auditable decisions.

Disclaimer: This software is for research and educational use only. It is not financial advice. Use at your own risk.

## Repo layout (Phase 0)
- backend/ - FastAPI service (auth, portfolio, trades, champions, tournaments, settings)
- frontend/ - Minimal UI scaffolding
- docs/ - architecture, policies, ADRs, audit trail, constitution
- scripts/ - data import + download scripts
- artifacts/ - generated outputs (gitignored)
- sources/ - ebooks/papers (gitignored)
- data/ - user-provided market data + caches (gitignored)

## Quick start (local)
1) Create a virtual environment and install dependencies (FastAPI, uvicorn, pandas, pandas-datareader, alpaca-py, yfinance).
2) Place source materials in `sources/` and register them in `sources/index.md`.
3) Place market data CSV/Parquet in `data/import/` and optionally `data/import/universe.csv`.
4) Run:
   - `python scripts/import_user_market_data.py`
5) Start the backend:
   - `uvicorn backend.app.main:app --reload`
6) Open `frontend/index.html` in a browser.

## Notes
- Default mode is paper/shadow trading. Live trading is disabled unless explicitly enabled.
- All decision logic is provisional until sources are provided and citations are verified.
- The system enforces traceability via provenance records and citation checks.
