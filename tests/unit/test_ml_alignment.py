"""Unit tests for ML label alignment rules."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from romulus.config.schema import CostConfig
from romulus.data.universe import Universe, UniverseEntry
from romulus.strategy import ml as ml_module
from romulus.strategy.ml import BASE_FEATURE_NAMES, MLReturnStrategy


def test_ml_training_rows_require_full_interval(monkeypatch) -> None:
    schedule = [
        {"decision_date": date(2024, 1, 3), "fill_date": date(2024, 1, 4)},
        {"decision_date": date(2024, 1, 5), "fill_date": date(2024, 1, 8)},
    ]

    fields = ["Open", "Close", "High", "Low", "Volume"]
    index = [date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5), date(2024, 1, 8)]
    columns = pd.MultiIndex.from_product([["SPY"], fields])
    data = pd.DataFrame(index=index, columns=columns, dtype=float)
    for i, day in enumerate(index):
        base = 100 + i
        data.loc[day, ("SPY", "Open")] = base
        data.loc[day, ("SPY", "Close")] = base + 1
        data.loc[day, ("SPY", "High")] = base + 2
        data.loc[day, ("SPY", "Low")] = base - 1
        data.loc[day, ("SPY", "Volume")] = 1_000_000 + i

    universe = Universe([UniverseEntry(ticker="SPY", name="SPY", inception_date=date(2000, 1, 1))])

    strategy = MLReturnStrategy(
        model_family="ridge",
        min_train_rows=1,
        train_window_days=1000,
        device="cpu",
        embargo_intervals=0,
    )
    strategy.set_context(
        {
            "decision_schedule": schedule,
            "decision_index_map": {entry["decision_date"]: idx for idx, entry in enumerate(schedule)},
            "universe": universe,
            "data_by_date": data,
            "costs": CostConfig(),
        }
    )

    monkeypatch.setattr(
        strategy,
        "_compute_feature_vector",
        lambda prices, ticker, as_of: np.zeros(len(BASE_FEATURE_NAMES)),
    )

    rows = strategy._build_training_rows(1, date(2024, 1, 5))
    assert rows == []

    rows_late = strategy._build_training_rows(1, date(2024, 1, 9))
    assert len(rows_late) == 1
    assert rows_late[0][0] == date(2024, 1, 3)
