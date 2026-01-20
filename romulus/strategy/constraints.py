"""Portfolio weight constraint helpers."""

from __future__ import annotations

from typing import Dict, Tuple


def compute_current_weights(
    positions: Dict[str, float],
    cash: float,
    prices: Dict[str, float],
) -> Dict[str, float]:
    """Compute current weights including cash."""
    total_value = cash + sum(positions.get(ticker, 0.0) * prices.get(ticker, 0.0) for ticker in prices)
    if total_value <= 0:
        return {"cash_weight": 1.0}

    weights = {"cash_weight": cash / total_value}
    for ticker, shares in positions.items():
        price = prices.get(ticker)
        if price is None:
            continue
        weights[ticker] = (shares * price) / total_value
    return weights


def apply_weight_constraints(
    raw_weights: Dict[str, float],
    current_weights: Dict[str, float],
    max_weight: float,
    turnover_cap: float,
) -> Tuple[Dict[str, float], Dict[str, float]]:
    """Apply long-only, max-weight, and turnover constraints."""
    clean = {ticker: max(0.0, weight) for ticker, weight in raw_weights.items() if ticker != "cash_weight"}

    total = sum(clean.values())
    if total > 1.0:
        scale = 1.0 / total
        clean = {ticker: weight * scale for ticker, weight in clean.items()}

    capped = {ticker: min(weight, max_weight) for ticker, weight in clean.items()}
    capped_total = sum(capped.values())
    if capped_total > 1.0:
        scale = 1.0 / capped_total
        capped = {ticker: weight * scale for ticker, weight in capped.items()}
        capped_total = sum(capped.values())

    target_cash = max(0.0, 1.0 - capped_total)

    target_with_cash = {**capped, "cash_weight": target_cash}
    for ticker in list(current_weights.keys()):
        if ticker not in target_with_cash:
            target_with_cash[ticker] = 0.0

    turnover_pre = 0.5 * sum(
        abs(target_with_cash[ticker] - current_weights.get(ticker, 0.0))
        for ticker in target_with_cash
    )

    scale_factor = 1.0
    if turnover_cap is not None and turnover_cap >= 0 and turnover_pre > turnover_cap:
        scale_factor = turnover_cap / turnover_pre if turnover_pre > 0 else 1.0
        adjusted = {}
        for ticker, target_weight in target_with_cash.items():
            adjusted[ticker] = current_weights.get(ticker, 0.0) + scale_factor * (
                target_weight - current_weights.get(ticker, 0.0)
            )
        target_with_cash = adjusted
        turnover_post = 0.5 * sum(
            abs(target_with_cash[ticker] - current_weights.get(ticker, 0.0))
            for ticker in target_with_cash
        )
    else:
        turnover_post = turnover_pre

    constrained = {ticker: weight for ticker, weight in target_with_cash.items() if ticker != "cash_weight"}
    return constrained, {
        "cash_weight": target_with_cash.get("cash_weight", 0.0),
        "turnover_pre": turnover_pre,
        "turnover_post": turnover_post,
        "scale_factor": scale_factor,
    }
