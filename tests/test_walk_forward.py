import numpy as np
import pandas as pd
import pytest

from quantancash.config import ResearchConfig
from quantancash.walk_forward import expanding_splits, run_walk_forward


def test_splits_are_chronological_and_tests_do_not_overlap() -> None:
    data = pd.DataFrame({"x": range(20)})
    folds = list(expanding_splits(data, min_train_size=8, test_size=4))
    assert [len(fold.test) for fold in folds] == [4, 4, 4]
    assert all(fold.train.index.max() < fold.test.index.min() for fold in folds)
    test_indices = [index for fold in folds for index in fold.test.index]
    assert len(test_indices) == len(set(test_indices))


def test_walk_forward_emits_only_non_overlapping_out_of_sample_rows() -> None:
    rows = 80
    index = pd.date_range("2020-01-01", periods=rows, freq="B")
    prices = pd.DataFrame(
        {
            "UP": 100 * np.cumprod(np.full(rows, 1.001)),
            "DOWN": 100 * np.cumprod(np.full(rows, 0.999)),
        },
        index=index,
    )
    result = run_walk_forward(
        prices,
        ResearchConfig(lookback_days=10, rebalance_days=5, top_n=1),
        min_train_size=40,
        test_size=15,
    )
    assert result.returns.index.equals(index[40:])
    assert result.returns.index.is_unique
    assert result.weights.index.equals(result.returns.index)
    assert "equal_weight_benchmark" in result.metrics.index


def test_walk_forward_requires_at_least_one_test_fold() -> None:
    index = pd.date_range("2020-01-01", periods=10, freq="B")
    prices = pd.DataFrame({"A": range(10, 20), "B": range(20, 30)}, index=index)
    with pytest.raises(ValueError, match="not enough observations"):
        run_walk_forward(prices, ResearchConfig(lookback_days=2), min_train_size=10)
