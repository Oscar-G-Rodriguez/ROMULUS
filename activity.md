# ROMULUS Phase A - Activity Log

## Current Status
**Last Updated:** 2025-01-19
**Tasks Completed:** 2 / 19
**Current Task:** data/Implement ETF universe with inception gating

---

## Session Log

### 2025-01-19 - Task Completed: setup/Initialize project structure and dependencies

**Completed Steps:**
- Verified directory structure: romulus/{data,calendar,portfolio,strategy,backtest,config,cli}
- Verified tests/{unit,integration} directories exist
- Verified configs/, data/cache/, outputs/runs/ directories exist
- Verified pyproject.toml with all dependencies (pandas, numpy, yfinance, pydantic, pyarrow, click, pytest, pandas-market-calendars, pyyaml)
- Verified .gitignore (data/cache/, outputs/runs/, __pycache__/, *.pyc, .pytest_cache/, venv/, .venv/)
- Verified README.md with project overview
- Dependencies already installed via venv

**Tests Run:**
```bash
$ python -c "import pandas, numpy, yfinance, pydantic, pyarrow, click, pytest"
# All imports successful!

$ python -c "import pandas_market_calendars; import yaml"
# All imports successful
```

**Status:** ✅ All steps completed, all imports working

**Updated plan.md:** Task "setup/Initialize project structure" marked as passing

---

### 2025-01-19 - Task Completed: setup/Create config files and validation schemas

**Completed Steps:**
- Created configs/universe_default.json with 4 ETFs (SPY, QQQ, IWM, TLT) and inception dates
- Created configs/etf_equal_weight.yaml per PRD Section 7.1
- Created romulus/config/schema.py with pydantic models:
  - BacktestConfig, BacktestSettings, UniverseConfig, StrategyConfig
  - ExecutionConfig, CostConfig, DataConfig, OutputConfig
- Added load_config(path) -> BacktestConfig function
- Updated romulus/config/__init__.py with exports
- Created tests/unit/test_config.py with 9 tests

**Tests Run:**
```bash
$ pytest tests/unit/test_config.py -v
============================= test session starts =============================
collected 9 items

tests/unit/test_config.py::TestConfigLoading::test_config_loads_successfully PASSED
tests/unit/test_config.py::TestConfigLoading::test_config_file_not_found PASSED
tests/unit/test_config.py::TestConfigLoading::test_config_with_defaults PASSED
tests/unit/test_config.py::TestConfigLoading::test_invalid_date_format PASSED
tests/unit/test_config.py::TestUniverseConfig::test_universe_json_valid_format PASSED
tests/unit/test_config.py::TestCostConfig::test_cost_config_defaults PASSED
tests/unit/test_config.py::TestCostConfig::test_cost_config_validation PASSED
tests/unit/test_config.py::TestExecutionConfig::test_execution_config_defaults PASSED
tests/unit/test_config.py::TestExecutionConfig::test_cash_buffer_validation PASSED

============================== 9 passed in 0.17s ==============================
```

**Status:** All 9 tests passed

**Updated plan.md:** Task "setup/Create config files and validation schemas" marked as passing

---

### 2026-01-19 16:38 - Task Attempted: data/Implement ETF universe with inception gating

**Completed Steps:**
- Created romulus/data/universe.py with Universe class, inception-date gating, and lookup helpers
- Updated romulus/data/__init__.py exports
- Added tests/unit/test_universe.py with inception gating coverage

**Tests Run:**
```bash
$ pytest tests/unit/test_universe.py -v
pytest : The term 'pytest' is not recognized as the name of a cmdlet, function, script file, or operable program.
Check the spelling of the name, or if a path was included, verify that the path is correct and try again.

$ python -m pytest tests/unit/test_universe.py -v
C:\Python314\python.exe: No module named pytest
```

**Issues Encountered:**
- pytest is not installed and cannot be fetched due to network restrictions (WinError 10013 when pip tries HTTPS).
- Temporary .tmp subdirectories created during pip attempt could not be removed due to permissions; they remain untracked.

