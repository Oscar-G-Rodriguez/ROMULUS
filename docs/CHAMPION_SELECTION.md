# Regime-Aware Champion Selection

## Ordering and no-lookahead rule

The leaderboard is calculated before the current decision is processed. At decision index `i`, it may use only the dated baseline and fills completed before `i`, completed prior interval returns, and prior turnover. Future rows can be changed without changing an earlier selection.

Every candidate must first pass:

```text
rolling drawdown >= configured drawdown limit
rolling turnover <= configured turnover limit
rolling Sharpe is available
```

Eligible candidates receive a global Sharpe percentile. Once a candidate has four completed intervals previously tagged with the current regime, it also receives a same-regime mean net-return percentile.

```text
composite = 0.60 × global percentile + 0.40 × regime percentile
```

If regime evidence is unavailable, the global percentile is the complete score. Sorting uses higher composite, shallower drawdown, lower turnover, then strategy name for deterministic ties.

## Weekly stabilization

- Wednesday: keep the incumbent identity, but apply its newly computed target weights.
- Friday: compare the top eligible challenger with the incumbent.
- Same winner: retain it.
- Eligible incumbent and different challenger: switch only when the score lead is at least 0.10.
- Ineligible incumbent: switch to the top eligible candidate without applying the margin.
- No eligible candidate or insufficient initial history: use the equal-weight baseline.
- Orders execute at the next valid open.

## Worked example

At Friday close, suppose the as-of regime is `UP_HIGHVOL`. All numbers below were known before Friday’s decision:

| Strategy | Sharpe rank | Regime rank | Composite | Eligible |
|---|---:|---:|---:|---|
| Inverse volatility | 0.75 | 1.00 | 0.85 | Yes |
| Momentum | 1.00 | 0.25 | 0.70 | Yes |
| Equal weight | 0.50 | 0.50 | 0.50 | Yes |

If momentum is incumbent, inverse volatility leads by `0.85 − 0.70 = 0.15`, exceeding the 0.10 margin. The champion changes to inverse volatility and the meta portfolio submits orders for its Friday target weights at the next valid open. If the lead were 0.08, momentum would remain champion.

## Where to audit it

- `leaderboard.csv` contains every candidate and score component for every decision.
- `champion_timeline.csv` contains the user-facing weekly decision trail.
- `meta/decision_log.jsonl` contains the same selection explanation plus weights and portfolio values.
- `meta/trades.csv` proves what the separate meta portfolio executed.

The after-run `best_overall` summary is descriptive and is not the historical champion path.

