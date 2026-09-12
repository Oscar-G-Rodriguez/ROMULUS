"""Point-in-time feature alignment tests."""

from __future__ import annotations

import pandas as pd
import pytest
from datetime import date

from romulus.data.external_features import align_features_to_dates


def test_features_require_availability_date() -> None:
    with pytest.raises(ValueError, match="available"):
        align_features_to_dates(pd.DataFrame({"macro": [1.0]}, index=["2024-01-01"]), ["2024-01-02"])


def test_future_revision_cannot_change_prior_aligned_feature() -> None:
    source = pd.DataFrame(
        {
            "macro": [1.0, 999.0],
            "available_date": ["2024-01-05", "2024-02-05"],
        },
        index=["2024-01-01", "2024-01-01"],
    )
    aligned = align_features_to_dates(source, ["2024-01-10", "2024-02-10"])
    assert aligned.loc[date(2024, 1, 10), "macro"] == 1.0
    assert aligned.loc[date(2024, 2, 10), "macro"] == 999.0
