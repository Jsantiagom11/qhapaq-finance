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


@dataclass(frozen=True, slots=True)
class SplitCoverage:
    ticker: str
    start_date: date
    end_date: date
    cumulative_factor: float
    source_provider: str
    source_identity: str
    event_dates: tuple[date, ...] = ()


@dataclass(frozen=True, slots=True)
class MarketCapDecision:
    market_cap: float | None
    diagnostic: str | None


class BatchMarketProvider(Protocol):
    provider_requests: int
    cache_hits: int
    cache_misses: int

    def quotes(self, tickers: tuple[str, ...], as_of: date) -> dict[str, MarketQuote]: ...


class SplitAdjustmentProvider(Protocol):
    provider_requests: int
    cache_hits: int
    cache_misses: int

    def coverage(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
        as_of: date,
    ) -> SplitCoverage | None: ...


def derive_safe_market_cap(
    *,
    quote: MarketQuote,
    shares: float | None,
    shares_observed_on: date | None,
    split_coverage: SplitCoverage | None,
) -> MarketCapDecision:
    if quote.market_cap is not None:
        return MarketCapDecision(quote.market_cap, None)
    if shares is None or shares_observed_on is None:
        return MarketCapDecision(None, None)
    if shares_observed_on > quote.observed_on:
        return MarketCapDecision(None, "MARKET_CAP_TEMPORAL_MISMATCH")
    if shares_observed_on == quote.observed_on:
        return MarketCapDecision(quote.price * shares, None)
    if (
        split_coverage is not None
        and split_coverage.ticker == quote.ticker
        and split_coverage.start_date == shares_observed_on
        and split_coverage.end_date == quote.observed_on
        and shares_observed_on not in split_coverage.event_dates
    ):
        adjusted_shares = shares * split_coverage.cumulative_factor
        return MarketCapDecision(quote.price * adjusted_shares, None)
    return MarketCapDecision(None, "MARKET_CAP_SPLIT_UNVERIFIED")
