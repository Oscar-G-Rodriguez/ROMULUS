"""Command line interface for ROMULUS."""

from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Mapping

import click

from romulus.backtest.engine import BacktestEngine
from romulus.config.schema import BacktestConfig, load_config


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


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """ROMULUS command line interface."""
    # If user runs just `romulus` with no subcommand, start interactive mode.
    if ctx.invoked_subcommand is None:
        repl()


def resolve_default_config_path(
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
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

    candidate = cwd / "configs" / "etf_equal_weight.yaml"
    if candidate.exists():
        return candidate

    candidate = cwd / "configs" / "default.yaml"
    if candidate.exists():
        return candidate

    return None


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
    if config_path:
        config_file = Path(config_path)
    else:
        config_file = resolve_default_config_path()
        if config_file is None:
            config_file = prompt_for_config_path()

    if not config_file.exists():
        raise click.ClickException(f"Config file not found: {config_file}")

    display_path = format_path_for_display(config_file)
    click.echo(f"Using config: {display_path}")

    config = load_config(str(config_file))

    if start_date:
        config.backtest.start_date = start_date
    if end_date:
        config.backtest.end_date = end_date

    print_effective_settings(config)

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
    click.echo(f"Outputs saved to: {result['output_path']}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
