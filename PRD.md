# ROMULUS Phase A - Product Requirements Document

**Project Name**: ROMULUS Phase A  
**Version**: 1.0  
**Created**: January 19, 2025  
**Author**: Oscar (via Claude)  

---

## 1. Executive Summary

ROMULUS Phase A is a deterministic ETF backtesting and portfolio management engine designed to eliminate survivorship bias and provide a robust foundation for quantitative strategy research. The system operates on daily bars with Wednesday/Friday rebalancing decisions and enforces strict point-in-time data integrity.

**Key Objectives**:
- Build a survivorship-bias-free ETF backtesting framework
- Enforce strict as-of date rules to prevent lookahead bias
- Provide deterministic, auditable backtest results
- Create a modular foundation for multiple strategy implementations

---

## 2. Product Vision & Goals

### 2.1 Vision
Create a professional-grade backtesting system that researchers and traders can trust for strategy development, with built-in guardrails against common biases that plague amateur backtesting systems.

### 2.2 Core Goals
1. **Eliminate Survivorship Bias**: Only include ETFs that existed at each point in time
2. **Prevent Lookahead**: Strict separation between decision time and fill time
3. **Ensure Determinism**: Same inputs always produce identical outputs
4. **Enable Auditability**: Every backtest produces complete records with checksums
5. **Support Modularity**: Easy to add new strategies without changing the engine

---

## 3. Target Users

**Primary User**: Quantitative researchers and algorithmic traders who:
- Need reliable backtesting infrastructure
- Understand the importance of avoiding statistical biases
- Want to test multiple strategies systematically
- Require audit trails for compliance or research publication

**Technical Level**: Intermediate to advanced Python users comfortable with command-line tools and data analysis.

---

## 4. User Stories

### Core Functionality

**As a quant researcher**, I want to:
- Run backtests on ETF strategies without survivorship bias
- Know that my backtest results are reproducible
- See detailed trade logs and portfolio history
- Trust that my signals aren't using future information

**As a strategy developer**, I want to:
- Plug in new strategy logic without rewriting the engine
- Test strategies across different time periods easily
- Compare multiple strategies on the same data
- Understand exactly when decisions are made vs when fills occur

**As a compliance officer**, I want to:
- Verify backtest results are deterministic
- Audit the complete decision trail
- Ensure no lookahead bias exists
- Validate data integrity with checksums

---

## 5. Core Features & Requirements

### 5.1 Data Management

**Universe Management**:
- Load ETF universe from JSON configuration
- Filter eligible tickers by inception date (point-in-time)
- Support for adding/removing ETFs via config updates

**Data Ingestion**:
- Fetch daily OHLCV data from Yahoo Finance (yfinance)
- Cache data locally in Parquet format
- Support split and dividend adjustments
- Compute and store data checksums for verification

**Requirements**:
- ✅ No data available before ETF inception date
- ✅ Cache hit logic to avoid redundant downloads
- ✅ MD5 checksums for all cached data files

### 5.2 Calendar Management

**Trading Calendar**:
- Generate NYSE trading days (exclude weekends/holidays)
- Use `pandas_market_calendars` for accuracy

**Decision Calendar**:
- Filter to Wednesday and Friday only
- Map each decision date to next trading day (fill date)

**Requirements**:
- ✅ No decisions on non-trading days
- ✅ No decisions on market holidays
- ✅ Clear separation between decision_date and fill_date

### 5.3 Portfolio Management

**Account Tracking**:
- Track cash balance
- Track positions (ticker → shares, supports fractional)
- Compute market value and total portfolio value

**Order Generation**:
- Compute target weights from strategy
- Calculate shares to trade based on prices and cash
- Respect minimum order notional ($1)
- Maintain cash buffer (1% default)

**Fill Simulation**:
- Apply slippage (5 bps default)
- Apply commission ($0 default)
- Update cash and positions atomically

**Requirements**:
- ✅ Cash accounting must be exact (no rounding errors)
- ✅ Support fractional shares
- ✅ Orders below minimum notional are filtered out
- ✅ All fills include slippage and commission costs

### 5.4 Strategy Framework

**Base Strategy Interface**:
```python
class BaseStrategy:
    def compute_target_weights(
        self,
        as_of_date: date,
        eligible_tickers: List[str],
        prices: pd.DataFrame,
        positions: Dict[str, float]
    ) -> Dict[str, float]:
        """Returns {ticker: weight} where sum(weights) <= 1.0"""
```

