# ROMULUS

ROMULUS is a deterministic, event-driven research backtester that compares multiple strategy portfolios and lets a regime-aware meta-portfolio follow a weekly champion.

> **Research software only.** ROMULUS is not a live-trading system. It was a personal project, was not used in a competition, and provides no evidence of profitability, investment performance, or external validation.

## The 60-second explanation

1. ROMULUS reads point-in-time price history and schedules Wednesday/Friday decisions.
2. Every configured strategy receives the same as-of data and runs its own independent “shadow” portfolio.
3. Before each decision, ROMULUS measures only completed prior intervals. It ranks global rolling Sharpe and performance in the current market regime.
4. At Friday close, an eligible challenger can replace the incumbent if its composite score leads by the configured margin.
5. The meta-portfolio copies the champion’s current target weights and fills at the next available open.
6. The desktop app and audit files explain the regime, rankings, weights, orders, fills, costs, holdings, and outcome for every decision.

```text
dated OHLCV ──► as-of strategy suite ──► prior-only leaderboard
     │                    │                       │
     └──► regime state ───┘                       ▼
                                      weekly champion decision
                                                  │
                                                  ▼
                                  next-open meta-portfolio fills
                                                  │
                                                  ▼
                                  UI + reproducible audit artifacts
```

## Start here

```powershell
uv python install 3.12
uv sync --frozen --group dev
uv run pytest
uv run python scripts/offline_demo.py
uv run romulus ui
```

The offline demo generates deterministic synthetic prices and never downloads market data. In the app, choose **Synthetic**, click **Inspect Coverage**, select bounded dates, and click **Run ROMULUS Suite**.

The application is the primary workflow:

- **Setup:** edit every suite setting, select synthetic/cache/market data, inspect coverage, and choose only valid dates.
- **Run:** see the current simulated date, completed decisions, overall progress, active champion, ETA, and safe cancellation.
- **Overview:** compare the meta portfolio with every individual strategy.
- **Champion Timeline:** inspect the regime, incumbent, challenger, winner, margin, and reason each week.
- **ML Accuracy:** inspect return, volatility, and risk-adjusted-return forecast diagnostics.
- **Decision Audit:** click a champion date and follow the complete evidence chain through signals, weights, fills, costs, positions, and value.
- **Diagnostics:** run a real CUDA XGBoost fit and see whether execution used `cuda:0` or CPU fallback.

## Champion selection

The default meta strategy is enabled. Every candidate is simulated independently before ROMULUS decides which one the separate meta portfolio should follow.

For each eligible strategy, ROMULUS calculates cross-sectional percentile ranks:

```text
champion score = 0.60 × rolling-Sharpe rank
               + 0.40 × same-regime net-return rank
```

The regime term activates after four completed matching-regime intervals. Before that, the global rank receives 100% weight. A strategy is ineligible when its rolling drawdown is below −20% or turnover exceeds 1.0. Champion identity may change only on Friday, and a normal challenger must lead the eligible incumbent by at least 0.10. Wednesday decisions may rebalance the incumbent but cannot change its identity.

The regime proxy is SPY when available:

| Input | Classification |
|---|---|
| 63-day return | `UP` above 3%; `DOWN` below −3%; otherwise `SIDE` |
| 21-day daily volatility × √252 | `LOWVOL` below 18%; otherwise `HIGHVOL` |
| 63-day drawdown | append `STRESS` at or below −12% |
| Fewer than 64 observations | `UNKNOWN` |

See [Champion selection](docs/CHAMPION_SELECTION.md) for the timing proof and worked example.

## Strategies

| Strategy | Signal and allocation | Cash behavior | ML |
|---|---|---|---|
| Cash | No asset targets | 100% cash | No |
| Buy and hold | Equal initial purchase, then no scheduled rebalance orders | Initial execution buffer remains cash | No |
| Equal weight | Equal allocation to eligible assets | Constraint buffer only | No |
| Inverse volatility | Weight proportional to inverse trailing daily volatility | Unscored assets remain cash | No |
| Time-series momentum | Own assets with positive trailing return | Fully defensive when none qualify | No |
| Cross-sectional momentum | Own the strongest trailing-return assets | Defensive when the leader fails its floor | No |
| Volatility target | Scale equal/inverse-vol exposure toward a target volatility | Unused risk budget stays cash | No |
| Moving-average crossover | Own assets whose fast average exceeds the slow average | Defensive for negative signals | No |
| ML return | Rank predicted next-interval net return | Cash when predicted edge is non-positive | XGBoost |
| ML volatility | Prefer lowest predicted interval volatility | Constraint buffer only | XGBoost |
| ML RAR | Rank predicted net return divided by predicted interval volatility | Cash when predicted edge is non-positive | XGBoost/Ridge baseline |

