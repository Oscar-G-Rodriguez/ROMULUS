"""Command line interface for ROMULUS."""

from __future__ import annotations

import click

from romulus.backtest.engine import BacktestEngine
from romulus.config.schema import load_config


@click.group()
def cli() -> None:
    """ROMULUS command line interface."""


@cli.command()
@click.option("--config", "config_path", required=True, help="Path to YAML config file")
@click.option("--start", "start_date", required=False, help="Override start date (YYYY-MM-DD)")
@click.option("--end", "end_date", required=False, help="Override end date (YYYY-MM-DD)")
def run(config_path: str, start_date: str | None, end_date: str | None) -> None:
    """Run a backtest from a configuration file."""
    config = load_config(config_path)

    if start_date:
        config.backtest.start_date = start_date
    if end_date:
        config.backtest.end_date = end_date

    engine = BacktestEngine()
    result = engine.run(config)

    metrics = result["metrics"]
    click.echo(f"Final Value: {metrics['final_value']:.2f}")
    click.echo(f"Total Return: {metrics['total_return']:.2f}%")
    click.echo(f"CAGR: {metrics['cagr']:.2f}%")
    click.echo(f"Sharpe: {metrics['sharpe']:.2f}")
    click.echo(f"Max Drawdown: {metrics['max_drawdown']:.2f}%")
    click.echo(f"Outputs saved to: {result['output_path']}")


if __name__ == "__main__":
    cli()
