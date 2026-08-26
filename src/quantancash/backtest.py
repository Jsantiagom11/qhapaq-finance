from dataclasses import dataclass

import pandas as pd

from .config import ResearchConfig
from .data import validate_prices
from .metrics import performance_metrics
from .signals import target_weights, trailing_momentum


@dataclass(frozen=True)
class BacktestResult:
    returns: pd.DataFrame
    weights: pd.DataFrame
    metrics: pd.DataFrame


def run_backtest(prices: pd.DataFrame, config: ResearchConfig) -> BacktestResult:
    """Compare a past-only momentum rule with an equal-weight benchmark."""
    clean = validate_prices(prices)
    asset_returns = clean.pct_change(fill_method=None).fillna(0.0)
    signal = trailing_momentum(clean, config.lookback_days)

    # One-day lag prevents using today's close to earn today's return.
    weights = target_weights(signal, config.top_n, config.rebalance_days).shift(1).fillna(0.0)
    gross = (weights * asset_returns).sum(axis=1)
    turnover = weights.diff().abs().sum(axis=1).fillna(weights.abs().sum(axis=1))
    net = gross - turnover * config.transaction_cost

    benchmark_weights = clean.notna().div(clean.notna().sum(axis=1), axis=0)
    benchmark = (benchmark_weights.shift(1).fillna(0.0) * asset_returns).sum(axis=1)
    result_returns = pd.DataFrame(
        {"strategy_gross": gross, "strategy_net": net, "equal_weight_benchmark": benchmark}
    )
    metrics = pd.DataFrame(
        {
            column: performance_metrics(result_returns[column], config.annualization)
            for column in result_returns
        }
    ).T
    return BacktestResult(returns=result_returns, weights=weights, metrics=metrics)
