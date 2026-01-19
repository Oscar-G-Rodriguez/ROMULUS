"""Unit tests for calendar utilities."""

from __future__ import annotations

from datetime import date

from romulus.calendar.trading_days import get_trading_days


def test_no_weekends() -> None:
    days = get_trading_days("2024-12-01", "2024-12-31")

    assert all(day.weekday() < 5 for day in days)


def test_no_holidays() -> None:
    days = get_trading_days("2024-12-01", "2024-12-31")

    assert date(2024, 12, 25) not in days
