"""Cached Yahoo Finance split adjustment evidence."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import urlencode

from ..cache import DiamondCache
from .market import MarketProviderError, SplitCoverage
from .yahoo import YahooJsonClient


class YahooSplitProviderError(MarketProviderError):
    """Raised when Yahoo split evidence cannot be acquired or parsed safely."""


def _canonical_ticker(ticker: str) -> str:
    canonical = ticker.strip().upper()
    if not canonical:
        raise YahooSplitProviderError("YAHOO_SPLIT_TICKER_INVALID")
    return canonical


def _yahoo_symbol(ticker: str) -> str:
    return ticker.replace(".", "-")


def _utc_timestamp(value: date) -> int:
    return int(datetime.combine(value, time.min, tzinfo=timezone.utc).timestamp())


def _positive_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number > 0 else None


def _utc_date(value: object) -> date | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    try:
        return datetime.fromtimestamp(number, tz=timezone.utc).date()
    except (OverflowError, OSError, ValueError):
        return None


class YahooSplitAdjustmentProvider:
    """Acquire and cache exact-interval split coverage from Yahoo charts."""

    BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
    PROVIDER = "yahoo-finance"

    def __init__(
        self,
        *,
        client: YahooJsonClient | None,
        cache: DiamondCache,
        refresh: bool = False,
    ) -> None:
        self._client = client
        self._cache = cache
        self._refresh = refresh
        self.provider_requests = 0
        self.cache_hits = 0
        self.cache_misses = 0

    @classmethod
    def _url(cls, ticker: str, start_date: date, end_date: date) -> str:
        query = urlencode(
            {
                "period1": _utc_timestamp(start_date),
                "period2": _utc_timestamp(end_date + timedelta(days=1)),
                "interval": "1d",
                "events": "splits",
            }
        )
        return f"{cls.BASE_URL}/{_yahoo_symbol(ticker)}?{query}"

    def _fetch(self, url: str, as_of: date) -> tuple[object, str]:
        if not self._refresh:
            cached = self._cache.load(url)
            if cached is not None and cached.data_as_of == as_of:
                if cached.provider != self.PROVIDER:
                    raise YahooSplitProviderError("YAHOO_SPLIT_CACHE_PROVIDER_MISMATCH")
                self.cache_hits += 1
                return cached.payload, cached.payload_sha256

        self.cache_misses += 1
        if self._client is None:
            raise YahooSplitProviderError("YAHOO_SPLIT_CACHE_MISS_REQUIRES_NETWORK")
        self.provider_requests += 1
        try:
            payload = self._client.get_json(url)
        except MarketProviderError as exc:
            raise YahooSplitProviderError("YAHOO_SPLIT_REQUEST_FAILED") from exc
        stored = self._cache.store(
            url,
            provider=self.PROVIDER,
            data_as_of=as_of,
            payload=payload,
        )
        return stored.payload, stored.payload_sha256

    @staticmethod
    def _parse(
        payload: object,
        *,
        ticker: str,
        start_date: date,
        end_date: date,
        source_identity: str,
    ) -> SplitCoverage:
        if not isinstance(payload, Mapping):
            raise YahooSplitProviderError("YAHOO_SPLIT_SCHEMA_INVALID")
        chart = payload.get("chart")
        if not isinstance(chart, Mapping) or chart.get("error") is not None:
            raise YahooSplitProviderError("YAHOO_SPLIT_SCHEMA_INVALID")
        results = chart.get("result")
        if not isinstance(results, list) or not results or not isinstance(results[0], Mapping):
            raise YahooSplitProviderError("YAHOO_SPLIT_SCHEMA_INVALID")

        result = results[0]
        events = result.get("events")
        if events is None:
            split_events: object = {}
        elif isinstance(events, Mapping):
            split_events = events.get("splits", {})
        else:
            raise YahooSplitProviderError("YAHOO_SPLIT_EVENTS_INVALID")
        if not isinstance(split_events, Mapping):
            raise YahooSplitProviderError("YAHOO_SPLIT_EVENTS_INVALID")

        cumulative_factor = 1.0
        event_dates: list[date] = []
        for event in split_events.values():
            if not isinstance(event, Mapping):
                raise YahooSplitProviderError("YAHOO_SPLIT_EVENT_INVALID")
            event_date = _utc_date(event.get("date"))
            numerator = _positive_number(event.get("numerator"))
            denominator = _positive_number(event.get("denominator"))
            if event_date is None or numerator is None or denominator is None:
                raise YahooSplitProviderError("YAHOO_SPLIT_EVENT_INVALID")
            if start_date <= event_date <= end_date:
                cumulative_factor *= numerator / denominator
                event_dates.append(event_date)

        return SplitCoverage(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            cumulative_factor=cumulative_factor,
            source_provider=YahooSplitAdjustmentProvider.PROVIDER,
            source_identity=source_identity,
            event_dates=tuple(sorted(event_dates)),
        )

    def coverage(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
        as_of: date,
    ) -> SplitCoverage:
        canonical = _canonical_ticker(ticker)
        if start_date > end_date:
            raise YahooSplitProviderError("YAHOO_SPLIT_INTERVAL_INVALID")
        url = self._url(canonical, start_date, end_date)
        payload, source_identity = self._fetch(url, as_of)
        return self._parse(
            payload,
            ticker=canonical,
            start_date=start_date,
            end_date=end_date,
            source_identity=source_identity,
        )
