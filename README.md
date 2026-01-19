# ROMULUS Phase A

**Deterministic ETF Backtesting Engine**

ROMULUS is a professional-grade backtesting system designed to eliminate survivorship bias and provide robust, auditable backtest results for quantitative strategy research.

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

## Project Status

Phase A - Under Development

## License

MIT
