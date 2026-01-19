"""Unit tests for data ingestion and caching."""

from __future__ import annotations

from typing import List

import pandas as pd
import pytest

from romulus.data.ingestion import fetch_daily_data


@pytest.fixture()
def sample_df() -> pd.DataFrame:
    index = pd.date_range("2020-01-01", periods=2, freq="D")
    return pd.DataFrame(
        {"Open": [1.0, 2.0], "Close": [1.5, 2.5]},
        index=index,
    )


def test_data_fetch_and_cache(tmp_path, monkeypatch, sample_df) -> None:
    calls: List[str] = []

    def fake_download(*args, **kwargs):
        calls.append("called")
        return sample_df

    monkeypatch.setattr("romulus.data.ingestion.yf.download", fake_download)

    result = fetch_daily_data(
        ["SPY"],
        start="2020-01-01",
        end="2020-01-03",
        cache_dir=str(tmp_path),
    )

    cache_file = tmp_path / "SPY_2020-01-01_2020-01-03.parquet"
    checksum_file = tmp_path / "checksums.json"

    assert cache_file.exists()
    assert checksum_file.exists()
    assert calls == ["called"]
    assert "SPY" in result.columns.get_level_values(0)


def test_cache_hit_skip_download(tmp_path, monkeypatch, sample_df) -> None:
    cache_file = tmp_path / "SPY_2020-01-01_2020-01-03.parquet"
    sample_df.to_parquet(cache_file)

    def fail_download(*args, **kwargs):
        raise AssertionError("Download should not be called on cache hit")

    monkeypatch.setattr("romulus.data.ingestion.yf.download", fail_download)

    result = fetch_daily_data(
        ["SPY"],
        start="2020-01-01",
        end="2020-01-03",
        cache_dir=str(tmp_path),
    )

    assert "SPY" in result.columns.get_level_values(0)
