"""Structured progress contract tests."""

from datetime import date

import pytest

from romulus.backtest.progress import ProgressReporter, ProgressTracker, RunCancelled


def test_progress_is_monotonic_and_tracks_simulated_date() -> None:
    reporter = ProgressReporter(warmup_enabled=False)
    reporter.emit("data", 1, 1)
    reporter.emit("validation", 1, 1)
    event = reporter.emit("simulation", 3, 10, current_date=date(2024, 1, 12), active_strategy="alpha")
    reporter.emit("artifacts", 1, 1)

    percentages = [row["overall_percent"] for row in reporter.events]
    assert percentages == sorted(percentages)
    assert event.current_date == "2024-01-12"
    assert event.active_strategy == "alpha"
    assert percentages[-1] == 100.0


def test_progress_cancellation_is_checked_at_safe_boundaries() -> None:
    reporter = ProgressReporter(cancel_requested=lambda: True)
    with pytest.raises(RunCancelled):
        reporter.check_cancelled()


def test_cli_progress_counts_decisions_not_calendar_milestones(capsys) -> None:
    tracker = ProgressTracker(date(2024, 1, 1), date(2025, 1, 1), total_units=2)
    tracker.update(date(2024, 1, 5))
    tracker.update(date(2024, 1, 8))
    tracker.finish()

    output = capsys.readouterr().out
    assert "1/2 (50%)" in output
    assert "2/2 (100%)" in output
