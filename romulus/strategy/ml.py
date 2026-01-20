"""Machine learning strategy implementations."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from romulus.strategy.base import BaseStrategy


FEATURE_NAMES = [
    "ret_5",
    "ret_10",
    "ret_21",
    "ret_63",
    "vol_21",
    "vol_63",
    "drawdown_63",
    "ma_ratio_21",
    "ma_ratio_63",
    "atr_proxy_21",
    "vol_z_63",
]


def _feature_hash() -> str:
    payload = "|".join(FEATURE_NAMES).encode("utf-8")
    return hashlib.md5(payload).hexdigest()


def _get_series(prices: pd.DataFrame, ticker: str, field: str) -> pd.Series:
    return prices[(ticker, field)].dropna()


def _compute_features(prices: pd.DataFrame, ticker: str, as_of: date) -> Optional[np.ndarray]:
    try:
        close = _get_series(prices, ticker, "Close").loc[:as_of]
        high = _get_series(prices, ticker, "High").loc[:as_of]
        low = _get_series(prices, ticker, "Low").loc[:as_of]
        volume = _get_series(prices, ticker, "Volume").loc[:as_of]
    except KeyError:
        return None

    if len(close) < 64:
        return None

    def ret_n(n: int) -> float:
        return float(close.iloc[-1] / close.iloc[-n - 1] - 1)

    returns = close.pct_change().dropna()
    if len(returns) < 64:
        return None

    vol_21 = float(returns.tail(21).std())
    vol_63 = float(returns.tail(63).std())

    roll_max = close.tail(63).cummax()
    drawdown = float((close.tail(63) / roll_max).iloc[-1] - 1)

    ma_21 = float(close.tail(21).mean())
    ma_63 = float(close.tail(63).mean())
    ma_ratio_21 = float(close.iloc[-1] / ma_21) if ma_21 else 0.0
    ma_ratio_63 = float(close.iloc[-1] / ma_63) if ma_63 else 0.0

    atr_proxy = float((high.tail(21) - low.tail(21)).mean() / close.iloc[-1])

    vol_mean = float(volume.tail(63).mean())
    vol_std = float(volume.tail(63).std())
    vol_z = float((volume.iloc[-1] - vol_mean) / vol_std) if vol_std else 0.0

    features = np.array(
        [
            ret_n(5),
            ret_n(10),
            ret_n(21),
            ret_n(63),
            vol_21,
            vol_63,
            drawdown,
            ma_ratio_21,
            ma_ratio_63,
            atr_proxy,
            vol_z,
        ],
        dtype=float,
    )
    if np.any(np.isnan(features)):
        return None
    return features


def _interval_return(
    prices: pd.DataFrame,
    ticker: str,
    start: date,
    end: date,
    field: str = "Open",
) -> Optional[float]:
    try:
        series = _get_series(prices, ticker, field)
    except KeyError:
        return None
    if start not in series.index or end not in series.index:
        return None
    return float(series.loc[end] / series.loc[start] - 1)


def _interval_vol(prices: pd.DataFrame, ticker: str, start: date, end: date) -> Optional[float]:
    try:
        series = _get_series(prices, ticker, "Close")
    except KeyError:
        return None
    slice_series = series.loc[start:end]
    if len(slice_series) < 2:
        return None
    returns = slice_series.pct_change().dropna()
    if returns.empty:
        return None
    return float(returns.std())


@dataclass
class RidgeModel:
    alpha: float = 1.0
    coef_: Optional[np.ndarray] = None

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        X_design = np.hstack([np.ones((X.shape[0], 1)), X])
        identity = np.eye(X_design.shape[1])
        identity[0, 0] = 0.0
        matrix = X_design.T @ X_design + self.alpha * identity
        self.coef_ = np.linalg.solve(matrix, X_design.T @ y)

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self.coef_ is None:
            raise ValueError("Model is not fitted")
        X_design = np.hstack([np.ones((X.shape[0], 1)), X])
        return X_design @ self.coef_


class MLBaseStrategy(BaseStrategy):
    """Base class for ML strategies."""

    def __init__(
        self,
        model_family: str = "ridge",
        train_window_days: int = 756,
        expanding: bool = False,
        min_train_rows: int = 200,
        refit_frequency: str = "every_decision",
        refit_n: int = 1,
        edge_floor: float = 0.0,
        top_k: int = 3,
        weighting: str = "equal",
        device: str = "cpu",
        cuda_ordinal: int = 0,
        xgb_params: Optional[dict] = None,
        ridge_alpha: float = 1.0,
    ) -> None:
        self.model_family = model_family
        self.train_window_days = train_window_days
        self.expanding = expanding
        self.min_train_rows = min_train_rows
        self.refit_frequency = refit_frequency
        self.refit_n = refit_n
        self.edge_floor = edge_floor
        self.top_k = top_k
        self.weighting = weighting
        self.device = device
        self.cuda_ordinal = cuda_ordinal
        self.xgb_params = xgb_params or {}
        self.ridge_alpha = ridge_alpha

        self._context: dict = {}
        self._model = None
        self._model_vol = None
        self._last_train_index: Optional[int] = None
        self._last_signals: dict = {}
        self._last_raw_weights: dict = {}
        self._last_forecasts: List[dict] = []
        self._last_training_info: dict = {}
        self._last_device: str = "cpu"
        self._last_fallback: Optional[str] = None

    def set_context(self, context: dict) -> None:
        self._context = context

    def get_last_signals(self) -> dict:
        return self._last_signals

    def get_last_raw_weights(self) -> dict:
        return self._last_raw_weights

    def get_last_forecasts(self) -> list[dict]:
        return self._last_forecasts

    def get_last_training_info(self) -> dict:
        return self._last_training_info

    def _should_refit(self, decision_index: int) -> bool:
        if self._model is None:
            return True
        if self.refit_frequency == "every_decision":
            return True
        if self.refit_frequency == "every_n_decisions":
            if self._last_train_index is None:
                return True
            return (decision_index - self._last_train_index) >= self.refit_n
        return False

    def _build_training_rows(self, as_of_date: date) -> List[tuple]:
        schedule = self._context.get("decision_schedule", [])
        universe = self._context.get("universe")
        data = self._context.get("data_by_date")
        if not schedule or universe is None or data is None:
            return []

        rows = []
        for idx in range(len(schedule) - 1):
            decision_date = schedule[idx]["decision_date"]
            next_fill_date = schedule[idx + 1]["fill_date"]
            if next_fill_date >= as_of_date:
                continue
            if not self.expanding:
                if (as_of_date - decision_date).days > self.train_window_days:
                    continue
            tickers = universe.get_eligible_tickers(decision_date)
            for ticker in tickers:
                features = _compute_features(data, ticker, decision_date)
                if features is None:
                    continue
                rows.append((decision_date, ticker, features, schedule[idx], schedule[idx + 1]))
        return rows

    def _train_model(self, X: np.ndarray, y: np.ndarray) -> tuple[object, str, Optional[str], Optional[dict]]:
        if self.model_family == "ridge":
            model = RidgeModel(alpha=self.ridge_alpha)
            model.fit(X, y)
            return model, "cpu", None, None

        if self.model_family == "xgboost":
            try:
                import xgboost as xgb
            except Exception as exc:
                raise ValueError("xgboost is not installed; install with extras [ml]") from exc

            params = {
                "objective": "reg:squarederror",
                "max_depth": 3,
                "learning_rate": 0.1,
                "n_estimators": 200,
                "subsample": 1.0,
                "colsample_bytree": 1.0,
                "reg_lambda": 1.0,
                "min_child_weight": 1.0,
                "random_state": 42,
                "nthread": 1,
                "tree_method": "hist",
            }
            params.update(self.xgb_params)

            device_used = "cpu"
            fallback_reason = None

            def train_with_device(device: str) -> xgb.XGBRegressor:
                model = xgb.XGBRegressor(**params, device=device)
                model.fit(X, y)
                return model

            if self.device == "cpu":
                model = train_with_device("cpu")
                device_used = "cpu"
            elif self.device == "cuda":
                device_name = f"cuda:{self.cuda_ordinal}"
                try:
                    model = train_with_device(device_name)
                except Exception as exc:
                    raise ValueError(f"CUDA requested but unavailable: {exc}") from exc
                device_used = device_name
            elif self.device == "auto":
                try:
                    device_name = f"cuda:{self.cuda_ordinal}"
                    model = train_with_device(device_name)
                    device_used = device_name
                except Exception as exc:
                    fallback_reason = str(exc)
                    model = train_with_device("cpu")
                    device_used = "cpu"
            else:
                raise ValueError(f"Unknown device setting: {self.device}")

            return model, device_used, fallback_reason, params

        raise ValueError(f"Unknown model_family: {self.model_family}")

    def _fit(self, decision_index: int, as_of_date: date, label_type: str) -> None:
        rows = self._build_training_rows(as_of_date)
        data = self._context.get("data_by_date")
        if not rows or data is None:
            self._model = None
            self._last_training_info = {
                "train_rows": 0,
                "feature_hash": _feature_hash(),
                "model_family": self.model_family,
                "device": "cpu",
                "fallback": None,
                "xgb_params": self.xgb_params if self.model_family == "xgboost" else None,
            }
            return

        X = []
        y = []
        for decision_date, ticker, features, schedule_curr, schedule_next in rows:
            fill_start = schedule_curr["fill_date"]
            fill_end = schedule_next["fill_date"]
            if label_type == "return":
                fill_field = self._context.get("fill_field", "Open")
                label = _interval_return(data, ticker, fill_start, fill_end, fill_field)
            else:
                label = _interval_vol(data, ticker, fill_start, fill_end)
            if label is None:
                continue
            X.append(features)
            y.append(label)

        if len(y) < self.min_train_rows:
            self._model = None
            self._last_training_info = {
                "train_rows": len(y),
                "feature_hash": _feature_hash(),
                "model_family": self.model_family,
                "device": "cpu",
                "fallback": None,
                "xgb_params": self.xgb_params if self.model_family == "xgboost" else None,
            }
            return

        X_arr = np.array(X)
        y_arr = np.array(y)
        model, device_used, fallback, params_used = self._train_model(X_arr, y_arr)
        self._model = model
        self._last_train_index = decision_index
        self._last_device = device_used
        self._last_fallback = fallback

        decision_dates = [row[0] for row in rows]
        self._last_training_info = {
            "train_rows": len(y),
            "train_start": min(decision_dates).isoformat() if decision_dates else None,
            "train_end": max(decision_dates).isoformat() if decision_dates else None,
            "feature_hash": _feature_hash(),
            "model_family": self.model_family,
            "device": device_used,
            "fallback": fallback,
            "xgb_params": params_used,
        }

    def _predict(self, as_of_date: date, eligible_tickers: List[str]) -> Dict[str, float]:
        data = self._context.get("data_by_date")
        if data is None or self._model is None:
            return {}
        predictions: Dict[str, float] = {}
        for ticker in eligible_tickers:
            features = _compute_features(data, ticker, as_of_date)
            if features is None:
                continue
            pred = float(self._model.predict(np.array([features]))[0])
            predictions[ticker] = pred
        return predictions

    def _expected_cost(self) -> float:
        costs = self._context.get("costs")
        if costs is None:
            return 0.0
        return float(costs.slippage_bps) / 10000.0


class MLReturnStrategy(MLBaseStrategy):
    """ML strategy predicting next-interval returns."""

    description = "Predict next-interval returns and allocate by edge."

    def compute_target_weights(
        self,
        as_of_date: date,
        eligible_tickers: List[str],
        prices: pd.DataFrame,
        positions: Dict[str, float],
    ) -> Dict[str, float]:
        decision_index = self._context.get("decision_index_map", {}).get(as_of_date)
        if decision_index is None:
            return {}

        if self._should_refit(decision_index):
            self._fit(decision_index, as_of_date, label_type="return")

        preds = self._predict(as_of_date, eligible_tickers)
        expected_cost = self._expected_cost()

        forecasts = []
        for ticker, mu in preds.items():
            net_edge = mu - expected_cost
            forecasts.append(
                {
                    "decision_date": as_of_date.isoformat(),
                    "ticker": ticker,
                    "mu": mu,
                    "sigma": None,
                    "expected_cost": expected_cost,
                    "net_edge": net_edge,
                    "score": net_edge,
                    "selected": False,
                }
            )

        if not forecasts:
            self._last_forecasts = []
            self._last_raw_weights = {}
            self._last_signals = {}
            return {}

        max_edge = max(item["net_edge"] for item in forecasts)
        if max_edge <= self.edge_floor:
            self._last_forecasts = forecasts
            self._last_raw_weights = {}
            self._last_signals = {"max_edge": max_edge}
            return {}

        ranked = sorted(forecasts, key=lambda item: item["net_edge"], reverse=True)
        selected = ranked[: self.top_k]

        if self.weighting == "score_softmax":
            scores = np.array([item["net_edge"] for item in selected])
            exp_scores = np.exp(scores - np.max(scores))
            weights = exp_scores / exp_scores.sum()
        else:
            weights = np.array([1.0 / len(selected)] * len(selected))

        target_weights = {}
        for item, weight in zip(selected, weights):
            item["selected"] = True
            target_weights[item["ticker"]] = float(weight)

        self._last_forecasts = forecasts
        self._last_raw_weights = target_weights
        self._last_signals = {"max_edge": max_edge}
        return target_weights


class MLVolStrategy(MLBaseStrategy):
    """ML strategy predicting next-interval volatility."""

    description = "Predict next-interval volatility and allocate to low-vol names."

    def compute_target_weights(
        self,
        as_of_date: date,
        eligible_tickers: List[str],
        prices: pd.DataFrame,
        positions: Dict[str, float],
    ) -> Dict[str, float]:
        decision_index = self._context.get("decision_index_map", {}).get(as_of_date)
        if decision_index is None:
            return {}

        if self._should_refit(decision_index):
            self._fit(decision_index, as_of_date, label_type="vol")

        preds = self._predict(as_of_date, eligible_tickers)
        forecasts = []
        for ticker, sigma in preds.items():
            score = 1.0 / max(sigma, 1e-6)
            forecasts.append(
                {
                    "decision_date": as_of_date.isoformat(),
                    "ticker": ticker,
                    "mu": None,
                    "sigma": sigma,
                    "expected_cost": 0.0,
                    "net_edge": 0.0,
                    "score": score,
                    "selected": False,
                }
            )

        if not forecasts:
            self._last_forecasts = []
            self._last_raw_weights = {}
            self._last_signals = {}
            return {}

        ranked = sorted(forecasts, key=lambda item: item["score"], reverse=True)
        selected = ranked[: self.top_k]

        if self.weighting == "inv_vol":
            total_score = sum(item["score"] for item in selected)
            weights = [item["score"] / total_score for item in selected] if total_score > 0 else []
        else:
            weights = [1.0 / len(selected)] * len(selected)

        target_weights = {}
        for item, weight in zip(selected, weights):
            item["selected"] = True
            target_weights[item["ticker"]] = float(weight)

        self._last_forecasts = forecasts
        self._last_raw_weights = target_weights
        self._last_signals = {}
        return target_weights


class MLRiskAdjustedStrategy(MLBaseStrategy):
    """ML strategy with risk-adjusted scoring."""

    description = "Predict return and volatility; allocate by risk-adjusted edge."

    def compute_target_weights(
        self,
        as_of_date: date,
        eligible_tickers: List[str],
        prices: pd.DataFrame,
        positions: Dict[str, float],
    ) -> Dict[str, float]:
        decision_index = self._context.get("decision_index_map", {}).get(as_of_date)
        if decision_index is None:
            return {}

        if self._should_refit(decision_index):
            self._fit(decision_index, as_of_date, label_type="return")
            self._model_vol = None
            self._fit_vol(decision_index, as_of_date)

        preds = self._predict(as_of_date, eligible_tickers)
        sigmas = self._predict_vol(as_of_date, eligible_tickers)
        expected_cost = self._expected_cost()

        forecasts = []
        for ticker, mu in preds.items():
            sigma = sigmas.get(ticker)
            if sigma is None:
                continue
            net_edge = mu - expected_cost
            score = net_edge / max(sigma, 1e-6)
            forecasts.append(
                {
                    "decision_date": as_of_date.isoformat(),
                    "ticker": ticker,
                    "mu": mu,
                    "sigma": sigma,
                    "expected_cost": expected_cost,
                    "net_edge": net_edge,
                    "score": score,
                    "selected": False,
                }
            )

        if not forecasts:
            self._last_forecasts = []
            self._last_raw_weights = {}
            self._last_signals = {}
            return {}

        max_edge = max(item["net_edge"] for item in forecasts)
        if max_edge <= self.edge_floor:
            for item in forecasts:
                item["selected"] = False
            self._last_forecasts = forecasts
            self._last_raw_weights = {}
            self._last_signals = {"max_edge": max_edge}
            return {}

        ranked = sorted(forecasts, key=lambda item: item["score"], reverse=True)
        selected = ranked[: self.top_k]

        scores = np.array([item["score"] for item in selected])
        if self.weighting == "score_softmax":
            exp_scores = np.exp(scores - np.max(scores))
            weights = exp_scores / exp_scores.sum()
        else:
            weights = np.array([1.0 / len(selected)] * len(selected))

        target_weights = {}
        for item, weight in zip(selected, weights):
            item["selected"] = True
            target_weights[item["ticker"]] = float(weight)

        self._last_forecasts = forecasts
        self._last_raw_weights = target_weights
        self._last_signals = {"max_edge": max_edge}
        return target_weights

    def _fit_vol(self, decision_index: int, as_of_date: date) -> None:
        rows = self._build_training_rows(as_of_date)
        data = self._context.get("data_by_date")
        if not rows or data is None:
            self._model_vol = None
            return

        X = []
        y = []
        for decision_date, ticker, features, schedule_curr, schedule_next in rows:
            fill_start = schedule_curr["fill_date"]
            fill_end = schedule_next["fill_date"]
            label = _interval_vol(data, ticker, fill_start, fill_end)
            if label is None:
                continue
            X.append(features)
            y.append(label)

        if len(y) < self.min_train_rows:
            self._model_vol = None
            return

        X_arr = np.array(X)
        y_arr = np.array(y)
        self._model_vol, _, _, _ = self._train_model(X_arr, y_arr)

    def _predict_vol(self, as_of_date: date, eligible_tickers: List[str]) -> Dict[str, float]:
        data = self._context.get("data_by_date")
        if data is None or self._model_vol is None:
            return {}
        predictions: Dict[str, float] = {}
        for ticker in eligible_tickers:
            features = _compute_features(data, ticker, as_of_date)
            if features is None:
                continue
            pred = float(self._model_vol.predict(np.array([features]))[0])
            predictions[ticker] = pred
        return predictions
