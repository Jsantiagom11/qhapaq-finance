import math

import pandas as pd
import pytest

from quantancash.metrics import performance_metrics


def test_sharpe_uses_arithmetic_mean_return_not_cagr() -> None:
    returns = pd.Series([0.01, -0.005, 0.02, -0.01])
    metrics = performance_metrics(returns, annualization=4)
    expected = returns.mean() * 4 / (returns.std(ddof=1) * math.sqrt(4))
    assert metrics["sharpe_zero_rf"] == pytest.approx(expected)


@pytest.mark.parametrize("returns", [[-1.0, 0.1], [float("inf"), 0.1]])
def test_impossible_or_non_finite_returns_are_rejected(returns) -> None:
    with pytest.raises(ValueError):
        performance_metrics(pd.Series(returns))


def test_zero_volatility_reports_undefined_sharpe() -> None:
    metrics = performance_metrics(pd.Series([0.0, 0.0, 0.0]))
    assert math.isnan(metrics["sharpe_zero_rf"])


def test_invalid_annualization_is_rejected() -> None:
    with pytest.raises(ValueError, match="annualization"):
        performance_metrics(pd.Series([0.1]), annualization=0)
