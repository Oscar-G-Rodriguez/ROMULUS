"""Data-coverage and bounded-date tests."""

from datetime import date

import pandas as pd

from romulus.data.coverage import build_coverage_index, inspect_cached_coverage, snap_date


def _frame() -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", "2024-01-12")
    columns = pd.MultiIndex.from_product([["SPY", "NEW"], ["Open", "Close", "High", "Low", "Volume"]])
    data = pd.DataFrame(100.0, index=dates, columns=columns)
    data.loc[dates[:3], "NEW"] = float("nan")
    return data


def test_dynamic_and_common_coverage_bound_staggered_inception() -> None:
    dynamic = build_coverage_index(_frame(), ["SPY", "NEW"], source="synthetic", policy="dynamic")
    common = build_coverage_index(_frame(), ["SPY", "NEW"], source="synthetic", policy="common")

    assert dynamic.minimum_date == "2024-01-01"
    assert common.minimum_date == "2024-01-04"
    assert dynamic.maximum_date == common.maximum_date == "2024-01-12"


def test_snap_date_respects_direction_and_rejects_out_of_range() -> None:
    available = [date(2024, 1, 5), date(2024, 1, 8)]
    assert snap_date(date(2024, 1, 6), available, "forward") == date(2024, 1, 8)
    assert snap_date(date(2024, 1, 6), available, "backward") == date(2024, 1, 5)


def test_cached_coverage_normalizes_single_ticker_files(tmp_path) -> None:
    raw = _frame().loc[:, "SPY"]
    raw.to_parquet(tmp_path / "SPY_2024-01-01_2024-01-12.parquet")

    coverage = inspect_cached_coverage(tmp_path, ["SPY"])

    assert coverage.minimum_date == "2024-01-01"
    assert coverage.maximum_date == "2024-01-12"
    assert coverage.tickers[0].observations == len(raw)


def test_minimum_observations_bounds_start_after_regime_warmup() -> None:
    coverage = build_coverage_index(
        _frame(), ["SPY", "NEW"], source="synthetic", policy="dynamic", minimum_observations=4
    )

    assert coverage.minimum_date == "2024-01-04"