**Equal-Weight Baseline**:
- Allocate 1/N to each eligible ticker
- Rebalance to equal weights on each decision date
- Serves as sanity check for engine correctness

**Requirements**:
- ✅ Strategies receive only as-of data
- ✅ Weights must sum to ≤ 1.0
- ✅ Strategies only allocate to eligible tickers

### 5.5 Backtest Engine

**Orchestration**:
1. Load universe and validate inception dates
2. Fetch/cache price data
3. Generate decision calendar
4. Initialize portfolio with starting cash
5. Loop through decision dates:
   - Get eligible tickers (as-of)
   - Get decision prices (close)
   - Compute target weights (strategy)
   - Generate orders
   - Get fill prices (next open)
   - Simulate fills
   - Apply costs
   - Update portfolio
   - Record state
6. Compute final metrics
7. Save outputs with manifest

**Execution Model**:
- **Decision time**: Wednesday/Friday at market close
- **Decision data**: Close prices on decision date
- **Fill time**: Next trading day at open
- **Fill price**: Open price + slippage

**Requirements**:
- ✅ Strict chronological order enforcement
- ✅ No lookahead (decision uses only past data)
- ✅ Deterministic given same config + data
- ✅ Complete audit trail in outputs

### 5.6 Cost Modeling

**Commission**:
- Default: $0 (modern brokers)
- Configurable per config file

**Slippage**:
- Default: 5 bps (0.05%)
- Applied as: `fill_price = price * (1 + slippage_bps/10000 * sign(shares))`
- Buy orders: pay slippage
- Sell orders: pay slippage

**Requirements**:
- ✅ Costs appear in Fill records
- ✅ Costs reduce cash balance
- ✅ Net performance includes all costs

### 5.7 Performance Metrics

**Calculated Metrics**:
- Total return (%)
- CAGR (annualized return)
- Sharpe ratio (252 trading days/year)
- Maximum drawdown (%)
- Final portfolio value

**Requirements**:
- ✅ Use 252 trading days for annualization
- ✅ Metrics saved to JSON
- ✅ Metrics printed to console on completion

### 5.8 Output Management

**Run Directory Structure**:
```
outputs/runs/{run_id}/
├── manifest.json              # Config hash, checksums, metadata
├── orders.parquet             # All orders generated
├── fills.parquet              # All fills executed
├── positions.parquet          # Daily positions by ticker
├── portfolio_value.parquet    # Daily total value
└── metrics.json               # Performance metrics
```

**Manifest Contents**:
- run_id (timestamp + hash prefix)
- config_hash (determinism verification)
- data_checksums (per ticker)
- status (completed/failed)
- execution_time_seconds
- created_at (ISO timestamp)

**Requirements**:
- ✅ All runs stored in separate directories
- ✅ Filenames are consistent
- ✅ Parquet files use standard schema
- ✅ Manifest includes checksums for reproducibility

---

## 6. Technical Architecture

### 6.1 Technology Stack

**Core**:
- Python 3.11+
- pandas (data manipulation)
- numpy (numerical operations)
- pyarrow (Parquet I/O)

**Data**:
- yfinance (Yahoo Finance API wrapper)
- pandas_market_calendars (NYSE calendar)

**Config & CLI**:
- pydantic (config validation)
- click (CLI framework)
- PyYAML (config files)

**Testing**:
- pytest (test framework)
- pytest-cov (coverage reporting)

### 6.2 Module Structure

```
romulus/
├── data/
│   ├── ingestion.py      # yfinance fetcher + caching
│   ├── universe.py       # ETF universe + inception gating
│   └── storage.py        # Parquet/JSON I/O
├── calendar/
│   ├── trading_days.py   # NYSE calendar
│   └── decision_days.py  # Wed/Fri filter + fill date mapping
├── portfolio/
│   ├── account.py        # Portfolio state tracker
│   ├── orders.py         # Order generation
│   └── fills.py          # Fill simulation
├── strategy/
│   ├── base.py           # BaseStrategy interface
│   └── equal_weight.py   # Equal-weight baseline
├── backtest/
│   ├── engine.py         # Main orchestrator
│   ├── costs.py          # Commission + slippage
│   └── metrics.py        # Performance calculation
├── config/
│   └── schema.py         # Pydantic models
└── cli/
    └── main.py           # Click CLI
```

