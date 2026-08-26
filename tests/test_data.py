import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quantancash.data import download_adjusted_close, validate_prices


def prices() -> pd.DataFrame:
    return pd.DataFrame(
        {"AAA": [10.0, 11.0, 12.0], "BBB": [20.0, 19.0, 18.0]},
        index=pd.date_range("2026-01-01", periods=3, freq="B"),
    )


def test_missing_prices_are_rejected_by_default_and_can_be_explicitly_inspected() -> None:
    panel = prices()
    panel.loc[panel.index[1], "BBB"] = np.nan
    with pytest.raises(ValueError, match="BBB=1"):
        validate_prices(panel)
    accepted = validate_prices(panel, allow_missing=True)
    assert accepted.isna().sum()["BBB"] == 1


def test_duplicate_asset_columns_are_rejected() -> None:
    panel = prices()
    panel.columns = ["AAA", "AAA"]
    with pytest.raises(ValueError, match="columns must be unique"):
        validate_prices(panel)


def test_provider_column_order_never_changes_ticker_identity(monkeypatch) -> None:
    index = pd.date_range("2026-01-01", periods=3, freq="B")
    columns = pd.MultiIndex.from_product([["Close"], ["BBB", "AAA"]])
    raw = pd.DataFrame([[200, 100], [201, 101], [202, 102]], index=index, columns=columns)
    fake = SimpleNamespace(download=lambda *args, **kwargs: raw)
    monkeypatch.setitem(sys.modules, "yfinance", fake)

    result = download_adjusted_close(["AAA", "BBB"], "2026-01-01")

    assert list(result.columns) == ["AAA", "BBB"]
    assert result.iloc[0].to_dict() == {"AAA": 100.0, "BBB": 200.0}


def test_provider_omitting_a_requested_symbol_fails_loudly(monkeypatch) -> None:
    index = pd.date_range("2026-01-01", periods=3, freq="B")
    columns = pd.MultiIndex.from_product([["Close"], ["AAA"]])
    raw = pd.DataFrame([[100], [101], [102]], index=index, columns=columns)
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=lambda *a, **k: raw))

    with pytest.raises(RuntimeError, match="BBB"):
        download_adjusted_close(["AAA", "BBB"], "2026-01-01")
