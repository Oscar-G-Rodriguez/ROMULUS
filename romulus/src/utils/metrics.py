import numpy as np
import pandas as pd
from scipy.stats import spearmanr, pearsonr

def sharpe_ratio(returns: pd.Series, risk_free: float = 0.0, periods_per_year: int = 252) -> float:
    r = pd.Series(returns).dropna()
    if r.std(ddof=0) == 0:
        return np.nan
    excess = r - risk_free/periods_per_year
    return np.sqrt(periods_per_year) * excess.mean() / excess.std(ddof=0)

def max_drawdown(returns: pd.Series) -> float:
    # returns are arithmetic (not log). Computes drawdown of cumulative curve.
    r = pd.Series(returns).fillna(0.0)
    equity = (1 + r).cumprod()
    peak = equity.cummax()
    dd = (equity / peak) - 1.0
    return dd.min()

def information_coefficient(y_true: pd.Series, y_pred: pd.Series, method: str = "spearman") -> float:
    x = pd.concat([pd.Series(y_true), pd.Series(y_pred)], axis=1).dropna()
    if len(x) < 3:
        return np.nan
    if method == "pearson":
        return pearsonr(x.iloc[:,0], x.iloc[:,1])[0]
    return spearmanr(x.iloc[:,0], x.iloc[:,1], nan_policy="omit")[0]

def rmse(y_true: pd.Series, y_pred: pd.Series) -> float:
    x = pd.concat([pd.Series(y_true), pd.Series(y_pred)], axis=1).dropna()
    if len(x) == 0:
        return np.nan
    diff = x.iloc[:,0] - x.iloc[:,1]
    return float(np.sqrt(np.mean(np.square(diff))))
