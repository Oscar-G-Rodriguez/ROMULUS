"""Command line interface for ROMULUS."""

from __future__ import annotations

import json
import os
import shlex
from pathlib import Path
from typing import Mapping

import click

from romulus import __version__
from romulus.backtest.engine import BacktestEngine
from romulus.backtest.suite import SuiteRunner
from romulus.config.schema import BacktestConfig, SuiteConfig, load_config, load_suite_config

_REPL_DEFAULT_CONFIG: Path | None = None


def set_repl_default_config(path: Path | None) -> None:
    global _REPL_DEFAULT_CONFIG
    _REPL_DEFAULT_CONFIG = path


def get_repl_default_config() -> Path | None:
    return _REPL_DEFAULT_CONFIG


def repl() -> None:
    click.echo("ROMULUS interactive. Type 'help' to list commands. Type 'exit' to quit.")
    while True:
        try:
            line = input("romulus> ").strip()
        except (EOFError, KeyboardInterrupt):
            click.echo("")
            break

        if not line:
            continue

        if line in ("exit", "quit", "q"):
            break

        if line.startswith("use"):
            parts = line.split(maxsplit=1)
            if len(parts) == 1:
                current = get_repl_default_config()
                if current is None:
                    click.echo("No session config set. Use: use path/to/config.yaml")
                else:
                    click.echo(f"Session config: {format_path_for_display(current)}")
                continue
            candidate = Path(parts[1])
            if not candidate.exists():
                click.echo(f"Config not found: {parts[1]}")
                continue
            set_repl_default_config(candidate)
            click.echo(f"Session config set to: {format_path_for_display(candidate)}")
            continue

        if line in ("help", "?"):
            try:
                cli.main(args=["--help"], prog_name="romulus", standalone_mode=False)
            except SystemExit:
                pass
            continue

        try:
            args = shlex.split(line)
            cli.main(args=args, prog_name="romulus", standalone_mode=False)
        except SystemExit:
            # Click raises SystemExit for normal command completion; ignore.
            pass
        except Exception as e:
            click.echo(f"Error: {e}")


@click.group(
    invoke_without_command=True,
    help="ROMULUS Phase B: strategy suite backtesting and audit-ready analytics.",
    epilog=(
        "Examples:\n"
        "  romulus init\n"
        "  romulus config validate --config configs/default.yaml\n"
        "  romulus run\n"
        "  romulus suite\n"
        "  romulus runs list\n"
    ),
)
@click.version_option(__version__, "--version", message="ROMULUS version %(version)s")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """ROMULUS command line interface."""
    # If user runs just `romulus` with no subcommand, start interactive mode.
    if ctx.invoked_subcommand is None:
        repl()


def resolve_default_config_path(
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    candidates: list[Path] | None = None,
) -> Path | None:
    """Resolve default config path based on environment and CWD."""
    if cwd is None:
        cwd = Path.cwd()
    if env is None:
        env = os.environ

    env_path = env.get("ROMULUS_CONFIG")
    if env_path:
        candidate = Path(env_path)
        if candidate.exists():
            return candidate

    if candidates is None:
        candidates = [Path("configs/etf_equal_weight.yaml"), Path("configs/default.yaml")]

    for candidate in candidates:
        resolved = cwd / candidate
        if resolved.exists():
            return resolved

    return None


def resolve_config_path(config_path: str | None, candidates: list[Path]) -> Path:
    if config_path:
        return Path(config_path)

    repl_default = get_repl_default_config()
    if repl_default and repl_default.exists():
        return repl_default

    resolved = resolve_default_config_path(candidates=candidates)
    if resolved:
        return resolved

    return prompt_for_config_path()


def prompt_for_config_path() -> Path:
    """Prompt the user for a config path until a valid file is provided."""
    while True:
        config_path = click.prompt(
            "Config path",
            type=click.Path(exists=True, dir_okay=False, path_type=Path),
        )
        if config_path.exists():
            return config_path


def format_path_for_display(path: Path, cwd: Path | None = None) -> str:
    """Format a path for display without forcing absolute paths."""
    if cwd is None:
        cwd = Path.cwd()
    try:
        return os.path.relpath(path, cwd)
    except ValueError:
        return str(path)


