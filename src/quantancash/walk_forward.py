from collections.abc import Iterator
from dataclasses import dataclass

import pandas as pd


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

