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