def print_effective_settings(config: BacktestConfig) -> None:
    """Print effective settings that will be used for the run."""
    click.echo("Effective settings:")
    click.echo(f"  backtest.start_date: {config.backtest.start_date}")
    click.echo(f"  backtest.end_date: {config.backtest.end_date}")
    click.echo(f"  backtest.initial_cash: {config.backtest.initial_cash}")
    click.echo(f"  execution.decision_days: {', '.join(config.execution.decision_days)}")
    click.echo(f"  execution.decision_time: {config.execution.decision_time}")
    click.echo(f"  execution.fill_time: {config.execution.fill_time}")
    click.echo(f"  execution.fractional_shares: {config.execution.fractional_shares}")
    click.echo(f"  execution.min_order_notional: {config.execution.min_order_notional}")
    click.echo(f"  execution.cash_buffer_pct: {config.execution.cash_buffer_pct}")
    click.echo(f"  costs.commission_per_trade: {config.costs.commission_per_trade}")
    click.echo(f"  costs.slippage_bps: {config.costs.slippage_bps}")


def print_suite_effective_settings(config: SuiteConfig) -> None:
    click.echo("Effective settings:")
    click.echo(f"  backtest.start_date: {config.backtest.start_date}")
    click.echo(f"  backtest.end_date: {config.backtest.end_date}")
    click.echo(f"  backtest.initial_cash: {config.backtest.initial_cash}")
    click.echo(f"  warmup.enabled: {config.warmup.enabled}")
    click.echo(f"  warmup.start_date: {config.warmup.start_date}")
    click.echo(f"  warmup.rebase: {config.warmup.rebase}")
    click.echo(f"  leaderboard.window: {config.leaderboard.window}")
    click.echo(f"  leaderboard.dd_limit: {config.leaderboard.dd_limit}")
    click.echo(f"  leaderboard.turnover_limit: {config.leaderboard.turnover_limit}")
    click.echo(f"  meta.enabled: {config.meta.enabled}")
    click.echo(f"  meta.min_periods_before_selection: {config.meta.min_periods_before_selection}")
    click.echo(f"  meta.baseline_strategy: {config.meta.baseline_strategy}")
    click.echo("  strategies:")
    for strategy in config.strategies:
        click.echo(f"    - {strategy.name}: {strategy.type}")


def _parse_csv_list(value: str) -> list[str]:
    return [item.strip().lower() for item in value.split(",") if item.strip()]


def edit_config_interactively(config: BacktestConfig) -> None:
    """Allow the user to edit key settings before running."""
    click.echo("Edit settings before run (press Enter to keep default).")

    config.backtest.start_date = click.prompt(
        "Start date (YYYY-MM-DD)",
        default=config.backtest.start_date,
        show_default=True,
    )
    config.backtest.end_date = click.prompt(
        "End date (YYYY-MM-DD)",
        default=config.backtest.end_date,
        show_default=True,
    )
    config.backtest.initial_cash = click.prompt(
        "Initial cash",
        default=config.backtest.initial_cash,
        type=float,
        show_default=True,
    )

    decision_days_default = ",".join(config.execution.decision_days)
    decision_days_input = click.prompt(
        "Decision days (comma-separated)",
        default=decision_days_default,
        show_default=True,
    )
    config.execution.decision_days = _parse_csv_list(decision_days_input)

    config.execution.decision_time = click.prompt(
        "Decision time (open/close)",
        default=config.execution.decision_time,
        show_default=True,
    )
    config.execution.fill_time = click.prompt(
        "Fill time (open/close)",
        default=config.execution.fill_time,
        show_default=True,
    )
    config.execution.fractional_shares = click.prompt(
        "Fractional shares",
        default=config.execution.fractional_shares,
        type=bool,
        show_default=True,
    )
    config.execution.min_order_notional = click.prompt(
        "Minimum order notional",
        default=config.execution.min_order_notional,
        type=float,
        show_default=True,
    )
    config.execution.cash_buffer_pct = click.prompt(
        "Cash buffer percent",
        default=config.execution.cash_buffer_pct,
        type=float,
        show_default=True,
    )

    config.costs.commission_per_trade = click.prompt(
        "Commission per trade",
        default=config.costs.commission_per_trade,
        type=float,
        show_default=True,
    )
    config.costs.slippage_bps = click.prompt(
        "Slippage (bps)",
        default=config.costs.slippage_bps,
        type=float,
        show_default=True,
    )


