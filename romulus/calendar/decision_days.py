"""Decision day utilities for rebalancing."""

from __future__ import annotations

from datetime import date
from typing import List

from romulus.calendar.trading_days import get_trading_days

_DAY_TO_WEEKDAY = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def generate_decision_calendar(
    start: str,
    end: str,
    days: List[str] | None = None,
) -> List[date]:
    """Generate decision dates filtered to the given weekdays."""
    if days is None:
        days = ["wednesday", "friday"]

    allowed = {_DAY_TO_WEEKDAY[day.lower()] for day in days}
    trading_days = get_trading_days(start, end)

    return [day for day in trading_days if day.weekday() in allowed]


def get_next_trading_day(day: date, trading_days: List[date]) -> date:
    """Return the next trading day after the given date."""
    if day not in trading_days:
        raise ValueError(f"Date {day} not in trading calendar")

    index = trading_days.index(day)
    if index + 1 >= len(trading_days):
        raise ValueError("No next trading day available")

    return trading_days[index + 1]


def get_next_trading_day_safe(day: date, trading_days: List[date]) -> date | None:
    """Return next trading day or None if unavailable."""
    try:
        return get_next_trading_day(day, trading_days)
    except ValueError:
        return None


def compute_fill_date(
    decision_date: date,
    trading_days: List[date],
    decision_time: str,
    fill_time: str,
) -> date | None:
    """Compute fill date based on decision/fill times."""
    if decision_time == "close" and fill_time == "open":
        return get_next_trading_day_safe(decision_date, trading_days)
    return decision_date