### 2026-01-19 16:43 - Follow-up: pytest install attempt

**Attempted Steps:**
- Tried installing pytest into repo-local target using repo-local temp/cache directories

**Result:**
```bash
$ python -m pip install --no-cache-dir --target .vendor_pytest pytest
... WinError 10013 ...
ERROR: No matching distribution found for pytest
```

**Issues Encountered:**
- Network access still blocked (WinError 10013), so pytest cannot be downloaded.
- Repo-local temp directories created by pip (.pip-tmp) could not be removed due to permissions.

### 2026-01-19 16:56 - Task Completed: data/Implement ETF universe with inception gating

**Completed Steps:**
- Implemented Universe loader with inception-date gating and lookup helpers
- Added unit tests for inception gating and post-inception eligibility
- Ran targeted and full pytest suites

**Tests Run:**
```bash
$ .venv\Scripts\python -m pytest tests/unit/test_universe.py -v
============================= test session starts =============================
platform win32 -- Python 3.14.0, pytest-9.0.2, pluggy-1.6.0 -- C:\Users\Oscar\Documents\GitHub\ROMULUS\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\Oscar\Documents\GitHub\ROMULUS
configfile: pyproject.toml
plugins: cov-7.0.0
collecting ... collected 2 items

tests/unit/test_universe.py::test_inception_gating_tlt PASSED            [ 50%]
tests/unit/test_universe.py::test_all_eligible_after_latest_inception PASSED [100%]

============================== 2 passed in 0.06s ==============================

$ .venv\Scripts\python -m pytest -v
============================= test session starts =============================
platform win32 -- Python 3.14.0, pytest-9.0.2, pluggy-1.6.0 -- C:\Users\Oscar\Documents\GitHub\ROMULUS\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\Oscar\Documents\GitHub\ROMULUS
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.0.0
collecting ... collected 11 items

tests/unit/test_config.py::TestConfigLoading::test_config_loads_successfully PASSED [  9%]
tests/unit/test_config.py::TestConfigLoading::test_config_file_not_found PASSED [ 18%]
tests/unit/test_config.py::TestConfigLoading::test_config_with_defaults PASSED [ 27%]
tests/unit/test_config.py::TestConfigLoading::test_invalid_date_format PASSED [ 36%]
tests/unit/test_config.py::TestUniverseConfig::test_universe_json_valid_format PASSED [ 45%]
tests/unit/test_config.py::TestCostConfig::test_cost_config_defaults PASSED [ 54%]
tests/unit/test_config.py::TestCostConfig::test_cost_config_validation PASSED [ 63%]
tests/unit/test_config.py::TestExecutionConfig::test_execution_config_defaults PASSED [ 72%]
tests/unit/test_config.py::TestExecutionConfig::test_cash_buffer_validation PASSED [ 81%]
tests/unit/test_universe.py::test_inception_gating_tlt PASSED            [ 90%]
tests/unit/test_universe.py::test_all_eligible_after_latest_inception PASSED [100%]

============================= 11 passed in 0.21s ==============================
```

**Status:** ? All steps completed, tests passing

**Updated plan.md:** Task "data/Implement ETF universe with inception gating" marked as passing

### 2026-01-19 17:00 - Task Completed: data/Implement yfinance data ingestion with caching

**Completed Steps:**
- Added romulus/data/ingestion.py with per-ticker caching and checksum tracking
- Added unit tests for cache creation and cache-hit behavior
- Updated romulus/data/__init__.py exports

**Tests Run:**
```bash
$ .venv\Scripts\python -m pytest tests/unit/test_ingestion.py -v
============================= test session starts =============================
platform win32 -- Python 3.14.0, pytest-9.0.2, pluggy-1.6.0 -- C:\Users\Oscar\Documents\GitHub\ROMULUS\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\Oscar\Documents\GitHub\ROMULUS
configfile: pyproject.toml
plugins: cov-7.0.0
collecting ... collected 2 items

tests/unit/test_ingestion.py::test_data_fetch_and_cache PASSED           [ 50%]
tests/unit/test_ingestion.py::test_cache_hit_skip_download PASSED        [100%]

============================== 2 passed in 5.46s ==============================
```

