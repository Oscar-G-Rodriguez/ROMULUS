# ROMULUS Phase A - Build Plan

## Overview
This plan implements the ROMULUS Phase A backtesting engine as specified in `PRD.md`.

**Reference:** `PRD.md`

---

## Task List

```json
[
  {
    "category": "setup",
    "description": "Initialize project structure and dependencies",
    "steps": [
      "Create directory structure: romulus/{data,calendar,portfolio,strategy,backtest,config,cli}",
      "Create tests/{unit,integration} directories",
      "Create configs/ directory",
      "Create data/cache/ directory (add to .gitignore)",
      "Create outputs/runs/ directory (add to .gitignore)",
      "Create pyproject.toml with dependencies: pandas, numpy, yfinance, pydantic, pyarrow, click, pytest, pandas-market-calendars, pyyaml",
      "Create .gitignore (data/cache/, outputs/runs/, __pycache__/, *.pyc, .pytest_cache/, venv/, .venv/)",
      "Create README.md with project overview",
      "Install dependencies: pip install -e .",
      "Verify imports work: python -c 'import pandas, numpy, yfinance, pydantic, pyarrow, click, pytest'"
    ],
    "passes": true
  },
  {
    "category": "setup",
    "description": "Create config files and validation schemas",
    "steps": [
      "Create configs/universe_default.json with 4 ETFs (SPY, QQQ, IWM, TLT) and inception dates",
      "Create configs/etf_equal_weight.yaml per PRD Section 7.1",
      "Create romulus/config/__init__.py",
      "Create romulus/config/schema.py with pydantic models for BacktestConfig, UniverseConfig, ExecutionConfig, CostConfig",
      "Add config loading function: load_config(path) -> BacktestConfig",
      "Create test: tests/unit/test_config.py with test_config_loads_successfully()",
      "Run: pytest tests/unit/test_config.py -v"
    ],
    "passes": true
  },
  {
    "category": "data",
    "description": "Implement ETF universe with inception gating",
    "steps": [
      "Create romulus/data/__init__.py",
      "Create romulus/data/universe.py",
      "Implement Universe class with load_from_json(path) method",
      "Implement Universe.get_eligible_tickers(as_of_date: date) -> List[str] with inception gating",
      "Implement Universe.get_inception_date(ticker: str) -> date",
      "Create tests/unit/test_universe.py",
      "Add test_inception_gating_tlt() to verify TLT not eligible before 2002-07-26",
      "Add test_all_eligible_after_latest_inception() to verify all 4 ETFs eligible after 2002-07-26",
      "Run: pytest tests/unit/test_universe.py -v"
    ],
    "passes": false
  },
  {
    "category": "data",
    "description": "Implement yfinance data ingestion with caching",
    "steps": [
      "Create romulus/data/ingestion.py",
      "Implement fetch_daily_data(tickers: List[str], start: str, end: str, cache_dir: str) -> pd.DataFrame",
      "Use yf.download() with auto_adjust=True for split/dividend adjustments",
      "Implement cache logic: check if data/cache/{ticker}_{start}_{end}.parquet exists",
      "If cache hit: load from Parquet, else download and save to cache",
      "Add MD5 checksum computation: compute_checksum(df: pd.DataFrame) -> str",
      "Store checksums in cache metadata file: data/cache/checksums.json",
      "Create tests/unit/test_ingestion.py",
      "Add test_data_fetch_and_cache() to verify caching works",
      "Add test_cache_hit_skip_download() to verify cache hits skip yfinance call",
      "Run: pytest tests/unit/test_ingestion.py -v"
    ],
    "passes": false
  },
  {
    "category": "data",
    "description": "Implement Parquet/JSON storage layer",
    "steps": [
      "Create romulus/data/storage.py",
      "Implement save_parquet(df: pd.DataFrame, path: str)",
      "Implement load_parquet(path: str) -> pd.DataFrame",
      "Implement save_json(data: dict, path: str)",
      "Implement load_json(path: str) -> dict",
      "Implement compute_dataframe_hash(df: pd.DataFrame) -> str using MD5 of sorted column names + dtypes + first/last rows",
      "Create tests/unit/test_storage.py",
      "Add test_parquet_roundtrip() to verify save/load produces identical DataFrame",
      "Add test_json_roundtrip() to verify save/load produces identical dict",
      "Run: pytest tests/unit/test_storage.py -v"
    ],
    "passes": false
  },
  {
    "category": "calendar",
    "description": "Generate NYSE trading calendar",
    "steps": [
      "Create romulus/calendar/__init__.py",
      "Create romulus/calendar/trading_days.py",
      "Import pandas_market_calendars: import pandas_market_calendars as mcal",
      "Implement get_trading_days(start: str, end: str) -> List[date] using mcal.get_calendar('NYSE')",
      "Implement is_trading_day(date: date) -> bool",
      "Create tests/unit/test_calendar.py",
      "Add test_no_weekends() to verify no Sat/Sun in trading days",
      "Add test_no_holidays() to verify Christmas 2024-12-25 not in trading days",
      "Run: pytest tests/unit/test_calendar.py -v"
    ],
    "passes": false
  },
  {
    "category": "calendar",
    "description": "Generate Wed/Fri decision calendar with fill date mapping",
    "steps": [
      "Create romulus/calendar/decision_days.py",
      "Implement generate_decision_calendar(start: str, end: str, days: List[str] = ['wednesday', 'friday']) -> List[date]",
      "Filter trading_days to only include weekday 2 (Wed) and 4 (Fri)",
      "Implement get_next_trading_day(date: date, trading_days: List[date]) -> date for fill date lookup",
      "Add test_decision_calendar_wed_fri_only() to verify only Wed/Fri in results",
      "Add test_no_holiday_decisions() to verify no holidays in decision calendar",
      "Add test_fill_date_mapping() to verify each decision date maps to next trading day",
      "Run: pytest tests/unit/test_calendar.py -v"
    ],
    "passes": false
  },
  {
    "category": "portfolio",
    "description": "Implement Portfolio account tracker",
    "steps": [
      "Create romulus/portfolio/__init__.py",
      "Create romulus/portfolio/account.py",
      "Define Portfolio class with cash: float and positions: Dict[str, float]",
      "Implement compute_market_value(self, prices: Dict[str, float]) -> float",
      "Implement get_total_value(self, prices: Dict[str, float]) -> float (cash + market_value)",
      "Implement apply_fills(self, fills: List[Fill]) to update cash and positions",
      "Create tests/unit/test_portfolio.py",
      "Add test_cash_accounting() to verify cash decreases by exact fill amount + costs",
      "Add test_fractional_shares() to verify positions support fractional shares (e.g., 2.5 shares)",
      "Add test_market_value_calculation() to verify total value computed correctly",
      "Run: pytest tests/unit/test_portfolio.py -v"
    ],
    "passes": false
  },
  {
    "category": "portfolio",
    "description": "Implement order generation logic",
    "steps": [
      "Create romulus/portfolio/orders.py",
      "Define Order dataclass with: ticker, shares, decision_date, target_weight",
      "Implement generate_orders(target_weights: Dict[str, float], current_positions: Dict[str, float], prices: Dict[str, float], cash: float, total_value: float, min_notional: float, cash_buffer_pct: float) -> List[Order]",
      "For each ticker: compute target_value = target_weight * total_value * (1 - cash_buffer_pct)",
      "Compute current_value = current_positions.get(ticker, 0) * prices[ticker]",
      "Compute shares_to_trade = (target_value - current_value) / prices[ticker]",
      "Filter out orders where abs(shares_to_trade * prices[ticker]) < min_notional",
      "Return List[Order]",
      "Add test_order_generation_respects_min_notional() to verify orders < $1 filtered out",
      "Add test_order_generation_respects_cash_buffer() to verify 1% cash buffer maintained",
      "Run: pytest tests/unit/test_portfolio.py -v"
    ],
    "passes": false
  },
  {
    "category": "portfolio",
    "description": "Implement fill simulation with slippage",
    "steps": [
      "Create romulus/portfolio/fills.py",
      "Define Fill dataclass with: ticker, shares, fill_price, fill_date, commission, slippage_cost, gross_value, net_cost",
      "Implement simulate_fills(orders: List[Order], fill_prices: Dict[str, float], fill_date: date, slippage_bps: float, commission: float) -> List[Fill]",
      "For each order: sign = 1 if shares > 0 else -1",
      "Compute fill_price = fill_prices[ticker] * (1 + sign * slippage_bps / 10000)",
      "Compute gross_value = abs(shares) * fill_price",
      "Compute slippage_cost = gross_value * (slippage_bps / 10000)",
      "Compute net_cost = gross_value + commission + slippage_cost",
      "Return List[Fill]",
      "Add test_slippage_applied_correctly() to verify buy pays slippage, sell pays slippage",
      "Add test_commission_applied() to verify commission added to net_cost",
      "Run: pytest tests/unit/test_portfolio.py -v"
    ],
    "passes": false
  },
  {
    "category": "strategy",
    "description": "Define base strategy interface",
    "steps": [
      "Create romulus/strategy/__init__.py",
      "Create romulus/strategy/base.py",
      "Define BaseStrategy abstract class using ABC",
      "Add abstract method: compute_target_weights(as_of_date: date, eligible_tickers: List[str], prices: pd.DataFrame, positions: Dict[str, float]) -> Dict[str, float]",
      "Add docstring: 'Returns target weights where sum(weights) <= 1.0. Only allocate to eligible_tickers.'",
      "No tests needed (abstract class)"
    ],
    "passes": false
  },
  {
    "category": "strategy",
    "description": "Implement equal-weight baseline strategy",
    "steps": [
      "Create romulus/strategy/equal_weight.py",
      "Implement EqualWeightStrategy(BaseStrategy)",
      "In compute_target_weights: return {ticker: 1.0 / len(eligible_tickers) for ticker in eligible_tickers}",
      "Create tests/unit/test_strategy.py",
      "Add test_equal_weight_sums_to_one() to verify sum(weights.values()) ≈ 1.0",
      "Add test_equal_weight_excludes_ineligible() to verify only eligible tickers in output",
      "Add test_equal_weight_handles_single_ticker() to verify works with 1 ticker (weight = 1.0)",
      "Run: pytest tests/unit/test_strategy.py -v"
    ],
    "passes": false
  },
  {
    "category": "backtest",
    "description": "Implement cost model",
    "steps": [
      "Create romulus/backtest/__init__.py",
      "Create romulus/backtest/costs.py",
      "Implement compute_slippage(shares: float, price: float, slippage_bps: float) -> float",
      "Formula: abs(shares) * price * (slippage_bps / 10000)",
      "Implement compute_commission(shares: float, commission_per_trade: float) -> float",
      "Return commission_per_trade if abs(shares) > 0 else 0",
      "Create tests/unit/test_backtest.py",
      "Add test_slippage_calculation() to verify 5 bps on $1000 = $0.50",
      "Add test_commission_calculation() to verify commission applied when shares > 0",
      "Run: pytest tests/unit/test_backtest.py -v"
    ],
    "passes": false
  },
  {
    "category": "backtest",
    "description": "Implement performance metrics",
    "steps": [
      "Create romulus/backtest/metrics.py",
      "Implement compute_metrics(portfolio_value: pd.Series) -> dict",
      "Calculate total_return = (final_value - initial_value) / initial_value * 100",
      "Calculate num_years = len(portfolio_value) / 252",
      "Calculate cagr = ((final_value / initial_value) ** (1 / num_years) - 1) * 100",
      "Calculate returns = portfolio_value.pct_change().dropna()",
      "Calculate sharpe = returns.mean() / returns.std() * sqrt(252) if returns.std() > 0 else 0",
      "Calculate running_max = portfolio_value.cummax()",
      "Calculate drawdown = (portfolio_value - running_max) / running_max",
      "Calculate max_drawdown = drawdown.min() * 100",
      "Return dict with: total_return, cagr, sharpe, max_drawdown, final_value, initial_value",
      "Add test_metrics_calculation() with known portfolio_value series",
      "Run: pytest tests/unit/test_backtest.py -v"
    ],
    "passes": false
  },
  {
    "category": "backtest",
    "description": "Implement main backtest engine",
    "steps": [
      "Create romulus/backtest/engine.py",
      "Define BacktestEngine class",
      "Implement run(config: BacktestConfig) -> dict method",
      "Step 1: Load universe from config.universe.source",
      "Step 2: Get all tickers and fetch data using fetch_daily_data()",
      "Step 3: Generate decision_calendar using generate_decision_calendar(config.start_date, config.end_date)",
      "Step 4: Initialize portfolio = Portfolio(cash=config.initial_cash, positions={})",
      "Step 5: Create empty lists for orders_list, fills_list, positions_history, portfolio_value_history",
      "Step 6: Loop through decision_dates:",
      "  - Get eligible_tickers = universe.get_eligible_tickers(decision_date)",
      "  - Get decision_prices (close prices on decision_date)",
      "  - Compute target_weights using strategy.compute_target_weights()",
      "  - Generate orders using generate_orders()",
      "  - Get fill_date = get_next_trading_day(decision_date)",
      "  - Get fill_prices (open prices on fill_date)",
      "  - Simulate fills using simulate_fills()",
      "  - Apply fills to portfolio using portfolio.apply_fills()",
      "  - Record positions_history and portfolio_value_history",
      "Step 7: Compute metrics using compute_metrics(portfolio_value_series)",
      "Step 8: Create run_id = timestamp + config_hash[:6]",
      "Step 9: Save outputs to outputs/runs/{run_id}/",
      "Step 10: Return dict with run_id, metrics, output_path",
      "Create tests/integration/test_end_to_end.py",
      "Add test_full_backtest_completes() to verify backtest runs without errors",
      "Run: pytest tests/integration/test_end_to_end.py -v"
    ],
    "passes": false
  },
  {
    "category": "backtest",
    "description": "Add determinism and lookahead tests",
    "steps": [
      "Create tests/integration/test_backtest_determinism.py",
      "Implement test_deterministic_runs() that runs same config twice and compares:",
      "  - config_hash matches",
      "  - portfolio_value DataFrames are identical",
      "  - final_value matches",
      "Implement test_no_lookahead() that verifies:",
      "  - Orders on decision_date D only use prices from dates <= D",
      "  - Fills occur on fill_date = next_trading_day(D) where fill_date > D",
      "Implement test_costs_applied() that verifies:",
      "  - All fills have slippage_cost > 0",
      "  - net_cost > gross_value for all fills",
      "Run: pytest tests/integration/test_backtest_determinism.py -v",
      "Verify all tests pass"
    ],
    "passes": false
  },
  {
    "category": "cli",
    "description": "Implement CLI interface with click",
    "steps": [
      "Create romulus/cli/__init__.py",
      "Create romulus/cli/main.py",
      "Use click to define: @click.command() def run(config: str, start: str, end: str)",
      "Load config from YAML using load_config(config)",
      "Override config.start_date and config.end_date if --start/--end provided",
      "Create BacktestEngine and call engine.run(config)",
      "Print summary: final_value, total_return, cagr, sharpe, max_drawdown",
      "Print output location: f'Outputs saved to: {result[\"output_path\"]}'",
      "Add --help text describing each parameter",
      "Make CLI executable: if __name__ == '__main__': run()",
      "Test: python -m romulus.cli.main run --config configs/etf_equal_weight.yaml --help"
    ],
    "passes": false
  },
  {
    "category": "cli",
    "description": "Create example run and verify outputs",
    "steps": [
      "Run: python -m romulus.cli.main run --config configs/etf_equal_weight.yaml",
      "Verify outputs/runs/{run_id}/ directory created",
      "Verify manifest.json exists and contains: config_hash, data_checksums, status, execution_time_seconds, created_at",
      "Verify orders.parquet exists and can be loaded with pd.read_parquet()",
      "Verify fills.parquet exists and contains columns: ticker, shares, fill_price, fill_date, commission, slippage_cost, net_cost",
      "Verify positions.parquet exists",
      "Verify portfolio_value.parquet exists",
      "Verify metrics.json exists and contains: total_return, cagr, sharpe, max_drawdown, final_value",
      "Load portfolio_value.parquet and verify final value > initial value (assuming positive returns)"
    ],
    "passes": false
  },
  {
    "category": "documentation",
    "description": "Create comprehensive README with usage examples",
    "steps": [
      "Update README.md with project overview from PRD",
      "Add 'Features' section listing key capabilities",
      "Add 'Installation' section: git clone, cd romulus, pip install -e .",
      "Add 'Quick Start' section with example: python -m romulus.cli.main run --config configs/etf_equal_weight.yaml",
      "Add 'Configuration' section explaining YAML structure",
      "Add 'Output Structure' section showing run directory contents",
      "Add 'Adding New Strategies' section with BaseStrategy example",
      "Add 'Testing' section: pytest tests/ -v",
      "Add 'Development' section with contribution guidelines",
      "Add license information (if applicable)"
    ],
    "passes": false
  }
]
```

---

## Agent Instructions

1. **Read `activity.md` first** to understand what has been completed recently
2. **Find the next task** where `"passes": false`
3. **Complete all steps** for that task in order
4. **Run tests** after implementation (if tests exist for that task)
5. **Update `plan.md`**: Change that task's `"passes"` from `false` to `true`
6. **Log completion** in `activity.md` with:
   - Date/time
   - Task completed (category + description)
   - Tests run and results
   - Any issues encountered
7. **Make ONE git commit** for that task with message: `"feat(category): description"`
8. **Repeat** until all tasks have `"passes": true`

---

## Completion Criteria

**All tasks marked with `"passes": true`**

When complete, output exactly: **`<promise>COMPLETE</promise>`**

---

## Important Rules

- ✅ Only modify the `"passes"` field (false → true)
- ✅ Do NOT remove or rewrite task steps
- ✅ Complete tasks in order (some tasks depend on earlier ones)
- ✅ Run tests after each task (if applicable)
- ✅ Make one commit per task (not per step)
- ✅ Log progress in activity.md after each task