### 6.3 Data Models

**Order**:
```python
@dataclass
class Order:
    ticker: str
    shares: float          # +buy / -sell
    decision_date: date
    target_weight: float
```

**Fill**:
```python
@dataclass
class Fill:
    ticker: str
    shares: float
    fill_price: float
    fill_date: date
    commission: float
    slippage_cost: float
    gross_value: float
    net_cost: float
```

**Portfolio State**:
```python
@dataclass
class Portfolio:
    cash: float
    positions: Dict[str, float]  # {ticker: shares}
```

---

## 7. Configuration

### 7.1 Backtest Config (YAML)

```yaml
backtest:
  name: "ETF Equal Weight Baseline"
  start_date: "2010-01-01"
  end_date: "2024-12-31"
  initial_cash: 10000.0

universe:
  source: "configs/universe_default.json"

strategy:
  type: "equal_weight"

execution:
  decision_days: ["wednesday", "friday"]
  decision_time: "close"
  fill_time: "open"
  fractional_shares: true
  min_order_notional: 1.0
  cash_buffer_pct: 0.01

costs:
  commission_per_trade: 0.0
  slippage_bps: 5.0

data:
  source: "yfinance"
  cache_dir: "data/cache"
  adjustment: "split_and_dividend"

output:
  run_dir: "outputs/runs"
```

### 7.2 Universe Config (JSON)

```json
{
  "etfs": [
    {
      "ticker": "SPY",
      "name": "SPDR S&P 500 ETF Trust",
      "inception_date": "1993-01-22"
    },
    {
      "ticker": "QQQ",
      "name": "Invesco QQQ Trust",
      "inception_date": "1999-03-10"
    },
    {
      "ticker": "IWM",
      "name": "iShares Russell 2000 ETF",
      "inception_date": "2000-05-22"
    },
    {
      "ticker": "TLT",
      "name": "iShares 20+ Year Treasury Bond ETF",
      "inception_date": "2002-07-26"
    }
  ]
}
```

---

## 8. Testing Strategy

### 8.1 Unit Tests

**test_universe.py**:
- Inception gating works correctly
- All tickers eligible after latest inception
- Inception dates loaded correctly

**test_calendar.py**:
- Decision calendar only contains Wed/Fri
- No holidays in decision calendar
- Fill date mapping works correctly

**test_portfolio.py**:
- Cash accounting is exact
- Fractional shares supported
- Market value calculation correct

**test_strategy.py**:
- Equal weight sums to 1.0
- Only eligible tickers receive allocation

### 8.2 Integration Tests

**test_backtest_determinism.py**:
- Same config produces identical results
- Config hash matches on identical configs
- Output checksums validate

**test_end_to_end.py**:
- Full backtest completes without errors
- Orders generated for each decision date
- Fills occur on correct dates (next trading day)
- Costs applied to all fills
- Final portfolio value > 0

**test_no_lookahead.py**:
- Decision on date D uses only prices ≤ D
- Fills occur on date D+1 (next trading day)
- No future data leaks into strategy

### 8.3 Coverage Target

- Minimum 80% code coverage
- 100% coverage on critical paths (portfolio accounting, order generation)

---

## 9. Development Phases

### Phase 1: Foundation (Setup + Data)
**Tasks**:
- Project structure setup
- Config schema implementation
- Universe loading + inception gating
- yfinance data ingestion + caching
- Parquet/JSON storage layer

**Definition of Done**:
- ✅ Config files load and validate
- ✅ Universe filters by inception date correctly
- ✅ Data fetches and caches to Parquet
- ✅ Unit tests pass

### Phase 2: Calendar System
**Tasks**:
- NYSE trading calendar generation
- Wed/Fri decision calendar
- Fill date mapping

**Definition of Done**:
- ✅ Decision calendar excludes holidays
- ✅ Only Wed/Fri in decision dates
- ✅ Each decision date maps to next trading day
- ✅ Unit tests pass

### Phase 3: Portfolio & Orders
**Tasks**:
- Portfolio account tracker
- Order generation logic
- Fill simulation with costs

**Definition of Done**:
- ✅ Cash accounting exact to penny
- ✅ Fractional shares supported
- ✅ Min notional filter works
- ✅ Slippage applied correctly
- ✅ Unit tests pass

### Phase 4: Strategy Framework
**Tasks**:
- BaseStrategy interface
- Equal-weight implementation

