"""Unit tests for ETF universe handling."""

from datetime import date

from romulus.data.universe import Universe


def test_inception_gating_tlt() -> None:
    """Verify TLT is not eligible before its inception date."""
    universe = Universe.load_from_json("configs/universe_default.json")
    eligible = universe.get_eligible_tickers(date(2002, 7, 25))

    assert "TLT" not in eligible


def test_all_eligible_after_latest_inception() -> None:
    """Verify all ETFs are eligible after the latest inception date."""
    universe = Universe.load_from_json("configs/universe_default.json")
    eligible = universe.get_eligible_tickers(date(2002, 7, 27))

    assert set(eligible) == {"SPY", "QQQ", "IWM", "TLT"}
