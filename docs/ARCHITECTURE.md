# Architecture and Accounting

## Event lifecycle

ROMULUS constructs a dated decision calendar, then maps every decision to a valid fill. With the default settings, information is observed at Wednesday or Friday close and orders fill at the next market open. A decision at the end of the requested range is skipped when no valid fill exists inside that range.

For each decision:

1. Slice prices and optional point-in-time features through the decision date.
2. Determine which assets are eligible by inception date and valid mark.
3. Ask every strategy for raw target weights.
4. Apply maximum-weight and turnover constraints.
5. Generate liquidation, sale, and purchase orders from current positions.
6. Fill sales before purchases at an adverse slippage-adjusted price.
7. Apply fixed commissions once, cap purchases to available cash, and update positions.
8. Revalue holdings plus cash and append the dated audit records.

The meta portfolio is separate from all shadow portfolios. It copies the selected strategy’s constrained target weights but creates and fills its own orders, so its switching costs are not borrowed from the shadow portfolio.

## Accounting identities

For a buy, the fill price is `reference price × (1 + slippage bps / 10,000)`. For a sale it is `reference price × (1 − slippage bps / 10,000)`. Cash changes by the signed fill notional and commission. Slippage is therefore already present in cash through the adverse price; `slippage_cost` only explains the difference from the reference-price notional.

After every fill batch:

```text
cash_after = cash_before + sum(fill.cash_flow)
position_after[ticker] = position_before[ticker] + sum(fill.shares)
portfolio_value = cash_after + sum(position_shares × valid_mark)
net_cost = slippage_cost + commission
```

Missing or non-positive marks for held assets are errors. Empty target weights mean liquidate into cash. Fractional-share behavior, cash buffers, maximum weights, minimum notionals, and turnover caps are explicit configuration.

## Data coverage

Coverage inspection records each ticker’s valid first/last OHLCV date, missing fields, business-day gaps, and checksum. Dynamic eligibility permits staggered inception at the beginning of a study. Common-overlap mode delays the study until every selected asset has history. Both modes use a safe common ending bound so no held asset is silently valued at a stale price.

The synthetic source is deterministic and offline. Cache mode refuses network access. The yfinance mode downloads only through an explicit run or the desktop Data Preparation action. Market-data output is not treated as a point-in-time institutional dataset.

## Determinism and manifests

Runs retain a configuration hash, data checksums/coverage, Python and XGBoost versions, actual execution devices, completion status, and structured progress history. Fixed XGBoost parameters use a deterministic seed and one CPU thread. Same-device results are expected to repeat; small CPU/GPU floating-point differences are not represented as economic findings.

## Glossary

- **Shadow portfolio:** independent simulation of one candidate strategy.
- **Meta portfolio:** separate portfolio that follows the selected champion.
- **Champion:** strategy whose weights the meta portfolio currently follows.
- **Incumbent:** current champion before a weekly evaluation.
- **Fill:** simulated execution of an order at a dated price.
- **Turnover:** absolute portfolio-weight change requested at a rebalance.
- **Warmup:** pre-evaluation history used to initialize signals or weights.
- **Holdout:** final chronological segment not used to choose features, parameters, or selection rules.