**Definition of Done**:
- ✅ Strategy interface documented
- ✅ Equal-weight produces valid weights
- ✅ Unit tests pass

### Phase 5: Backtest Engine
**Tasks**:
- Main engine orchestration
- Cost model integration
- Metrics calculation
- Output generation + manifest

**Definition of Done**:
- ✅ Full backtest runs end-to-end
- ✅ Determinism tests pass
- ✅ Lookahead tests pass
- ✅ All outputs generated with checksums
- ✅ Integration tests pass

### Phase 6: CLI & Documentation
**Tasks**:
- Click CLI implementation
- README documentation
- Example run verification

**Definition of Done**:
- ✅ `romulus run --config ...` works
- ✅ Help text clear and complete
- ✅ README includes installation + usage
- ✅ Example run produces expected outputs

---

## 10. Success Criteria

**The system is complete when**:

1. ✅ A backtest can run from CLI with a single command
2. ✅ Running the same config twice produces identical results
3. ✅ All unit tests pass (80%+ coverage)
4. ✅ All integration tests pass
5. ✅ Inception gating prevents survivorship bias
6. ✅ No lookahead bias (verified by tests)
7. ✅ Outputs include complete audit trail
8. ✅ Equal-weight baseline produces reasonable performance metrics
9. ✅ Documentation allows a new user to run a backtest

---

## 11. Known Limitations & Future Work

### Current Limitations
- **ETFs only** (no stocks, futures, options)
- **Daily bars only** (no intraday)
- **Wed/Fri only** (no daily or monthly rebalancing yet)
- **Simple slippage model** (fixed bps, no volume-based)
- **No transaction costs beyond slippage** (no market impact)
- **Single strategy per run** (no multi-strategy comparison)

### Future Enhancements (Phase B+)
- Multiple rebalancing frequencies (daily, weekly, monthly)
- Volume-based slippage models
- Market impact models
- Multi-strategy comparison framework
- Live paper trading integration (Alpaca API)
- Web dashboard for results visualization
- Additional asset classes (stocks, bonds, futures)
- Optimization framework for strategy parameters

---

## 12. References & Resources

**Data Sources**:
- Yahoo Finance: https://finance.yahoo.com
- yfinance documentation: https://github.com/ranaroussi/yfinance

**Market Calendars**:
- pandas_market_calendars: https://github.com/rsheftel/pandas_market_calendars

**ETF Information**:
- ETF.com: https://www.etf.com
- Morningstar: https://www.morningstar.com

**Backtesting Best Practices**:
- "Advances in Financial Machine Learning" by Marcos López de Prado
- "Quantitative Trading" by Ernie Chan

---

## Appendix A: Example Output

### Console Output
```
ROMULUS Backtest Engine
=======================
Config: ETF Equal Weight Baseline
Period: 2010-01-01 to 2024-12-31
Universe: 4 ETFs (SPY, QQQ, IWM, TLT)

Fetching data... ✓
Generating calendar... ✓ (390 decision dates)
Running backtest... ✓

Results
-------
Initial Value:  $10,000.00
Final Value:    $45,234.12
Total Return:   352.34%
CAGR:           10.8%
Sharpe Ratio:   0.87
Max Drawdown:   -28.4%

Outputs saved to: outputs/runs/20250119_143022_a3f9c2/
```

### Manifest JSON
```json
{
  "run_id": "20250119_143022_a3f9c2",
  "config_hash": "a3f9c2e1b4d5c8f7a9e2d4c6b8f1a3e5",
  "status": "completed",
  "start_date": "2010-01-01",
  "end_date": "2024-12-31",
  "universe": ["SPY", "QQQ", "IWM", "TLT"],
  "strategy": "equal_weight",
  "data_checksums": {
    "SPY": "e4b2a1c3d5f7e9a2b4c6d8e1f3a5b7c9",
    "QQQ": "f5c3d2e4f6a8b1c3d5e7f9a2b4c6d8e1",
    "IWM": "a1b2c3d4e5f6a7b8c9d1e2f3a4b5c6d7",
    "TLT": "c2d3e4f5a6b7c8d9e1f2a3b4c5d6e7f8"
  },
  "execution_time_seconds": 12.4,
  "created_at": "2025-01-19T14:30:22Z"
}
```

---

**Document Version History**:
- v1.0 (2025-01-19): Initial PRD for Phase A
