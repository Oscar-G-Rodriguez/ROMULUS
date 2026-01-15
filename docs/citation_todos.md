# Citation TODOs

Add verified citations (SOURCE_ID + location) once sources are available.

- docs/ROMULUS_CONSTITUTION.md: governance, separation, traceability, risk controls, data resolution policy
- docs/architecture.md: system boundary and auditability claims
- docs/audit_trail.md: ledger requirements and traceability expectations
- docs/risk_policy.md: risk limits, kill-switch behavior, trading safety defaults
- docs/data_policy.md: adjustments, cutoffs, survivorship bias, point-in-time limits
- docs/adr/ADR-001.md: weekly cadence and decision/execution split
- docs/adr/ADR-002.md: daily vs weekly vs non-time bars policy
- docs/adr/ADR-003.md: validation, leakage control, purging/embargo policy
- docs/adr/ADR-004.md: tournament governance and promotion gates
- docs/adr/ADR-005.md: cost/slippage model and sensitivity gates
- docs/adr/ADR-006.md: risk policy and kill-switch behavior
- backend/app/main.py: framework selection and scaffolding
- backend/trading/__init__.py: package boundary rationale
- backend/trading/db.py: storage schema and ledger linkage
- backend/trading/api.py: API scope and key handling
- backend/trading/schemas.py: request/response schema choices
- scripts/import_user_market_data.py: schema/validation and provenance rules
- scripts/ingestion_utils.py: data contract and provenance helpers
- scripts/universe_utils.py: manual universe policy and defaults
- scripts/data_manager.py: data manager workflow
- scripts/providers/provider_utils.py: fetch provenance format
- scripts/providers/__init__.py: provider package organization
- scripts/providers/provider_stooq.py: connector usage and caching policy
- scripts/providers/provider_alpaca.py: connector usage and update-latest policy
- scripts/providers/provider_yfinance.py: fallback policy and best-effort labeling
- scripts/download_stooq_daily.py: data connector usage details
- scripts/download_alpaca_bars.py: data connector usage details
- scripts/download_yfinance_daily.py: fallback data connector usage details
- scripts/check_citations.py: enforcement policy
