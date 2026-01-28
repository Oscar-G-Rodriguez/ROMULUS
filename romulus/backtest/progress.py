"""Progress tracking utilities for backtests."""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from typing import List


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, monthrange(year, month)[1])
    return date(year, month, day)


def _build_milestones(start: date, end: date, step_months: int) -> List[date]:
    milestones: List[date] = []
    cursor = _add_months(start, step_months)
    while cursor <= end:
        milestones.append(cursor)
        cursor = _add_months(cursor, step_months)
    if not milestones and start <= end:
        milestones.append(end)
    return milestones


@dataclass
class ProgressTracker:
    """Prints progress updates at fixed month intervals."""

    start_date: date
    end_date: date
    step_months: int = 6
    label: str = "Progress"
    bar_width: int = 20

    def __post_init__(self) -> None:
        self._milestones = _build_milestones(self.start_date, self.end_date, self.step_months)
        self._completed = 0
        self._total = max(1, len(self._milestones))
        self._last_render_date: date | None = None

    def update(self, current_date: date) -> None:
        while self._completed < len(self._milestones) and current_date >= self._milestones[self._completed]:
            self._completed += 1

        if self._last_render_date != current_date:
            self._print(current_date)
            self._last_render_date = current_date

    def finish(self) -> None:
        if self._last_render_date is None:
            return
        print("")

    def _print(self, current_date: date) -> None:
        pct = self._completed / self._total
        filled = int(self.bar_width * pct)
        bar = "#" * filled + "-" * (self.bar_width - filled)
        percent_display = int(round(pct * 100))
        print(
            f"{self.label} progress: [{bar}] {self._completed}/{self._total} "
            f"({percent_display}%) as of {current_date.isoformat()}",
            end="\r",
            flush=True,
        )