## Metric definitions

| Metric | Definition |
|---|---|
| Interval return | next fill-open ÷ current fill-open − 1 |
| Portfolio total return | ending value ÷ starting value − 1 |
| CAGR | compound growth over actual elapsed calendar days |
| Annualized volatility | timestamp-aware residual log-return volatility scaled over 365.25 days |
| Sharpe | annualized timestamp-aware log-return drift ÷ annualized volatility; zero risk-free rate |
| Realized interval volatility | square root of summed squared daily log returns between fills |
| Predicted RAR | (predicted interval return − estimated cost fraction) ÷ predicted interval volatility |
| Drawdown | portfolio value relative to its prior running maximum |

Event-level portfolio metrics never pretend the twice-weekly observations are 252 daily observations. The √252 conversion is used only where the underlying observations truly are daily returns, such as the regime volatility classifier.

## ML validation

XGBoost uses fixed parameters, deterministic seeds, an embargo, and walk-forward training. It attempts CUDA first and falls back to deterministic CPU XGBoost with the reason recorded. Ridge is always a separately named comparison candidate.

`ml_evaluation.json` reports return MAE/RMSE/directional accuracy/rank correlation, volatility error and calibration, RAR rank diagnostics, and top-selection hit rate. Forecasts are divided chronologically into training, validation, and final-holdout reporting segments. These diagnostics are descriptive; they do not establish that ML adds value.

See [ML validation](docs/ML_VALIDATION.md).

## Audit artifacts

Each suite run is stored beneath `outputs/suite_runs/<run-id>/`:

- `suite_summary.json`: meta and individual portfolio comparison.
- `leaderboard.csv`: every candidate’s score components, gates, and rank on every decision.
- `champion_timeline.csv`: week-by-week incumbent, challenger, selection, and reason.
- `meta/decision_log.jsonl` and `meta/trades.csv`: executed meta decisions and trades.
- `<strategy>/decision_log.jsonl`, `orders.csv`, `fills.csv`, `trades.csv`, and `holdings.csv`: shadow-portfolio evidence.
- `forecasts.csv` and `ml_evaluation.json`: predictions, mature labels, and accuracy diagnostics.
- `regime_leaderboard.csv`: descriptive after-run regime breakdown.
- `manifest.json`: configuration hash, data coverage/checksums, runtime/device metadata, progress history, and completion status.

## Correctness boundaries

- Strategy inputs are sliced as of each decision.
- ML labels end before the current training decision and observe the configured embargo.
- External features require explicit availability dates; observation dates alone are rejected.
- Slippage exists once in the adverse fill price. `slippage_cost` is an audit decomposition, not another cash charge.
- Sales execute before purchases, unaffordable buys are reduced, and missing marks for held positions are errors.
- Omitted targets are liquidation instructions, not permission to silently retain holdings.
- Cancellation occurs at a decision boundary and creates a manifest marked `cancelled`.

Detailed material:

- [Architecture and accounting](docs/ARCHITECTURE.md)
- [Champion selection](docs/CHAMPION_SELECTION.md)
- [ML validation](docs/ML_VALIDATION.md)
- [Desktop workflow](docs/UI_GUIDE.md)
- [Public export guide](docs/PUBLIC_EXPORT.md)
- [Correctness validation report](VALIDATION_REPORT.md)

## Limitations and risk

Backtests remain sensitive to survivorship, delistings, corporate actions, point-in-time availability, data-vendor revisions, and execution assumptions. Synthetic demonstrations prove mechanics only. A favorable historical period is not evidence of future performance. Nothing here is investment advice or a recommendation.

## License

MIT
