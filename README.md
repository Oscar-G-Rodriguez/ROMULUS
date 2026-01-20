# ROMULUS Phase B

ROMULUS is a deterministic ETF basket backtesting engine built around Wednesday/Friday execution semantics, a configurable cost model, and strict point-in-time data handling. Phase B extends the system with a strategy suite runner, shadow portfolios, and a no-lookahead leaderboard to compare strategies under identical market conditions. Optional meta-strategy selection lets the engine follow the best eligible strategy over time. All runs are auditable with full decision logs, trades, and reliability reporting.

## Install

```bash
python -m venv venv
venv\Scripts\activate
pip install -e ".[dev]"
```

## Quickstart (first 2 minutes)

```bash
romulus init
romulus config validate --config configs/default.yaml
romulus run
romulus suite
```

Example output snippet:

```
Using config: configs\default.yaml
Effective settings:
  backtest.start_date: 2010-01-01
  backtest.end_date: 2024-12-31
  backtest.initial_cash: 10000.0
Outputs will be saved under: outputs\runs
```

Outputs live under `outputs/runs/{run_id}` for single runs and `outputs/suite_runs/{run_id}` for suites.

## Configuration

ROMULUS supports two config types:

- **Run config**: a single strategy backtest (`romulus run`).
- **Suite config**: multiple strategies with shadow portfolios, leaderboard ranking, and optional meta-selection (`romulus suite`).

Warmup + rebase:

- `warmup.enabled`: whether to run a warmup simulation.
- `warmup.start_date`: optional earlier start date for warmup.
- `warmup.rebase`: rebase the scored run to warmup weights at the first scored decision date.

Meta-strategy selection:

- `meta.enabled`: turn on selecting the top-ranked strategy.
- `meta.min_periods_before_selection`: use baseline until this many periods pass.
- `meta.baseline_strategy`: strategy used before selection starts.

Key knobs:

- `backtest.start_date`, `backtest.end_date`, `backtest.initial_cash`
- `costs.commission_per_trade`, `costs.slippage_bps`
- `execution.cash_buffer_pct`, `execution.min_order_notional`
- `leaderboard.dd_limit`, `leaderboard.turnover_limit`, `leaderboard.window`

## Artifacts

Per run or suite, ROMULUS writes auditable artifacts:

- `trades.csv` (all fills/trades)
- `decision_log.jsonl` (decision records)
- `leaderboard.csv` (suite-only)
- `reliability_report.json` (suite-only)

## Determinism

Re-running the same config with the same cached data should produce identical hashes and leaderboard output. For suites, the leaderboard hash is returned in the run result and written to disk as `leaderboard.csv`. Determinism depends on unchanged configs and input data.

## License

MIT
