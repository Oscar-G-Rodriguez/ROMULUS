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
