from typing import cast

import pandas as pd


def trailing_momentum(prices: pd.DataFrame, lookback_days: int) -> pd.DataFrame:
    """Past-only momentum; the signal observed at t is used from t+1."""
    if lookback_days < 2:
        raise ValueError("lookback_days must be at least 2")
    return cast(pd.DataFrame, prices.pct_change(lookback_days, fill_method=None))


def target_weights(momentum: pd.DataFrame, top_n: int, rebalance_days: int) -> pd.DataFrame:
    """Equal-weight the strongest positive assets on scheduled rebalance dates."""
    rebalance_index = momentum.index[::rebalance_days]
    scheduled = pd.DataFrame(0.0, index=rebalance_index, columns=momentum.columns)
    for date in rebalance_index:
        scores = momentum.loc[date].dropna()
        selected = scores[scores > 0].nlargest(top_n).index
        if len(selected):
            scheduled.loc[date, selected] = 1.0 / len(selected)
    return cast(pd.DataFrame, scheduled.reindex(momentum.index).ffill().fillna(0.0))
