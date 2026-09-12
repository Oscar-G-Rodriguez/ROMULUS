"""Date-aware performance metrics for backtests.

Portfolio values are recorded at execution events, not necessarily on every
trading day. Metrics therefore use timestamps; they never infer elapsed time
from an observation count.
"""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd


CALENDAR_DAYS_PER_YEAR = 365.25


def _dated_values(portfolio_value: pd.Series) -> pd.Series:
    """Return finite, positive values indexed by unique increasing dates."""
    values = pd.to_numeric(portfolio_value, errors="coerce").dropna()
    values = values[values > 0]
    if values.empty:
        return values
    try:
        dates = pd.to_datetime(values.index, errors="raise")
    except (TypeError, ValueError):
        return pd.Series(dtype=float)
    values = pd.Series(values.to_numpy(dtype=float), index=dates)
    return values[~values.index.duplicated(keep="last")].sort_index()


def _timestamp_aware_moments(values: pd.Series) -> tuple[float, float]:
    """Return annualized zero-rate Sharpe and volatility for irregular samples."""
    if len(values) < 3 or not isinstance(values.index, pd.DatetimeIndex):
        return 0.0, 0.0
    elapsed_days = values.index.to_series().diff().dt.total_seconds().to_numpy() / 86400.0
    log_returns = np.diff(np.log(values.to_numpy(dtype=float)))
    valid = np.isfinite(log_returns) & np.isfinite(elapsed_days[1:]) & (elapsed_days[1:] > 0)
    log_returns, days = log_returns[valid], elapsed_days[1:][valid]
    if len(log_returns) < 2 or days.sum() <= 0:
        return 0.0, 0.0
    daily_drift = float(log_returns.sum() / days.sum())
    residuals = log_returns - daily_drift * days
    variance_per_day = float(np.sum(residuals**2) / days.sum())
    if variance_per_day <= 0 or not np.isfinite(variance_per_day):
        return 0.0, 0.0
    annualized_volatility = float(np.sqrt(variance_per_day * CALENDAR_DAYS_PER_YEAR))
    sharpe = float((daily_drift * CALENDAR_DAYS_PER_YEAR) / annualized_volatility)
    return sharpe, annualized_volatility


def _timestamp_aware_sharpe(values: pd.Series) -> float:
    """Estimate zero-risk-free Sharpe from irregular calendar-time increments."""
    return _timestamp_aware_moments(values)[0]


def compute_metrics(portfolio_value: pd.Series) -> Dict[str, float]:
    """Compute total return, CAGR, Sharpe, and drawdown from dated values.

    A non-dated series has no defensible annualization basis, so CAGR and
    Sharpe are zero rather than silently assuming daily samples.
    """
    values = _dated_values(portfolio_value)
    if values.empty:
        return {
            "total_return": 0.0, "cagr": 0.0, "sharpe": 0.0,
            "max_drawdown": 0.0, "final_value": 0.0, "initial_value": 0.0,
            "elapsed_days": 0.0, "annualized_volatility": 0.0,
        }
    initial_value, final_value = float(values.iloc[0]), float(values.iloc[-1])
    total_return = (final_value / initial_value - 1.0) * 100.0
    elapsed_days = float((values.index[-1] - values.index[0]).total_seconds() / 86400.0) if len(values) >= 2 else 0.0
    years = elapsed_days / CALENDAR_DAYS_PER_YEAR
    cagr = ((final_value / initial_value) ** (1.0 / years) - 1.0) * 100.0 if years > 0 else 0.0
    running_max = values.cummax()
    sharpe, annualized_volatility = _timestamp_aware_moments(values)
    return {
        "total_return": float(total_return), "cagr": float(cagr),
        "sharpe": sharpe,
        "annualized_volatility": annualized_volatility,
        "max_drawdown": float(((values - running_max) / running_max).min() * 100.0),
        "final_value": final_value, "initial_value": initial_value,
        "elapsed_days": elapsed_days,
    }
