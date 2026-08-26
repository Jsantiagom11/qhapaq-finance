import numpy as np
import pandas as pd

from quantancash.backtest import run_backtest
from quantancash.config import ResearchConfig


def synthetic_prices(rows: int = 180) -> pd.DataFrame:
    index = pd.date_range("2020-01-01", periods=rows, freq="B")
    return pd.DataFrame(
        {
            "UP": 100 * np.cumprod(np.full(rows, 1.001)),
            "FLAT": np.full(rows, 100.0),
            "DOWN": 100 * np.cumprod(np.full(rows, 0.999)),
        },
        index=index,
    )


def test_backtest_lags_signal_and_selects_positive_momentum() -> None:
    config = ResearchConfig(lookback_days=20, rebalance_days=10, top_n=1)
    result = run_backtest(synthetic_prices(), config)
    assert result.weights.iloc[:21].sum(axis=1).eq(0).all()
    assert result.weights.iloc[22:]["UP"].eq(1.0).all()
    assert result.weights.iloc[22:][["FLAT", "DOWN"]].eq(0.0).all().all()


def test_transaction_costs_reduce_returns() -> None:
    free = run_backtest(
        synthetic_prices(), ResearchConfig(lookback_days=20, rebalance_days=10, top_n=1)
    )
    costly = run_backtest(
        synthetic_prices(),
        ResearchConfig(lookback_days=20, rebalance_days=10, top_n=1, transaction_cost_bps=50),
    )
    assert costly.returns["strategy_net"].sum() < free.returns["strategy_net"].sum()


def test_cost_scenarios_degrade_monotonically() -> None:
    totals = [
        run_backtest(
            synthetic_prices(),
            ResearchConfig(lookback_days=20, rebalance_days=10, top_n=1, transaction_cost_bps=cost),
        )
        .returns["strategy_net"]
        .sum()
        for cost in [0, 10, 25, 50, 100]
    ]
    assert totals == sorted(totals, reverse=True)


def test_metrics_include_a_benchmark() -> None:
    result = run_backtest(synthetic_prices(), ResearchConfig(lookback_days=20))
    assert "equal_weight_benchmark" in result.metrics.index
    assert {"annual_return", "annual_volatility", "max_drawdown"} <= set(result.metrics)
