# ML Features and Validation

## Where ML is used

ML is confined to explicitly configured strategies. It does not invent fills, override accounting, or classify regimes.

- `ml_return` predicts next-fill-to-next-fill asset return.
- `ml_vol` predicts realized volatility over the next fill interval.
- `ml_risk_adjusted` trains return and volatility models and ranks `(mu − estimated cost) / sigma`.

The base feature set contains trailing returns, realized volatility, drawdown, moving-average ratios, an ATR proxy, and volume z-score. The optional expanded set adds 126-day measures, RSI, and a trend slope. External features remain disabled unless they carry explicit availability dates.

## Labels and alignment

A feature row is computed using data through its decision close. Its return label begins at that decision’s fill and ends at the following fill. Its volatility label is the root-sum-square of daily log returns within the same fill interval. Training excludes incomplete labels and applies the configured number of embargo intervals.

Volatility is trained in log space and transformed back after prediction, ensuring non-negative forecasts. RAR uses predicted interval return and predicted interval volatility at compatible horizons.

## XGBoost and Ridge

XGBoost is the operational model. `device: auto` tries `cuda:0`, retries with a memory-conscious quantile matrix, then uses CPU XGBoost while retaining the failure reason. The Diagnostics tab performs a real fit/predict probe rather than reporting GPU presence alone.

Ridge receives the same feature and training-row definitions as a named baseline. A fallback never relabels Ridge as XGBoost.

## Accuracy report

Mature forecasts receive labels only after the run for evaluation:

- Return: MAE, RMSE, sign accuracy, and per-date cross-sectional rank correlation.
- Volatility: MAE, RMSE, rank correlation, and mean-prediction/mean-realization calibration.
- RAR: rank diagnostics and whether the top predicted asset was the top realized asset.
- Baselines: zero return, prior return, prior realized volatility, and Ridge.

The report includes chronological train/validation/holdout counts. Features, parameters, and selection rules must be frozen before interpreting the final holdout. Statistical accuracy is shown separately from strategy turnover, costs, and after-cost portfolio results.

No metric automatically establishes that ML adds value. A conclusion would require the untouched holdout to beat predeclared naïve and Ridge baselines after costs, with enough observations to be credible.

