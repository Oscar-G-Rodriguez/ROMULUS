# Architecture (Draft)

ROMULUS is split into two systems:
- Research Truth System (Lab) for data ingestion, feature engineering, training, tournaments, and backtests.
- Trading Truth System (Execution/App) for users, portfolios, orders, trades, and audit trails.

This separation reduces leakage and preserves decision auditability. [SOURCE_PLACEHOLDER | LOCATION-TODO | architecture boundary]

## Components
- FastAPI backend (local auth, portfolios, trades, champions, tournaments, settings)
- SQLite persistence (local-only)
- Import and download scripts that normalize data to the canonical contract
- Minimal frontend that surfaces traceability fields

## Auditability
Every decision and trade references a run_id and champion_id, and includes provenance sources. [SOURCE_PLACEHOLDER | LOCATION-TODO | auditability requirement]
