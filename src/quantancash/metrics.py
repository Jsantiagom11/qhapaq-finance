import math

import numpy as np
import pandas as pd


def performance_metrics(returns: pd.Series, annualization: int = 252) -> dict[str, float]:
    if annualization < 1:
        raise ValueError("annualization must be positive")
    clean = returns.dropna().astype(float)
    if clean.empty:
        raise ValueError("returns cannot be empty")
    if not np.isfinite(clean).all():
        raise ValueError("returns must be finite")
    if (clean <= -1).any():
        raise ValueError("returns must be greater than -100%")
    equity = (1.0 + clean).cumprod()
    years = len(clean) / annualization
    annual_return = equity.iloc[-1] ** (1 / years) - 1 if years > 0 else math.nan
    annual_vol = clean.std(ddof=1) * np.sqrt(annualization)
    annual_mean = clean.mean() * annualization
    sharpe = annual_mean / annual_vol if annual_vol > 0 else math.nan
    drawdown = equity / equity.cummax() - 1.0
    return {
        "total_return": float(equity.iloc[-1] - 1.0),
        "annual_return": float(annual_return),
        "annual_volatility": float(annual_vol),
        "sharpe_zero_rf": float(sharpe),
        "max_drawdown": float(drawdown.min()),
    }
