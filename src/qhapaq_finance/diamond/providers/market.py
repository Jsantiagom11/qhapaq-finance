"""Provider-neutral market observation boundary for the Diamond Funnel."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol


class MarketProviderError(RuntimeError):
    """Raised when optional market evidence cannot be acquired safely."""


@dataclass(frozen=True, slots=True)
class MarketQuote:
    ticker: str
    price: float
    observed_on: date
    currency: str
    market_cap: float | None
    source_provider: str
    source_identity: str


class BatchMarketProvider(Protocol):
    provider_requests: int
    cache_hits: int
    cache_misses: int

    def quotes(self, tickers: tuple[str, ...], as_of: date) -> dict[str, MarketQuote]: ...
