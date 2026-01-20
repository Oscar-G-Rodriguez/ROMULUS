"""Deterministic strategy implementations."""

from __future__ import annotations

from datetime import date
from typing import Dict, List

import pandas as pd

from romulus.strategy.base import BaseStrategy


def _get_series(prices: pd.DataFrame, ticker: str, field: str) -> pd.Series:
    return prices[(ticker, field)].dropna()


def _daily_returns(prices: pd.DataFrame, ticker: str) -> pd.Series:
    series = _get_series(prices, ticker, "Close")
    return series.pct_change().dropna().rename(ticker)


def _inv_vol_scores(prices: pd.DataFrame, tickers: List[str], lookback: int, vol_floor: float) -> Dict[str, float]:
    scores = {}
    for ticker in tickers:
        returns = _daily_returns(prices, ticker).tail(lookback)
        if returns.empty:
            continue
        sigma = returns.std()
        score = 1.0 / max(sigma, vol_floor)
        scores[ticker] = score
    return scores


def _weight_from_scores(scores: Dict[str, float]) -> Dict[str, float]:
    total = sum(scores.values())
    if total <= 0:
        return {}
    return {ticker: score / total for ticker, score in scores.items()}


def _equal_weights(tickers: List[str]) -> Dict[str, float]:
    if not tickers:
        return {}
    weight = 1.0 / len(tickers)
    return {ticker: weight for ticker in tickers}


def _inv_vol_weights(prices: pd.DataFrame, tickers: List[str], lookback: int, vol_floor: float) -> Dict[str, float]:
    scores = _inv_vol_scores(prices, tickers, lookback, vol_floor)
    return _weight_from_scores(scores)


class InvVolStrategy(BaseStrategy):
    """Inverse volatility weighting strategy."""

    description = "Weights by inverse realized volatility."

    def __init__(self, lookback_days: int = 20, vol_floor: float = 1e-6, top_k: int | None = None) -> None:
        self.lookback_days = lookback_days
        self.vol_floor = vol_floor
        self.top_k = top_k
        self._last_signals: dict = {}
        self._last_raw_weights: dict = {}

    def compute_target_weights(
        self,
        as_of_date: date,
        eligible_tickers: List[str],
        prices: pd.DataFrame,
        positions: Dict[str, float],
    ) -> Dict[str, float]:
        scores = _inv_vol_scores(prices, eligible_tickers, self.lookback_days, self.vol_floor)
        if self.top_k is not None:
            ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)[: self.top_k]
            scores = dict(ranked)

        weights = _weight_from_scores(scores)
        self._last_signals = {"scores": scores}
        self._last_raw_weights = weights
        return weights

    def get_last_signals(self) -> dict:
        return self._last_signals

    def get_last_raw_weights(self) -> dict:
        return self._last_raw_weights


class TsMomStrategy(BaseStrategy):
    """Time-series momentum strategy with defensive cash."""

    description = "Time-series momentum with optional inverse-vol weighting."

    def __init__(
        self,
        lookback_days: int = 63,
        edge_floor: float = 0.0,
        weighting: str = "equal",
        vol_floor: float = 1e-6,
    ) -> None:
        self.lookback_days = lookback_days
        self.edge_floor = edge_floor
        self.weighting = weighting
        self.vol_floor = vol_floor
        self._last_signals: dict = {}
        self._last_raw_weights: dict = {}

    def compute_target_weights(
        self,
        as_of_date: date,
        eligible_tickers: List[str],
        prices: pd.DataFrame,
        positions: Dict[str, float],
    ) -> Dict[str, float]:
        momentum: Dict[str, float] = {}
        for ticker in eligible_tickers:
            series = _get_series(prices, ticker, "Close")
            if len(series) <= self.lookback_days:
                continue
            mom = series.iloc[-1] / series.iloc[-self.lookback_days - 1] - 1
            momentum[ticker] = mom

        selected = [ticker for ticker, mom in momentum.items() if mom > self.edge_floor]
        if not selected:
            self._last_signals = {"momentum": momentum, "selected": []}
            self._last_raw_weights = {}
            return {}

        if self.weighting == "inv_vol":
            weights = _inv_vol_weights(prices, selected, self.lookback_days, self.vol_floor)
        else:
            weights = _equal_weights(selected)

        self._last_signals = {"momentum": momentum, "selected": selected}
        self._last_raw_weights = weights
        return weights

    def get_last_signals(self) -> dict:
        return self._last_signals

    def get_last_raw_weights(self) -> dict:
        return self._last_raw_weights


