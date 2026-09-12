"""Hand-calculated ML target tests."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from romulus.strategy.ml import _interval_vol


def test_realized_interval_volatility_is_root_sum_squared_log_returns() -> None:
    dates = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 5)]
    columns = pd.MultiIndex.from_product([["AAA"], ["Close"]])
    data = pd.DataFrame([100.0, 110.0, 99.0], index=dates, columns=columns)
    expected = np.sqrt(np.log(1.1) ** 2 + np.log(0.9) ** 2)

    assert _interval_vol(data, "AAA", dates[0], dates[-1]) == pytest.approx(expected)