**Status:** ? All steps completed, tests passing

**Updated plan.md:** Task "data/Implement yfinance data ingestion with caching" marked as passing

### 2026-01-19 17:01 - Task Completed: data/Implement Parquet/JSON storage layer

**Completed Steps:**
- Added romulus/data/storage.py with Parquet/JSON helpers and DataFrame hash
- Added tests/unit/test_storage.py with roundtrip and hash coverage
- Updated romulus/data/__init__.py exports

**Tests Run:**
```bash
$ .venv\Scripts\python -m pytest tests/unit/test_storage.py -v
============================= test session starts =============================
platform win32 -- Python 3.14.0, pytest-9.0.2, pluggy-1.6.0 -- C:\Users\Oscar\Documents\GitHub\ROMULUS\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\Oscar\Documents\GitHub\ROMULUS
configfile: pyproject.toml
plugins: cov-7.0.0
collecting ... collected 3 items

tests/unit/test_storage.py::test_parquet_roundtrip PASSED                [ 33%]
tests/unit/test_storage.py::test_json_roundtrip PASSED                   [ 66%]
tests/unit/test_storage.py::test_compute_dataframe_hash_stable PASSED    [100%]

============================== 3 passed in 0.63s ==============================
```

**Status:** ? All steps completed, tests passing

**Updated plan.md:** Task "data/Implement Parquet/JSON storage layer" marked as passing

### 2026-01-19 17:02 - Task Completed: calendar/Generate NYSE trading calendar

**Completed Steps:**
- Added romulus/calendar/trading_days.py with NYSE trading day utilities
- Added tests/unit/test_calendar.py for weekends and holiday exclusion
- Updated romulus/calendar/__init__.py exports

**Tests Run:**
```bash
$ .venv\Scripts\python -m pytest tests/unit/test_calendar.py -v
============================= test session starts =============================
platform win32 -- Python 3.14.0, pytest-9.0.2, pluggy-1.6.0 -- C:\Users\Oscar\Documents\GitHub\ROMULUS\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\Oscar\Documents\GitHub\ROMULUS
configfile: pyproject.toml
plugins: cov-7.0.0
collecting ... collected 2 items

tests/unit/test_calendar.py::test_no_weekends PASSED                     [ 50%]
tests/unit/test_calendar.py::test_no_holidays PASSED                     [100%]

============================== 2 passed in 4.49s ==============================
```

**Status:** ? All steps completed, tests passing

**Updated plan.md:** Task "calendar/Generate NYSE trading calendar" marked as passing

### 2026-01-19 17:03 - Task Completed: calendar/Generate Wed/Fri decision calendar with fill date mapping

**Completed Steps:**
- Added romulus/calendar/decision_days.py with decision date filtering and fill date mapping
- Extended tests/unit/test_calendar.py with decision calendar and fill-date coverage
- Updated romulus/calendar/__init__.py exports

**Tests Run:**
```bash
$ .venv\Scripts\python -m pytest tests/unit/test_calendar.py -v
============================= test session starts =============================
platform win32 -- Python 3.14.0, pytest-9.0.2, pluggy-1.6.0 -- C:\Users\Oscar\Documents\GitHub\ROMULUS\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\Oscar\Documents\GitHub\ROMULUS
configfile: pyproject.toml
plugins: cov-7.0.0
collecting ... collected 5 items

tests/unit/test_calendar.py::test_no_weekends PASSED                     [ 20%]
tests/unit/test_calendar.py::test_no_holidays PASSED                     [ 40%]
tests/unit/test_calendar.py::test_decision_calendar_wed_fri_only PASSED  [ 60%]
tests/unit/test_calendar.py::test_no_holiday_decisions PASSED            [ 80%]
tests/unit/test_calendar.py::test_fill_date_mapping PASSED               [100%]

============================== 5 passed in 1.16s ==============================
```

