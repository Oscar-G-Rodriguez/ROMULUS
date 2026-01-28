"""NYSE trading day utilities."""

from __future__ import annotations

from datetime import date
from typing import List

import pandas_market_calendars as mcal


def get_trading_days(start: str, end: str) -> List[date]:
    """Return NYSE trading days between start and end (inclusive)."""
    calendar = mcal.get_calendar("NYSE")
    schedule = calendar.schedule(start_date=start, end_date=end)
    return [day.date() for day in schedule.index]


def is_trading_day(day: date) -> bool:
    """Check if a given date is a NYSE trading day."""
    calendar = mcal.get_calendar("NYSE")
    schedule = calendar.schedule(
        start_date=day.isoformat(),
        end_date=day.isoformat(),
    )
    return not schedule.empty
