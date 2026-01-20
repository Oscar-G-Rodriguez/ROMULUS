"""Unit tests for decision schedule filtering."""

from __future__ import annotations

from datetime import date

from romulus.backtest.schedule import build_decision_schedule


def test_build_decision_schedule_skips_final_when_fill_missing() -> None:
    trading_days = [date(2024, 1, 3), date(2024, 1, 4)]
    decision_calendar = [date(2024, 1, 3), date(2024, 1, 4)]

    schedule, skipped = build_decision_schedule(
        decision_calendar,
        trading_days,
        "close",
        "open",
        date(2024, 1, 4),
    )

    assert len(schedule) == 1
    assert schedule[0]["decision_date"] == date(2024, 1, 3)
    assert skipped is not None
    assert skipped["decision_date"] == date(2024, 1, 4)
