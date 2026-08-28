from collections.abc import Iterable

import pandas as pd


def validate_prices(prices: pd.DataFrame) -> pd.DataFrame:
    """Return a clean price panel without silently filling missing observations."""
    if not isinstance(prices.index, pd.DatetimeIndex):
        raise TypeError("prices must use a DatetimeIndex")
    if prices.empty or prices.shape[1] < 2:
        raise ValueError("prices must contain at least two assets")
    if prices.index.has_duplicates or not prices.index.is_monotonic_increasing:
        raise ValueError("price index must be unique and increasing")
    clean = prices.astype(float).dropna(how="all")
    if (clean <= 0).any().any():
        raise ValueError("prices must be positive")
    return clean


def download_adjusted_close(
    tickers: Iterable[str], start: str, end: str | None = None
) -> pd.DataFrame:
    """Download adjusted prices. Network data is deliberately isolated here."""
    try:
        # yfinance does not publish typing metadata.
        import yfinance as yf  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("Install Qhapaq Finance with the 'data' extra") from exc

    symbols = list(dict.fromkeys(tickers))
    if len(symbols) < 2:
        raise ValueError("provide at least two unique tickers")
    raw = yf.download(symbols, start=start, end=end, auto_adjust=True, progress=False)
    if raw.empty:
        raise RuntimeError("the data provider returned no observations")
    close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
    close.columns = symbols if len(symbols) == close.shape[1] else close.columns
    return validate_prices(close)
