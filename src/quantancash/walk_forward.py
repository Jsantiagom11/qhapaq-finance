from collections.abc import Iterator
from dataclasses import dataclass

import pandas as pd

from .backtest import BacktestResult, run_backtest
from .config import ResearchConfig
from .data import validate_prices
from .metrics import performance_metrics


@dataclass(frozen=True)
class Fold:
    train: pd.DataFrame
    test: pd.DataFrame


def expanding_splits(
    data: pd.DataFrame, min_train_size: int = 252, test_size: int = 63
) -> Iterator[Fold]:
    """Yield chronological, non-overlapping test folds with expanding training data."""
    if min_train_size < 1 or test_size < 1:
        raise ValueError("split sizes must be positive")
    for test_start in range(min_train_size, len(data), test_size):
        test_end = min(test_start + test_size, len(data))
        yield Fold(train=data.iloc[:test_start].copy(), test=data.iloc[test_start:test_end].copy())


def run_walk_forward(
    prices: pd.DataFrame,
    config: ResearchConfig,
    *,
    min_train_size: int = 252,
    test_size: int = 63,
) -> BacktestResult:
    """Evaluate the fixed baseline on chronological, non-overlapping test windows."""
    clean = validate_prices(prices)
    folds = list(expanding_splits(clean, min_train_size=min_train_size, test_size=test_size))
    if not folds:
        raise ValueError("not enough observations for one walk-forward fold")

    test_returns: list[pd.DataFrame] = []
    test_weights: list[pd.DataFrame] = []
    for fold in folds:
        test_end = int(clean.index.searchsorted(fold.test.index[-1], side="right"))
        result = run_backtest(clean.iloc[:test_end], config)
        test_returns.append(result.returns.loc[fold.test.index])
        test_weights.append(result.weights.loc[fold.test.index])

    returns = pd.concat(test_returns).sort_index()
    weights = pd.concat(test_weights).sort_index()
    if returns.index.has_duplicates or weights.index.has_duplicates:
        raise RuntimeError("walk-forward test windows overlap")
    metrics = pd.DataFrame(
        {column: performance_metrics(returns[column], config.annualization) for column in returns}
    ).T
    return BacktestResult(returns=returns, weights=weights, metrics=metrics)
