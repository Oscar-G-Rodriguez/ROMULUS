# Data Policy (Draft)

Status: PROVISIONAL until sources are provided.

## Resolution
- Daily OHLCV is the default research feed.
- Weekly resampling is allowed as a tournament configuration.
- Non-time bars are only allowed in a separate league with explicit justification.

## Universe (Manual Only)
- Universe is defined solely by `data/import/universe.csv` with a `symbol` column. [SOURCE_PLACEHOLDER | LOCATION-TODO | universe policy]
- If the universe file is missing, ROMULUS creates a small starter list and prints a warning (PROVISIONAL). [SOURCE_PLACEHOLDER | LOCATION-TODO | universe policy]

## Fetch-and-Ingest Workflow
- Use the Data Manager to fetch historical data for the universe, cache raw downloads, and ingest into canonical tables. [SOURCE_PLACEHOLDER | LOCATION-TODO | data manager workflow]
- Each fetch run writes a provenance artifact with per-ticker status and SOURCES. [SOURCE_PLACEHOLDER | LOCATION-TODO | provenance requirements]
- Each ingest run links to one or more fetch_run_id values and stores universe hash/size. [SOURCE_PLACEHOLDER | LOCATION-TODO | ingestion provenance requirements]

## Adjustments
- Adjustment policy (splits/dividends) must be explicit and recorded in provenance.
- Default adjustment behavior is PROVISIONAL until a cited policy exists.

## Cutoffs and Lookahead
- Weekly decisions are made after Friday close and executed next open.
- Training and evaluation must enforce as-of cutoffs.

## Limitations
- Survivorship bias and point-in-time membership limits must be documented and surfaced in UI.

All statements require citations. [SOURCE_PLACEHOLDER | LOCATION-TODO | data policy guidance]