**Status:** ? All steps completed, tests passing

**Updated plan.md:** Task "calendar/Generate Wed/Fri decision calendar with fill date mapping" marked as passing

### 2026-01-19 17:05 - Task Completed: portfolio/Implement Portfolio account tracker

**Completed Steps:**
- Added romulus/portfolio/account.py with Portfolio class and accounting helpers
- Added tests/unit/test_portfolio.py for cash, fractional shares, and valuation
- Updated romulus/portfolio/__init__.py exports

**Tests Run:**
```bash
$ .venv\Scripts\python -m pytest tests/unit/test_portfolio.py -v
============================= test session starts =============================
platform win32 -- Python 3.14.0, pytest-9.0.2, pluggy-1.6.0 -- C:\Users\Oscar\Documents\GitHub\ROMULUS\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\Oscar\Documents\GitHub\ROMULUS
configfile: pyproject.toml
plugins: cov-7.0.0
collecting ... collected 3 items

tests/unit/test_portfolio.py::test_cash_accounting PASSED                [ 33%]
tests/unit/test_portfolio.py::test_fractional_shares PASSED              [ 66%]
tests/unit/test_portfolio.py::test_market_value_calculation PASSED       [100%]

============================== 3 passed in 0.03s ==============================
```

**Status:** ? All steps completed, tests passing

**Updated plan.md:** Task "portfolio/Implement Portfolio account tracker" marked as passing

### 2026-01-19 17:06 - Task Completed: portfolio/Implement order generation logic

**Completed Steps:**
- Added romulus/portfolio/orders.py with Order dataclass and generate_orders
- Extended tests/unit/test_portfolio.py with min notional and cash buffer checks
- Updated romulus/portfolio/__init__.py exports

**Tests Run:**
```bash
$ .venv\Scripts\python -m pytest tests/unit/test_portfolio.py -v
============================= test session starts =============================
platform win32 -- Python 3.14.0, pytest-9.0.2, pluggy-1.6.0 -- C:\Users\Oscar\Documents\GitHub\ROMULUS\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\Oscar\Documents\GitHub\ROMULUS
configfile: pyproject.toml
plugins: cov-7.0.0
collecting ... collected 5 items

tests/unit/test_portfolio.py::test_cash_accounting PASSED                [ 20%]
tests/unit/test_portfolio.py::test_fractional_shares PASSED              [ 40%]
tests/unit/test_portfolio.py::test_market_value_calculation PASSED       [ 60%]
tests/unit/test_portfolio.py::test_order_generation_respects_min_notional PASSED [ 80%]
tests/unit/test_portfolio.py::test_order_generation_respects_cash_buffer PASSED [100%]

============================== 5 passed in 0.03s ==============================
```

**Status:** ? All steps completed, tests passing

**Updated plan.md:** Task "portfolio/Implement order generation logic" marked as passing

### 2026-01-19 17:08 - Task Completed: portfolio/Implement fill simulation with slippage

**Completed Steps:**
- Added romulus/portfolio/fills.py with Fill dataclass and simulate_fills
- Extended tests/unit/test_portfolio.py with slippage and commission coverage
- Updated romulus/portfolio/__init__.py exports

**Tests Run:**
```bash
$ .venv\Scripts\python -m pytest tests/unit/test_portfolio.py -v
============================= test session starts =============================
platform win32 -- Python 3.14.0, pytest-9.0.2, pluggy-1.6.0 -- C:\Users\Oscar\Documents\GitHub\ROMULUS\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\Oscar\Documents\GitHub\ROMULUS
configfile: pyproject.toml
plugins: cov-7.0.0
collecting ... collected 7 items

tests/unit/test_portfolio.py::test_cash_accounting PASSED                [ 14%]
tests/unit/test_portfolio.py::test_fractional_shares PASSED              [ 28%]
tests/unit/test_portfolio.py::test_market_value_calculation PASSED       [ 42%]
tests/unit/test_portfolio.py::test_order_generation_respects_min_notional PASSED [ 57%]
tests/unit/test_portfolio.py::test_order_generation_respects_cash_buffer PASSED [ 71%]
tests/unit/test_portfolio.py::test_slippage_applied_correctly PASSED     [ 85%]
tests/unit/test_portfolio.py::test_commission_applied PASSED             [100%]

============================== 7 passed in 0.03s ==============================
```

