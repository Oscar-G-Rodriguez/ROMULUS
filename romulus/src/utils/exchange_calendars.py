import pandas as pd
import pandas_market_calendars as mcal

def get_calendar(market: str = "NYSE", start: str = "1990-01-01", end: str = None) -> pd.DatetimeIndex:
    """
    Return valid trading days for the given market using pandas_market_calendars.
    Falls back to weekday calendar if package or schedule unavailable.
    """
    if end is None:
        end = pd.Timestamp.today().strftime("%Y-%m-%d")

    try:
        cal = mcal.get_calendar(market)
        sched = cal.schedule(start_date=start, end_date=end)
        return mcal.date_range(sched, frequency="1D")
    except Exception as e:
        print(f"Warning: fallback weekday calendar ({e})")
        return pd.date_range(start=start, end=end, freq="B")
