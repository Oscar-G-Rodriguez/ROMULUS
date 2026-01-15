# Data Contract v0 (Draft)

Status: PROVISIONAL until sources are provided.

This document defines the canonical tables ROMULUS expects for market data ingestion. It applies to the import script and all download scripts.

## Canonical tables

### prices_daily
Required. One row per symbol per trading day.

Columns:
- symbol (TEXT, required)
- date (TEXT, ISO-8601 YYYY-MM-DD, required)
- open (REAL, required)
- high (REAL, required)
- low (REAL, required)
- close (REAL, required)
- volume (REAL, required)
- adj_close (REAL, optional)
- source (TEXT, required) - vendor/source name
- ingest_run_id (TEXT, required) - provenance linkage

### corporate_actions (optional)
- symbol (TEXT, required)
- date (TEXT, required)
- action_type (TEXT, required) - split, dividend, etc
- value (REAL, required)
- source (TEXT, required)
- ingest_run_id (TEXT, required)

### macro (optional)
- series (TEXT, required)
- date (TEXT, required)
- value (REAL, required)
- source (TEXT, required)
- ingest_run_id (TEXT, required)

### ingestion_provenance
Required. One row per ingest run.

Columns:
- run_id (TEXT, required)
- created_at (TEXT, required)
- vendor (TEXT, required)
- dataset_id (TEXT, required)
- universe (TEXT, required) - string or JSON
- universe_hash (TEXT, required)
- universe_size (INTEGER, required)
- fetch_run_ids (TEXT, optional) - JSON array of fetch_run_id values
- adjustment_policy (TEXT, required)
- cutoff_policy (TEXT, required)
- quality_gates (TEXT, required)
- sources (TEXT, required) - JSON array of citations
- notes (TEXT, optional)

### ingestion_quality_report
Required. One row per ingest run.

Columns:
- run_id (TEXT, required)
- created_at (TEXT, required)
- report_json (TEXT, required)

## Normalization rules (PROVISIONAL)
- All dates must be normalized to ISO-8601 YYYY-MM-DD.
- Prices must be numeric and non-negative.
- Duplicates (symbol, date) are rejected.
- The import script must record a provenance entry for every ingest run.

All rules require citations once sources are provided. [SOURCE_PLACEHOLDER | LOCATION-TODO | data contract guidance]