def edit_suite_interactively(config: SuiteConfig) -> None:
    click.echo("Edit suite settings before run (press Enter to keep default).")

    config.backtest.start_date = click.prompt(
        "Start date (YYYY-MM-DD)",
        default=config.backtest.start_date,
        show_default=True,
    )
    config.backtest.end_date = click.prompt(
        "End date (YYYY-MM-DD)",
        default=config.backtest.end_date,
        show_default=True,
    )
    config.backtest.initial_cash = click.prompt(
        "Initial cash",
        default=config.backtest.initial_cash,
        type=float,
        show_default=True,
    )
    config.warmup.enabled = click.prompt(
        "Warmup enabled",
        default=config.warmup.enabled,
        type=bool,
        show_default=True,
    )
    config.warmup.rebase = click.prompt(
        "Warmup rebase",
        default=config.warmup.rebase,
        type=bool,
        show_default=True,
    )
    config.leaderboard.dd_limit = click.prompt(
        "Drawdown limit (negative fraction)",
        default=config.leaderboard.dd_limit,
        type=float,
        show_default=True,
    )
    config.leaderboard.turnover_limit = click.prompt(
        "Turnover limit",
        default=config.leaderboard.turnover_limit,
        type=float,
        show_default=True,
    )
    config.meta.enabled = click.prompt(
        "Meta selection enabled",
        default=config.meta.enabled,
        type=bool,
        show_default=True,
    )
    config.meta.min_periods_before_selection = click.prompt(
        "Min periods before selection",
        default=config.meta.min_periods_before_selection,
        type=int,
        show_default=True,
    )


def _default_run_template() -> str:
    return """backtest:\n  name: \"ROMULUS Run Default\"\n  start_date: \"2010-01-01\"\n  end_date: \"2024-12-31\"\n  initial_cash: 10000.0\n\nuniverse:\n  source: \"configs/universe_default.json\"\n\nstrategy:\n  type: \"equal_weight\"\n\nexecution:\n  decision_days: [\"wednesday\", \"friday\"]\n  decision_time: \"close\"\n  fill_time: \"open\"\n  fractional_shares: true\n  min_order_notional: 1.0\n  cash_buffer_pct: 0.01\n\ncosts:\n  commission_per_trade: 0.0\n  slippage_bps: 5.0\n\ndata:\n  source: \"yfinance\"\n  cache_dir: \"data/cache\"\n  adjustment: \"split_and_dividend\"\n\noutput:\n  run_dir: \"outputs/runs\"\n"""


def _default_suite_template() -> str:
    return """backtest:\n  name: \"ROMULUS Suite Default\"\n  start_date: \"2010-01-01\"\n  end_date: \"2024-12-31\"\n  initial_cash: 10000.0\n\nuniverse:\n  source: \"configs/universe_default.json\"\n\nstrategies:\n  - name: \"equal_weight\"\n    type: \"equal_weight\"\n  - name: \"cash_only\"\n    type: \"cash_only\"\n\nexecution:\n  decision_days: [\"wednesday\", \"friday\"]\n  decision_time: \"close\"\n  fill_time: \"open\"\n  fractional_shares: true\n  min_order_notional: 1.0\n  cash_buffer_pct: 0.01\n\ncosts:\n  commission_per_trade: 0.0\n  slippage_bps: 5.0\n\ndata:\n  source: \"yfinance\"\n  cache_dir: \"data/cache\"\n  adjustment: \"split_and_dividend\"\n\noutput:\n  run_dir: \"outputs/suite_runs\"\n\nwarmup:\n  enabled: true\n  start_date: \"2008-01-01\"\n  rebase: true\n\nleaderboard:\n  window: 20\n  dd_limit: -0.2\n  turnover_limit: 1.0\n\nmeta:\n  enabled: false\n  min_periods_before_selection: 4\n  baseline_strategy: \"equal_weight\"\n"""


