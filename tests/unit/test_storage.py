"""Unit tests for storage utilities."""

from __future__ import annotations

import pandas as pd

from romulus.data.storage import (
    compute_dataframe_hash,
    load_json,
    load_parquet,
    save_json,
    save_parquet,
)


def test_parquet_roundtrip(tmp_path) -> None:
    df = pd.DataFrame({"a": [1, 2], "b": [3.0, 4.0]})
    path = tmp_path / "sample.parquet"

    save_parquet(df, str(path))
    loaded = load_parquet(str(path))

    assert df.equals(loaded)


def test_json_roundtrip(tmp_path) -> None:
    data = {"alpha": 1, "beta": {"gamma": 2}}
    path = tmp_path / "sample.json"

    save_json(data, str(path))
    loaded = load_json(str(path))

    assert data == loaded


def test_compute_dataframe_hash_stable(tmp_path) -> None:
    df = pd.DataFrame({"a": [1, 2], "b": [3.0, 4.0]})
    first = compute_dataframe_hash(df)
    second = compute_dataframe_hash(df.copy())

    assert first == second
