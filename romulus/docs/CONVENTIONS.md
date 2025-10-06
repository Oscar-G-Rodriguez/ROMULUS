# Romulus Data & Workflow Conventions

This document defines **data standards**, **file naming**, and **workflow rules** used across all Romulus modules.  
Every script must comply with these conventions to guarantee reproducibility and clean data merges.

---

## 1. General Principles

| Category | Convention |
|-----------|-------------|
| **Time Zone** | All timestamps are UTC (naive, no timezone offset). |
| **Calendar** | NYSE business days; weekends and market holidays excluded. |
| **Naming** | Columns use `snake_case`; tickers are upper-case. |
| **File Format** | Parquet for structured tables; CSV only for temporary exports. |
| **Date Key** | `date` column is the anchor for all joins. |
| **Units** | Prices in USD, returns in log units, costs in basis points (bps). |
| **Indexes** | DataFrames should not rely on pandas indexes for joins; always use explicit columns. |
| **Adjustments** | Use split/dividend-adjusted prices only if explicitly specified. Default = raw. |

---

## 2. Directory Layout

| Path | Purpose |
|------|----------|
| `data/raw/` | Direct downloads (e.g., yfinance, macro data). No modification. |
| `data/interim/` | Cleaned + aligned panels, ready for feature generation. |
| `data/features/` | Feature stores by anchor frequency and horizon. |
| `data/labels/` | Target variables aligned to feature stores. |
| `data/preds/` | Model outputs (predictions, scores, signals). |
| `data/portfolio/` | Portfolio state snapshots, weights, and returns. |
| `data/reports/` | Aggregated analytics, performance reports. |
| `logs/` | Runtime and pipeline logs. |
| `config/` | All YAML configuration files used across modules. |
| `src/` | Source code grouped by function (ingest, preprocess, featuregen, etc.). |

---

## 3. File Naming

| Type | Convention | Example |
|------|-------------|---------|
| Raw price data | `{TICKER}.parquet` | `AAPL.parquet` |
| Feature store | `{anchor}_{horizon}.parquet` | `daily_5d.parquet` |
| Label set | `{anchor}_{horizon}_labels.parquet` | `daily_5d_labels.parquet` |
| Predictions | `{model_name}_{anchor}_{horizon}.parquet` | `xgb_v1_daily_5d.parquet` |
| Portfolio | `{date}_portfolio.parquet` | `2025-10-06_portfolio.parquet` |

---

## 4. Column Standards

### 4.1 Raw Daily Prices
date | Open | High | Low | Close | Adj Close | Volume | Ticker

- `date`: trading day (UTC, midnight)
- `Volume`: shares traded
- `Ticker`: upper-case symbol
- `Adj Close`: included but not used unless adjusted returns are needed

### 4.2 Derived Columns (Interim)
| Column | Formula / Description |
|---------|-----------------------|
| `dollar_vol` | `Close * Volume` |
| `ret_1` | `log(Close / Close[t-1])` |
| `ret_5`, `ret_10` | multi-day log returns |
| `vol_20`, `vol_60` | rolling std of `ret_1` |
| `SMA20`, `SMA50` | simple moving averages |
| `RSI14` | 14-period RSI |
| `mom20`, `mom60` | momentum over N days |

---

## 5. Frequency & Aggregation Rules

### Daily → Weekly
| Column Type | Aggregation |
|--------------|-------------|
| Price | last close of week |
| Return | sum of daily log returns |
| Volatility | std of daily returns |
| Volume | sum over the week |
| Dollar Volume | sum of daily dollar_vol |

### Weekly → Daily
Forward-fill until next release date, then flag:
- `*_age` = days since last release
- optional `is_stale` boolean when exceeding threshold (7d for weekly, 31d for monthly)

---

## 6. Point-in-Time (PIT) Handling

- All slow-moving data (e.g., fundamentals, macro) must include release_ts | valid_from | valid_to

- Merge via **as-of join**:
release_ts <= asof_date
- Always add `age_days` feature = `(asof_date - release_ts).days`.
- Never use future data (no look-ahead leakage).

---

## 7. Label Definitions

| Horizon | Column | Formula |
|----------|---------|----------|
| 5-day | `y_5` | `log(Close[t+5] / Close[t])` |
| 10-day | `y_10` | `log(Close[t+10] / Close[t])` |
| 1-week | `y_1w` | `log(Close[next_week] / Close[current_week])` |

---

## 8. Portfolio & Risk

| Metric | Definition |
|---------|-------------|
| `turnover` | Σ |wₜ − wₜ₋₁| |
| `cost` | `turnover × (bps / 10000)` |
| `beta` | regression slope vs. SPY returns |
| `alpha` | intercept of that regression |
| `Sharpe` | mean(daily_return) / std(daily_return) × √252 |

---

## 9. Runtime Conventions

| Field | Rule |
|--------|------|
| **Work window** | 06:00–24:00 system local time (configurable) |
| **Pause handling** | Respect `pause.flag` in root dir if present |
| **Logs** | One log per module per run, under `logs/{module}_{YYYYMMDD}.log` |

---

## 10. Versioning & Metadata

Each dataset (`features`, `labels`, `preds`) must include metadata columns:
asof_date | version_tag | source | created_utc

yaml
Copy code

- `version_tag`: e.g., `v1.0.0` or Git commit hash
- `source`: upstream file or script name
- `created_utc`: UTC timestamp when generated

---

## 11. Quality Checks (Mandatory)

1. No duplicate `(Ticker, date)` rows.  
2. Continuous daily calendar per ticker between first and last available date.  
3. No NaN in `Close`, `Volume`, or label columns.  
4. Feature columns must have ≥95% non-NaN coverage.  
5. Dollar volume ≥ threshold from `params.yaml`.

---

## 12. Reproducibility

All deterministic runs must be seed-controlled:
- random seeds in `params.yaml` → `training.seed`
- pseudorandom functions must reference that seed.

---

**Last Updated:** 2025-10-06  
Author: Oscar Rodriguez


