import pandas as pd

from quantancash.walk_forward import expanding_splits


def test_splits_are_chronological_and_tests_do_not_overlap() -> None:
    data = pd.DataFrame({"x": range(20)})
    folds = list(expanding_splits(data, min_train_size=8, test_size=4))
    assert [len(fold.test) for fold in folds] == [4, 4, 4]
    assert all(fold.train.index.max() < fold.test.index.min() for fold in folds)
    test_indices = [index for fold in folds for index in fold.test.index]
    assert len(test_indices) == len(set(test_indices))

