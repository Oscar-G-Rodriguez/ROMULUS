# ROMULUS Constitution (Draft)

Disclaimer: This document is provisional until sources are provided and citations are verified.

## Purpose
ROMULUS exists to support traceable, auditable trading research and execution workflows with strong separation between research artifacts and live trading state. [SOURCE_PLACEHOLDER | LOCATION-TODO | governance and system separation]

## Two Truth Systems
- Research Truth System (Lab): data, features, training, tournaments, backtests, artifacts.
- Trading Truth System (Execution/App): users, portfolios, orders, trades, audit trails.
This separation is mandatory to prevent leakage and to preserve auditability. [SOURCE_PLACEHOLDER | LOCATION-TODO | research vs execution separation]

## Traceability and Provenance
Every meaningful model decision must be linked to data provenance, sources, and a champion/tournament run identifier. [SOURCE_PLACEHOLDER | LOCATION-TODO | auditability requirement]

## Safety and Risk
Default operation is paper/shadow trading; live trading requires explicit enablement, risk limits, and a kill-switch. [SOURCE_PLACEHOLDER | LOCATION-TODO | risk controls]

## Data Policy
Daily OHLCV is the default research feed. Alternative bar types require explicit support and governance. [SOURCE_PLACEHOLDER | LOCATION-TODO | data resolution policy]

## Change Control
Major architectural decisions are documented as ADRs and include citations. [SOURCE_PLACEHOLDER | LOCATION-TODO | ADR practice]
