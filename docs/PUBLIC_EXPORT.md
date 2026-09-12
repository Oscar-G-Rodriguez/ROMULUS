# Clean Public Portfolio Export

The tracked `sources_private/` directory contains private books and papers. It must not be deleted, moved, published, or rewritten as part of repository cleanup.

Create a new history-free public repository and copy only an explicit allowlist:

- `romulus/`
- `tests/`
- `configs/`
- `.github/`
- `scripts/offline_demo.py`
- `README.md`, `VALIDATION_REPORT.md`, `CHANGELOG.md`, `LICENSE`, and permitted files under `docs/`
- `pyproject.toml`, `uv.lock`, `.python-version`, and `.gitignore`

Exclude `sources_private/`, `.git/`, caches, downloaded market data, generated outputs, virtual environments, temporary directories, and unreviewed binaries. Scan the staged export for secrets and private filenames, validate dependency and documentation licenses, run the locked offline tests, and inspect the final staged file list before publishing.

The public narrative must describe a personal research/backtesting project. It must not imply competition participation, live trading, real capital, profitability, or independent validation.