**Status:** ? All steps completed, tests passing

**Updated plan.md:** Task "portfolio/Implement fill simulation with slippage" marked as passing

### 2026-01-19 17:09 - Task Completed: strategy/Define base strategy interface

**Completed Steps:**
- Added romulus/strategy/base.py with BaseStrategy ABC
- Updated romulus/strategy/__init__.py exports

**Tests Run:**
- None (abstract class only)

**Status:** ? All steps completed

**Updated plan.md:** Task "strategy/Define base strategy interface" marked as passing

### 2026-01-19 17:10 - Task Completed: strategy/Implement equal-weight baseline strategy

**Completed Steps:**
- Added romulus/strategy/equal_weight.py with EqualWeightStrategy
- Added tests/unit/test_strategy.py for weight validation
- Updated romulus/strategy/__init__.py exports

**Tests Run:**
```bash
$ .venv\Scripts\python -m pytest tests/unit/test_strategy.py -v
============================= test session starts =============================
platform win32 -- Python 3.14.0, pytest-9.0.2, pluggy-1.6.0 -- C:\Users\Oscar\Documents\GitHub\ROMULUS\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\Oscar\Documents\GitHub\ROMULUS
configfile: pyproject.toml
plugins: cov-7.0.0
collecting ... collected 3 items

tests/unit/test_strategy.py::test_equal_weight_sums_to_one PASSED        [ 33%]
tests/unit/test_strategy.py::test_equal_weight_excludes_ineligible PASSED [ 66%]
tests/unit/test_strategy.py::test_equal_weight_handles_single_ticker PASSED [100%]

============================== 3 passed in 0.37s ==============================
```

**Status:** ? All steps completed, tests passing

**Updated plan.md:** Task "strategy/Implement equal-weight baseline strategy" marked as passing

### 2026-01-19 17:11 - Task Completed: backtest/Implement cost model

**Completed Steps:**
- Added romulus/backtest/costs.py with slippage and commission helpers
- Added tests/unit/test_backtest.py with cost validation
- Updated romulus/backtest/__init__.py exports

**Tests Run:**
```bash
$ .venv\Scripts\python -m pytest tests/unit/test_backtest.py -v
============================= test session starts =============================
platform win32 -- Python 3.14.0, pytest-9.0.2, pluggy-1.6.0 -- C:\Users\Oscar\Documents\GitHub\ROMULUS\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\Oscar\Documents\GitHub\ROMULUS
configfile: pyproject.toml
plugins: cov-7.0.0
collecting ... collected 2 items

tests/unit/test_backtest.py::test_slippage_calculation PASSED            [ 50%]
tests/unit/test_backtest.py::test_commission_calculation PASSED          [100%]

============================== 2 passed in 0.03s ==============================
```

**Status:** ? All steps completed, tests passing

**Updated plan.md:** Task "backtest/Implement cost model" marked as passing

### 2026-01-19 17:12 - Task Completed: backtest/Implement performance metrics

**Completed Steps:**
- Added romulus/backtest/metrics.py with performance metric calculations
- Extended tests/unit/test_backtest.py with metrics validation
- Updated romulus/backtest/__init__.py exports