@cli.command()
@click.option("--suite", is_flag=True, help="Create suite default config")
def init(suite: bool) -> None:
    """Initialize default config files."""
    configs_dir = Path.cwd() / "configs"
    configs_dir.mkdir(parents=True, exist_ok=True)

    filename = "suite_default.yaml" if suite else "default.yaml"
    target = configs_dir / filename
    if target.exists():
        raise click.ClickException(f"Config already exists: {format_path_for_display(target)}")

    template = _default_suite_template() if suite else _default_run_template()
    target.write_text(template, encoding="utf-8")

    click.echo(f"Created {format_path_for_display(target)}")
    click.echo("Next commands to run:")
    click.echo("  romulus config validate --config configs/default.yaml" if not suite else "  romulus config validate --config configs/suite_default.yaml --suite")
    click.echo("  romulus run" if not suite else "  romulus suite")


@cli.group()
def config() -> None:
    """Configuration utilities."""


@config.command("validate")
@click.option("--config", "config_path", required=True, help="Path to YAML config file")
@click.option("--suite", "suite_mode", is_flag=True, help="Validate a suite config")
def validate_config(config_path: str, suite_mode: bool) -> None:
    """Validate a config file and report errors."""
    try:
        if suite_mode:
            load_suite_config(config_path)
        else:
            load_config(config_path)
    except Exception as exc:
        raise click.ClickException(f"Config validation failed: {exc}") from exc

    click.echo(f"Config OK: {format_path_for_display(Path(config_path))}")


@cli.group()
def runs() -> None:
    """Utilities for listing runs."""


@runs.command("list")
@click.option("--limit", default=10, show_default=True, type=int, help="Max runs to display")
def list_runs(limit: int) -> None:
    """List recent run IDs and metrics."""
    run_dirs = []
    for base in (Path("outputs/runs"), Path("outputs/suite_runs")):
        if base.exists():
            run_dirs.extend([path for path in base.iterdir() if path.is_dir()])

    rows = []
    for run_dir in run_dirs:
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        metrics_path = run_dir / "metrics.json"
        reliability_path = run_dir / "reliability_report.json"
        metrics = {}
        if metrics_path.exists():
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        if reliability_path.exists():
            metrics = json.loads(reliability_path.read_text(encoding="utf-8"))
        rows.append(
            {
                "run_id": manifest.get("run_id", run_dir.name),
                "config_name": manifest.get("config_name"),
                "created_at": manifest.get("created_at"),
                "path": run_dir,
                "metrics": metrics,
            }
        )

    rows.sort(key=lambda item: item["created_at"] or "", reverse=True)

    click.echo("Recent runs:")
    for row in rows[:limit]:
        path_display = format_path_for_display(row["path"])
        summary = ""
        if "final_value" in row["metrics"]:
            summary = f"final_value={row['metrics']['final_value']}"
        if "most_reliable" in row["metrics"]:
            summary = f"most_reliable={row['metrics']['most_reliable']}"
        config_name = row.get("config_name") or "-"
        click.echo(
            f"  {row['run_id']} | {row['created_at']} | {config_name} | {path_display} | {summary}"
        )


@cli.command()
@click.option("--run", "run_id", required=True, help="Run ID to report")
def report(run_id: str) -> None:
    """Print a readable summary for a run."""
    search_paths = [Path("outputs/runs"), Path("outputs/suite_runs")]
    target = None
    for base in search_paths:
        candidate = base / run_id
        if candidate.exists():
            target = candidate
            break
    if target is None:
        raise click.ClickException(f"Run not found: {run_id}")

    click.echo(f"Run: {run_id}")
    click.echo(f"Path: {format_path_for_display(target)}")
    manifest_path = target / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        config_name = manifest.get("config_name")
        if config_name:
            click.echo(f"Config: {config_name}")

    metrics_path = target / "metrics.json"
    reliability_path = target / "reliability_report.json"
    if metrics_path.exists():
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        click.echo("Metrics:")
        for key, value in metrics.items():
            click.echo(f"  {key}: {value}")
    if reliability_path.exists():
        report_data = json.loads(reliability_path.read_text(encoding="utf-8"))
        click.echo("Reliability:")
        click.echo(f"  most_reliable: {report_data.get('most_reliable')}")

    click.echo("Artifacts:")
    for artifact in ("orders.parquet", "fills.parquet", "leaderboard.csv", "reliability_report.json"):
        artifact_path = target / artifact
        if artifact_path.exists():
            click.echo(f"  {format_path_for_display(artifact_path)}")


