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
