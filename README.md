# ROMULUS Phase B+

ROMULUS is a deterministic ETF basket backtesting engine built around Wednesday/Friday decision events, explicit execution timing (open/close), and a configurable cost model. Phase B+ expands the engine with a strategy suite runner, shadow portfolios, and a no-lookahead leaderboard that compares strategies under identical market conditions. Optional meta-strategy selection lets ROMULUS trade the top eligible strategy over time. All runs are audit-ready with full decision logs, trades, holdings, forecasts, and reliability reporting.

## Install

```bash
python -m venv venv
venv\Scripts\activate
pip install -e ".[dev]"
```

For ML strategies (XGBoost), install the optional ML extras:

```bash
pip install -e ".[dev,ml]"
```

## Quickstart (first 2 minutes)

```bash
romulus init
romulus config validate --config configs/default.yaml
romulus run
romulus suite
```

See available strategies:

```bash
romulus strategies list
```

You can also validate the suite config:

```bash
romulus config validate --config configs/suite_default.yaml --suite
```

ROMULUS prints the config it resolved, effective settings, and output locations. By default, it offers a pre-run edit wizard; use `--no-edit` to skip the prompt.

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

Parameter variants:

- `param_grid`: expand a strategy into multiple parameterized variants automatically in a suite run.

Key knobs:

- `backtest.start_date`, `backtest.end_date`, `backtest.initial_cash`
- `execution.decision_time`, `execution.fill_time`, `execution.max_weight`, `execution.turnover_cap`
- `costs.commission_per_trade`, `costs.slippage_bps`
- `leaderboard.dd_limit`, `leaderboard.turnover_limit`, `leaderboard.window`
- `meta.min_periods_before_selection`

## ML strategies

ROMULUS ships ML strategies (ridge or XGBoost) that use only OHLCV features and strict as-of alignment. Enable XGBoost by installing the ML extra and set `model_family: "xgboost"` in the strategy params. GPU training is supported via `device: "cuda"` or `device: "auto"`; `auto` will fall back to CPU if CUDA is unavailable. For deterministic runs and tests, keep `device: "cpu"`.

## Artifacts

Per run or suite, ROMULUS writes auditable artifacts such as:

- `orders.csv`, `fills.csv`, `trades.csv`, `holdings.csv`
- `decision_log.jsonl`
- `forecasts.csv` (ML runs)
- `leaderboard.csv`, `reliability_report.json` (suite runs)
- `warmup_summary.json`, `initialization_trades.csv` (suite warmup + rebase)

## Determinism

Re-running the same config with the same cached data should produce identical hashes and leaderboard output. For suites, the leaderboard hash is returned in the run result and written to disk as `leaderboard.csv`. Determinism depends on unchanged configs and input data; ML determinism is strongest when `device: "cpu"` is used.

## License

MIT
