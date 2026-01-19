"""Unit tests for calendar utilities."""

from __future__ import annotations

from datetime import date

from romulus.calendar.decision_days import generate_decision_calendar, get_next_trading_day
from romulus.calendar.trading_days import get_trading_days


def test_no_weekends() -> None:
    days = get_trading_days("2024-12-01", "2024-12-31")

    assert all(day.weekday() < 5 for day in days)


def test_no_holidays() -> None:
    days = get_trading_days("2024-12-01", "2024-12-31")

    assert date(2024, 12, 25) not in days


def test_decision_calendar_wed_fri_only() -> None:
    decision_days = generate_decision_calendar("2024-12-01", "2024-12-31")

    assert all(day.weekday() in {2, 4} for day in decision_days)


def test_no_holiday_decisions() -> None:
    decision_days = generate_decision_calendar("2024-12-01", "2024-12-31")

    assert date(2024, 12, 25) not in decision_days


def test_fill_date_mapping() -> None:
    trading_days = get_trading_days("2024-12-02", "2024-12-10")
    decision_days = generate_decision_calendar("2024-12-02", "2024-12-10")

    decision_day = decision_days[0]
    next_day = get_next_trading_day(decision_day, trading_days)

    assert next_day > decision_day
    assert next_day in trading_days
