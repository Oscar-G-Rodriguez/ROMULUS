"""Progress tracking utilities for backtests."""

from __future__ import annotations

from calendar import monthrange
from math import floor
from dataclasses import asdict, dataclass
from datetime import date
from time import perf_counter
from typing import Callable, List, Optional


PROGRESS_WEIGHTS = {
    "data": 0.10,
    "validation": 0.05,
    "warmup": 0.15,
    "simulation": 0.65,
    "artifacts": 0.05,
}


class RunCancelled(RuntimeError):
    """Raised at a safe decision boundary when cancellation was requested."""


@dataclass(frozen=True)
class ProgressEvent:
    stage: str
    completed: int
    total: int
    stage_percent: float
    overall_percent: float
    current_date: str | None = None
    fill_date: str | None = None
    active_strategy: str | None = None
    elapsed_seconds: float = 0.0
    eta_seconds: float | None = None
    message: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class ProgressReporter:
    """Emit monotonic structured progress to UI, CLI, and run manifests."""

    def __init__(
        self,
        callback: Optional[Callable[[ProgressEvent], None]] = None,
        cancel_requested: Optional[Callable[[], bool]] = None,
        *,
        warmup_enabled: bool = True,
    ) -> None:
        self.callback = callback
        self.cancel_requested = cancel_requested
        self.started = perf_counter()
        self.events: list[dict] = []
        self._last_overall = 0.0
        self.weights = dict(PROGRESS_WEIGHTS)
        if not warmup_enabled:
            self.weights["simulation"] += self.weights["warmup"]
            self.weights["warmup"] = 0.0

    def check_cancelled(self) -> None:
        if self.cancel_requested is not None and self.cancel_requested():
            raise RunCancelled("Run cancelled at a safe decision boundary")

    def emit(
        self,
        stage: str,
        completed: int,
        total: int,
        *,
        current_date: date | None = None,
        fill_date: date | None = None,
        active_strategy: str | None = None,
        message: str = "",
    ) -> ProgressEvent:
        total = max(1, total)
        stage_fraction = min(1.0, max(0.0, completed / total))
        stage_order = list(self.weights)
        prefix = sum(self.weights[name] for name in stage_order[: stage_order.index(stage)])
        overall = min(1.0, prefix + self.weights[stage] * stage_fraction)
        overall = max(self._last_overall, overall)
        self._last_overall = overall
        elapsed = perf_counter() - self.started
        eta = elapsed * (1.0 - overall) / overall if 0 < overall < 1 else None
        event = ProgressEvent(
            stage=stage,
            completed=max(0, completed),
            total=total,
            stage_percent=stage_fraction * 100.0,
            overall_percent=overall * 100.0,
            current_date=current_date.isoformat() if current_date else None,
            fill_date=fill_date.isoformat() if fill_date else None,
            active_strategy=active_strategy,
            elapsed_seconds=elapsed,
            eta_seconds=eta,
            message=message,
        )
        self.events.append(event.to_dict())
        if self.callback is not None:
            self.callback(event)
        return event


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
    """Print a throttled decision-count progress bar for CLI runs."""

    start_date: date
    end_date: date
    step_months: int = 6
    label: str = "Progress"
    bar_width: int = 20
    total_units: int | None = None

    def __post_init__(self) -> None:
        self._milestones = _build_milestones(self.start_date, self.end_date, self.step_months)
        self._completed = 0
        self._total = max(1, self.total_units or len(self._milestones))
        self._last_render_date: date | None = None
        self._last_percent_display = -1

    def update(self, current_date: date) -> None:
        if self.total_units is not None:
            if self._last_render_date != current_date:
                self._completed = min(self._total, self._completed + 1)
        else:
            while self._completed < len(self._milestones) and current_date >= self._milestones[self._completed]:
                self._completed += 1

        percent_display = int(round(100 * self._completed / self._total))
        if self._last_render_date != current_date and percent_display != self._last_percent_display:
            self._print(current_date)
            self._last_percent_display = percent_display
        self._last_render_date = current_date

    def finish(self) -> None:
        if self._last_render_date is None:
            return
        if self.total_units is not None and self._completed < self._total:
            self._completed = self._total
            self._print(self._last_render_date)
        print("")

    def _print(self, current_date: date) -> None:
        pct = self._completed / self._total
        filled = int(self.bar_width * pct)
        bar = "#" * filled + "-" * (self.bar_width - filled)
        percent_display = 100 if self._completed >= self._total else floor(pct * 100)
        print(
            f"{self.label} progress: [{bar}] {self._completed}/{self._total} "
            f"({percent_display}%) as of {current_date.isoformat()}",
            end="\r",
            flush=True,
        )
