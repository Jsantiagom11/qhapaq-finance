from collections.abc import Iterable
from typing import cast

import pandas as pd


def validate_prices(prices: pd.DataFrame, *, allow_missing: bool = False) -> pd.DataFrame:
    """Return a clean price panel without silently filling missing observations."""
    if not isinstance(prices.index, pd.DatetimeIndex):
        raise TypeError("prices must use a DatetimeIndex")
    if prices.empty or prices.shape[1] < 2:
        raise ValueError("prices must contain at least two assets")
    if prices.index.has_duplicates or not prices.index.is_monotonic_increasing:
        raise ValueError("price index must be unique and increasing")
    clean = prices.astype(float).dropna(how="all")
    if not clean.columns.is_unique:
        raise ValueError("asset columns must be unique")
    if not allow_missing and clean.isna().any().any():
        missing = clean.isna().sum()
        affected = ", ".join(f"{name}={count}" for name, count in missing.items() if count)
        raise ValueError(f"prices contain missing observations: {affected}")
    if (clean <= 0).any().any():
        raise ValueError("prices must be positive")
    return cast(pd.DataFrame, clean)


def download_adjusted_close(
    tickers: Iterable[str], start: str, end: str | None = None
) -> pd.DataFrame:
    """Download adjusted prices. Network data is deliberately isolated here."""
    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("Install QuantAncash with the 'data' extra") from exc

    symbols = list(dict.fromkeys(tickers))
    if len(symbols) < 2:
        raise ValueError("provide at least two unique tickers")
    raw = yf.download(
        symbols,
        start=start,
        end=end,
        auto_adjust=True,
        progress=False,
        threads=False,
        timeout=10,
    )
    if raw.empty:
        raise RuntimeError("the data provider returned no observations")
    close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
    if not isinstance(close, pd.DataFrame):
        close = close.to_frame()
    missing_symbols = [symbol for symbol in symbols if symbol not in close.columns]
    if missing_symbols:
        raise RuntimeError(f"the data provider omitted requested symbols: {missing_symbols}")
    close = close.reindex(columns=symbols)
    return validate_prices(close)