class XSecMomStrategy(BaseStrategy):
    """Cross-sectional momentum strategy."""

    description = "Cross-sectional momentum with defensive cash gate."

    def __init__(
        self,
        lookback_days: int = 63,
        top_k: int = 3,
        defensive_floor: float = 0.0,
        weighting: str = "equal",
        vol_floor: float = 1e-6,
    ) -> None:
        self.lookback_days = lookback_days
        self.top_k = top_k
        self.defensive_floor = defensive_floor
        self.weighting = weighting
        self.vol_floor = vol_floor
        self._last_signals: dict = {}
        self._last_raw_weights: dict = {}

    def compute_target_weights(
        self,
        as_of_date: date,
        eligible_tickers: List[str],
        prices: pd.DataFrame,
        positions: Dict[str, float],
    ) -> Dict[str, float]:
        returns = {}
        for ticker in eligible_tickers:
            series = _get_series(prices, ticker, "Close")
            if len(series) <= self.lookback_days:
                continue
            trailing = series.iloc[-1] / series.iloc[-self.lookback_days - 1] - 1
            returns[ticker] = trailing

        ranked = sorted(returns.items(), key=lambda item: item[1], reverse=True)
        if not ranked or ranked[0][1] <= self.defensive_floor:
            self._last_signals = {"returns": returns, "selected": []}
            self._last_raw_weights = {}
            return {}

        selected = [ticker for ticker, _ in ranked[: self.top_k]]
        if self.weighting == "inv_vol":
            weights = _inv_vol_weights(prices, selected, self.lookback_days, self.vol_floor)
        else:
            weights = _equal_weights(selected)

        self._last_signals = {"returns": returns, "selected": selected}
        self._last_raw_weights = weights
        return weights

    def get_last_signals(self) -> dict:
        return self._last_signals

    def get_last_raw_weights(self) -> dict:
        return self._last_raw_weights


class VolTargetStrategy(BaseStrategy):
    """Volatility targeting strategy with cash scaling."""

    description = "Scale exposure to target annualized volatility."

    def __init__(
        self,
        base: str = "equal",
        lookback_days: int = 20,
        target_annual_vol: float = 0.10,
        vol_floor: float = 1e-6,
    ) -> None:
        self.base = base
        self.lookback_days = lookback_days
        self.target_annual_vol = target_annual_vol
        self.vol_floor = vol_floor
        self._last_signals: dict = {}
        self._last_raw_weights: dict = {}

    def compute_target_weights(
        self,
        as_of_date: date,
        eligible_tickers: List[str],
        prices: pd.DataFrame,
        positions: Dict[str, float],
    ) -> Dict[str, float]:
        if self.base == "inv_vol":
            base_weights = _inv_vol_weights(prices, eligible_tickers, self.lookback_days, self.vol_floor)
        else:
            base_weights = _equal_weights(eligible_tickers)

        if not base_weights:
            self._last_signals = {"realized_vol": None, "scale": 0.0}
            self._last_raw_weights = {}
            return {}

        returns_df = []
        for ticker in base_weights:
            returns_df.append(_daily_returns(prices, ticker).tail(self.lookback_days))
        if not returns_df:
            self._last_signals = {"realized_vol": None, "scale": 0.0}
            self._last_raw_weights = {}
            return {}

        aligned = pd.concat(returns_df, axis=1).dropna()
        if aligned.empty:
            self._last_signals = {"realized_vol": None, "scale": 0.0}
            self._last_raw_weights = {}
            return {}

        weights_series = pd.Series(base_weights)
        portfolio_returns = aligned.dot(weights_series.loc[aligned.columns])
        realized_vol = portfolio_returns.std() * (252 ** 0.5)
        if realized_vol <= 0:
            scale = 0.0
        else:
            scale = min(1.0, self.target_annual_vol / realized_vol)

        weights = {ticker: weight * scale for ticker, weight in base_weights.items()}

        self._last_signals = {"realized_vol": float(realized_vol), "scale": float(scale)}
        self._last_raw_weights = weights
        return weights

    def get_last_signals(self) -> dict:
        return self._last_signals

    def get_last_raw_weights(self) -> dict:
        return self._last_raw_weights


class MaCrossoverStrategy(BaseStrategy):
    """Moving average crossover strategy."""

    description = "Trend filter using fast/slow moving averages."

    def __init__(
        self,
        fast_days: int = 20,
        slow_days: int = 100,
        weighting: str = "equal",
        vol_floor: float = 1e-6,
    ) -> None:
        self.fast_days = fast_days
        self.slow_days = slow_days
        self.weighting = weighting
        self.vol_floor = vol_floor
        self._last_signals: dict = {}
        self._last_raw_weights: dict = {}

    def compute_target_weights(
        self,
        as_of_date: date,
        eligible_tickers: List[str],
        prices: pd.DataFrame,
        positions: Dict[str, float],
    ) -> Dict[str, float]:
        signals = {}
        selected: List[str] = []
        for ticker in eligible_tickers:
            series = _get_series(prices, ticker, "Close")
            if len(series) < self.slow_days:
                continue
            fast_ma = series.tail(self.fast_days).mean()
            slow_ma = series.tail(self.slow_days).mean()
            signal = 1 if fast_ma > slow_ma else 0
            signals[ticker] = {
                "fast_ma": float(fast_ma),
                "slow_ma": float(slow_ma),
                "signal": signal,
            }
            if signal == 1:
                selected.append(ticker)

        if not selected:
            self._last_signals = {"signals": signals, "selected": []}
            self._last_raw_weights = {}
            return {}

        if self.weighting == "inv_vol":
            weights = _inv_vol_weights(prices, selected, self.slow_days, self.vol_floor)
        else:
            weights = _equal_weights(selected)

        self._last_signals = {"signals": signals, "selected": selected}
        self._last_raw_weights = weights
        return weights

    def get_last_signals(self) -> dict:
        return self._last_signals

    def get_last_raw_weights(self) -> dict:
        return self._last_raw_weights
