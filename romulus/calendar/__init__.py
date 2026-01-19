"""Calendar management module for ROMULUS."""

from romulus.calendar.decision_days import (
    generate_decision_calendar,
    get_next_trading_day,
)
from romulus.calendar.trading_days import get_trading_days, is_trading_day

__all__ = [
    "generate_decision_calendar",
    "get_next_trading_day",
    "get_trading_days",
    "is_trading_day",
]
