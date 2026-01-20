# ROMULUS Phase A

**Deterministic ETF Backtesting Engine**

ROMULUS is a professional-grade backtesting system designed to eliminate survivorship bias and provide robust, auditable backtest results for quantitative strategy research. It operates on daily bars with Wednesday/Friday decision points, strict point-in-time data handling, and deterministic outputs.

## Features

- **Survivorship-Bias Free**: Only includes ETFs that existed at each point in time
- **No Lookahead Bias**: Strict separation between decision time and fill time
- **Deterministic**: Same inputs always produce identical outputs
- **Auditable**: Every backtest produces complete records with checksums
- **Modular**: Easy to add new strategies without changing the engine

## Installation

```bash
git clone <repository-url>
cd ROMULUS
pip install -e ".[dev]"
```

## Quick Start

```bash
python -m romulus.cli.main run --config configs/etf_equal_weight.yaml
```

Quickstart with defaults (CWD-aware resolver):

```bash
romulus run
```

Override config resolution:

- Set `ROMULUS_CONFIG` to a config file path
- Or pass `--config path/to/config.yaml`

Pre-run edit wizard:

- By default, `romulus run` prompts to edit key fields before running
- Use `--no-edit` to skip the wizard

## Configuration

ROMULUS is configured via YAML. Key sections include:

- `backtest`: name, start/end dates, initial cash
- `universe`: path to ETF universe JSON
- `strategy`: strategy type and optional parameters
- `execution`: decision days, fill/decision times, min notional, cash buffer
- `costs`: commission and slippage
- `data`: data source and cache directory
- `output`: output run directory

Example snippet:

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
```

## Output Structure

Each run is saved to `outputs/runs/{run_id}/`:

```
outputs/runs/{run_id}/
+-- manifest.json
+-- orders.parquet
+-- fills.parquet
+-- positions.parquet
+-- portfolio_value.parquet
+-- metrics.json
```

## Adding New Strategies

Implement the base interface and register it with the engine:

```python
from datetime import date
from typing import Dict, List
import pandas as pd

from romulus.strategy.base import BaseStrategy

class MyStrategy(BaseStrategy):
    def compute_target_weights(
        self,
        as_of_date: date,
        eligible_tickers: List[str],
        prices: pd.DataFrame,
        positions: Dict[str, float],
    ) -> Dict[str, float]:
        return {ticker: 1.0 / len(eligible_tickers) for ticker in eligible_tickers}
```

## Testing

```bash
pytest tests/ -v
```

## Development

- Keep functions small and well-documented
- Add unit tests for new logic
- Run tests before committing changes

## License

MIT
