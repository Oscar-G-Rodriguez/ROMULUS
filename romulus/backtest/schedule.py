"""Decision schedule helpers for backtests and suites."""

from __future__ import annotations

from datetime import date
from typing import List, Optional, Tuple

from romulus.calendar.decision_days import compute_fill_date


def build_decision_schedule(
    decision_calendar: List[date],
    trading_days: List[date],
    decision_time: str,
    fill_time: str,
    end_date: date,
) -> Tuple[List[dict], Optional[dict]]:
    """Build decision schedule with fill dates, skipping invalid final decisions."""
    schedule: List[dict] = []
    skipped: Optional[dict] = None
    for decision_date in decision_calendar:
        fill_date = compute_fill_date(decision_date, trading_days, decision_time, fill_time)
        if fill_date is None or fill_date > end_date:
            skipped = {
                "decision_date": decision_date,
                "fill_date": fill_date,
                "reason": "fill_date_unavailable_before_end_date",
            }
            break
        schedule.append({"decision_date": decision_date, "fill_date": fill_date})
    return schedule, skipped