**Tests Run:**
```bash
$ .venv\Scripts\python -m pytest tests/unit/test_backtest.py -v
============================= test session starts =============================
platform win32 -- Python 3.14.0, pytest-9.0.2, pluggy-1.6.0 -- C:\Users\Oscar\Documents\GitHub\ROMULUS\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\Oscar\Documents\GitHub\ROMULUS
configfile: pyproject.toml
plugins: cov-7.0.0
collecting ... collected 3 items

tests/unit/test_backtest.py::test_slippage_calculation PASSED            [ 33%]
tests/unit/test_backtest.py::test_commission_calculation PASSED          [ 66%]
tests/unit/test_backtest.py::test_metrics_calculation PASSED             [100%]

============================== 3 passed in 0.40s ==============================
```

**Status:** ? All steps completed, tests passing

**Updated plan.md:** Task "backtest/Implement performance metrics" marked as passing

### 2026-01-19 17:17 - Task Completed: backtest/Implement main backtest engine

**Completed Steps:**
- Added romulus/backtest/engine.py with BacktestEngine orchestration
- Implemented output writing (orders, fills, positions, portfolio value, metrics, manifest)
- Added tests/integration/test_end_to_end.py for end-to-end run
- Updated romulus/backtest/__init__.py exports

**Tests Run:**
```bash
$ .venv\Scripts\python -m pytest tests/integration/test_end_to_end.py -v
============================= test session starts =============================
platform win32 -- Python 3.14.0, pytest-9.0.2, pluggy-1.6.0 -- C:\Users\Oscar\Documents\GitHub\ROMULUS\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\Oscar\Documents\GitHub\ROMULUS
configfile: pyproject.toml
plugins: cov-7.0.0
collecting ... collected 1 item

tests/integration/test_end_to_end.py::test_full_backtest_completes PASSED [100%]

============================== 1 passed in 1.25s ==============================
```

**Status:** ? All steps completed, tests passing

**Updated plan.md:** Task "backtest/Implement main backtest engine" marked as passing

### 2026-01-19 17:19 - Task Completed: backtest/Add determinism and lookahead tests

**Completed Steps:**
- Added tests/integration/test_backtest_determinism.py with determinism, lookahead, and cost checks

**Tests Run:**
```bash
$ .venv\Scripts\python -m pytest tests/integration/test_backtest_determinism.py -v
============================= test session starts =============================
platform win32 -- Python 3.14.0, pytest-9.0.2, pluggy-1.6.0 -- C:\Users\Oscar\Documents\GitHub\ROMULUS\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\Oscar\Documents\GitHub\ROMULUS
configfile: pyproject.toml
plugins: cov-7.0.0
collecting ... collected 3 items

tests/integration/test_backtest_determinism.py::test_deterministic_runs PASSED [ 33%]
tests/integration/test_backtest_determinism.py::test_no_lookahead PASSED [ 66%]
tests/integration/test_backtest_determinism.py::test_costs_applied PASSED [100%]

============================== 3 passed in 2.45s ==============================
```

**Status:** ? All steps completed, tests passing

**Updated plan.md:** Task "backtest/Add determinism and lookahead tests" marked as passing

### 2026-01-19 17:21 - Task Completed: cli/Implement CLI interface with click

**Completed Steps:**
- Added romulus/cli/main.py with click CLI (group + run command)
- Updated romulus/cli/__init__.py exports

**Tests Run:**
```bash
$ .venv\Scripts\python -m romulus.cli.main run --config configs/etf_equal_weight.yaml --help
<frozen runpy>:128: RuntimeWarning: 'romulus.cli.main' found in sys.modules after import of package 'romulus.cli', but prior to execution of 'romulus.cli.main'; this may result in unpredictable behaviour
Usage: python -m romulus.cli.main run [OPTIONS]

  Run a backtest from a configuration file.

Options:
  --config TEXT  Path to YAML config file  [required]
  --start TEXT   Override start date (YYYY-MM-DD)
  --end TEXT     Override end date (YYYY-MM-DD)
  --help         Show this message and exit.
```

**Status:** ? All steps completed

**Updated plan.md:** Task "cli/Implement CLI interface with click" marked as passing
