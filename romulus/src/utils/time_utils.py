import pandas as pd

def purge_and_embargo_mask(timestamps: pd.Series, train_start, train_end, test_start, test_end, embargo_days: int):
    """
    Returns boolean masks for train/test given date ranges with embargo.
    timestamps: Series of pd.Timestamp
    """
    ts = pd.to_datetime(timestamps).dt.normalize()
    train_mask = (ts >= pd.to_datetime(train_start)) & (ts <= pd.to_datetime(train_end))
    test_mask  = (ts >= pd.to_datetime(test_start))  & (ts <= pd.to_datetime(test_end))
    # embargo: remove points within embargo_days after train_end from test
    embargo_end = pd.to_datetime(train_end) + pd.Timedelta(days=embargo_days)
    test_mask = test_mask & (ts > embargo_end)
    # purge: ensure no overlap
    train_mask = train_mask & ~test_mask
    return train_mask.values, test_mask.values
