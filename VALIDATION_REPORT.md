# ROMULUS Validation Report

## Scope

This report covers deterministic engine mechanics, not investment performance. The default test suite is offline: integration tests substitute synthetic OHLCV data and do not download market data.

## Controls verified

- Portfolio CAGR uses the elapsed dates between first and last valuation; no event count is treated as 252 trading days.
- Sharpe is calculated from dated, irregular log-return increments. Leaderboard scoring consumes dated portfolio values rather than applying a fixed annualization factor to Wednesday/Friday events.
- Slippage is embedded once in the adverse execution price. `slippage_cost` is audit information, `net_cost` is slippage plus commission, and `cash_flow` is the signed cash movement.
- Fills execute sales before buys and partially fill purchases that are unaffordable at the actual execution price. Cash and positions reconcile from the recorded fills.
- Omitted targets generate liquidation orders when a valid mark exists. Missing/invalid marks for a held position raise an error instead of silently omitting its value.
- Strategy inputs remain as-of sliced. ML feature and external-feature tests mutate future inputs and verify earlier calculations are unchanged. Completed ML forecasts are scored post-run in `ml_evaluation.json` against zero and persistence naïve baselines, with any deterministic ridge candidate identified as the reference.
- External macro/alternative features are disabled by default. If enabled, they require an explicit `available_date` field; observation-date-only alignment is rejected.
- Champion selection records the current as-of market regime and combines cross-sectional ranks using 60% timestamp-aware rolling Sharpe and 40% same-regime after-cost return after four completed matching-regime intervals. Until then it uses 100% global Sharpe rank. A switch is considered only on Friday close, requires a 0.10 normalized-score lead when the incumbent remains eligible, and is filled at the next valid open.
- The meta decision audit records the incumbent, challenger, selection reason, raw scores, percentile ranks, target weights, fills, cash, positions, commission, slippage, and holdings-value reconciliation after every decision.

## How to reproduce

```powershell
uv python install 3.12
uv sync --frozen
uv run pytest
uv run python scripts/offline_demo.py
```

The demo writes all individual shadow portfolios plus the meta portfolio, dated values, the champion timeline, forecasts, ML diagnostics, decision logs, metrics, and a manifest under `outputs/offline_demo/suite_runs/`. Its prices are synthetic and it is solely an accounting/timing demonstration.

The project is locked to Python 3.12 with `uv`; CI checks that `uv.lock` is current before running the offline suite. Run manifests report the Python, `uv`, XGBoost, and actual model-training devices. The native frontend also provides a real CUDA fit-and-predict diagnostic with a memory-conscious CUDA retry and CPU XGBoost fallback.

Last local validation (2026-09-12, Python 3.12.14, XGBoost 3.4.1): **77 passed, 1 skipped** with 55% branch-aware coverage. The opt-in skipped test is the hardware-dependent CUDA pytest. A separate real fit-and-predict diagnostic succeeded on `cuda:0` using the NVIDIA RTX 5070 Ti (driver 591.86), and the operational `device="auto"` path also recorded both CUDA and CPU training devices where fallback or baseline work applied.

The deterministic demonstration run `20260912_173631_d66445` completed its 204-decision schedule across 12 shadow strategies—including a distinct buy-and-hold benchmark—plus the separate meta portfolio. Buy-and-hold produced exactly five initial asset fills and no scheduled rebalances. The run recorded 30 champion changes, all on Fridays, 210 structured progress events ending at 100%, and an evaluated ML report. The largest absolute accounting reconciliation residual was approximately `1.82e-12`, effectively machine precision. These facts validate mechanics on generated data; they are not evidence of investment performance or model superiority.

## ML and benchmark limits

Ridge and XGBoost strategies fit embargoed walk-forward training windows and the report labels chronological training, validation, and holdout segments. It reports return, volatility, and RAR diagnostics against zero-return, persistence, and Ridge references. The synthetic run does not establish ML value: generated prices are not a market dataset, and the report itself forbids a superiority claim without a predeclared untouched real-data holdout after costs.

## Residual risks

- Market-data adjustments, delistings, corporate actions, and vendor revisions require an independently curated point-in-time dataset for empirical claims.
- The current external-data fetchers cannot create vintage/publication metadata on their own; users must supply it before those features are admitted.
- A strategy suite ranks the simulated candidates; a ranking is not out-of-sample validation or proof of economic value.
- Tkinter presenters and imports are tested headlessly, but automated pixel-level screenshot comparison is not yet part of CI.

## Truthful draft resume bullets

- Built ROMULUS, a deterministic Python event-driven research backtester that evaluates 11 shadow strategies and a regime-aware meta portfolio with prior-only Friday champion selection, next-open execution, exact transaction-cost accounting, and decision-level audit artifacts.
- Added walk-forward XGBoost and Ridge forecasting, chronological baseline diagnostics, timestamp-aware risk metrics, adversarial no-lookahead tests, reproducible synthetic demonstrations, and a native Tkinter workflow for bounded data preparation, progress tracking, comparison, and audit drill-down.