@cli.command()
@click.option("--config", "config_path", required=False, help="Path to YAML config file")
@click.option("--start", "start_date", required=False, help="Override start date (YYYY-MM-DD)")
@click.option("--end", "end_date", required=False, help="Override end date (YYYY-MM-DD)")
@click.option(
    "--edit/--no-edit",
    default=True,
    help="Offer interactive edit step before running",
)
@click.option(
    "--show-effective",
    is_flag=True,
    help="Print effective settings and exit without running",
)
def run(
    config_path: str | None,
    start_date: str | None,
    end_date: str | None,
    edit: bool,
    show_effective: bool,
) -> None:
    """Run a backtest from a configuration file."""
    config_file = resolve_config_path(
        config_path,
        [Path("configs/etf_equal_weight.yaml"), Path("configs/default.yaml")],
    )

    if not config_file.exists():
        raise click.ClickException(f"Config file not found: {config_file}")

    click.echo(f"Using config: {format_path_for_display(config_file)}")

    config = load_config(str(config_file))

    if start_date:
        config.backtest.start_date = start_date
    if end_date:
        config.backtest.end_date = end_date

    print_effective_settings(config)
    click.echo(f"Outputs will be saved under: {format_path_for_display(Path(config.output.run_dir))}")

    if show_effective:
        return

    if edit:
        edit_config_interactively(config)

    engine = BacktestEngine()
    result = engine.run(config)

    metrics = result["metrics"]
    click.echo(f"Final Value: {metrics['final_value']:.2f}")
    click.echo(f"Total Return: {metrics['total_return']:.2f}%")
    click.echo(f"CAGR: {metrics['cagr']:.2f}%")
    click.echo(f"Sharpe: {metrics['sharpe']:.2f}")
    click.echo(f"Max Drawdown: {metrics['max_drawdown']:.2f}%")
    click.echo(f"Outputs saved to: {format_path_for_display(Path(result['output_path']))}")


@cli.command()
@click.option("--config", "config_path", required=False, help="Path to YAML suite config file")
@click.option("--start", "start_date", required=False, help="Override start date (YYYY-MM-DD)")
@click.option("--end", "end_date", required=False, help="Override end date (YYYY-MM-DD)")
@click.option(
    "--edit/--no-edit",
    default=True,
    help="Offer interactive edit step before running",
)
@click.option(
    "--show-effective",
    is_flag=True,
    help="Print effective settings and exit without running",
)
def suite(
    config_path: str | None,
    start_date: str | None,
    end_date: str | None,
    edit: bool,
    show_effective: bool,
) -> None:
    """Run a strategy suite and optional meta-selection."""
    config_file = resolve_config_path(
        config_path,
        [Path("configs/suite_default.yaml"), Path("configs/default.yaml")],
    )

    if not config_file.exists():
        raise click.ClickException(f"Config file not found: {config_file}")

    click.echo(f"Using config: {format_path_for_display(config_file)}")
    config = load_suite_config(str(config_file))

    if start_date:
        config.backtest.start_date = start_date
    if end_date:
        config.backtest.end_date = end_date

    print_suite_effective_settings(config)
    click.echo(f"Outputs will be saved under: {format_path_for_display(Path(config.output.run_dir))}")

    if show_effective:
        return

    if edit:
        edit_suite_interactively(config)

    runner = SuiteRunner()
    result = runner.run(config)

    click.echo(f"Suite run complete: {result['run_id']}")
    click.echo(f"Outputs saved to: {format_path_for_display(Path(result['output_path']))}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
