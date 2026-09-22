"""Key-free cached batch price observations from Yahoo Finance."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from http.client import HTTPConnection, HTTPSConnection
from typing import Protocol
from urllib.parse import urlencode, urlsplit

from ..cache import DiamondCache
from .market import MarketProviderError, MarketQuote


class YahooProviderError(MarketProviderError):
    """Raised when Yahoo market evidence cannot be acquired or parsed safely."""


@dataclass(frozen=True, slots=True)
class YahooResponse:
    status_code: int
    headers: Mapping[str, str]
    content: bytes


class YahooTransport(Protocol):
    def __call__(
        self,
        url: str,
        headers: Mapping[str, str],
        connect_timeout: float,
        read_timeout: float,
    ) -> YahooResponse: ...


class YahooJsonClient(Protocol):
    def get_json(self, url: str) -> object: ...


def _stdlib_get(
    url: str,
    headers: Mapping[str, str],
    connect_timeout: float,
    read_timeout: float,
) -> YahooResponse:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("Yahoo URL must be absolute HTTP(S)")
    connection_type = HTTPSConnection if parts.scheme == "https" else HTTPConnection
    target = parts.path or "/"
    if parts.query:
        target = f"{target}?{parts.query}"
    connection = connection_type(parts.hostname, parts.port, timeout=connect_timeout)
    try:
        connection.request("GET", target, headers=dict(headers))
        if connection.sock is not None:
            connection.sock.settimeout(read_timeout)
        response = connection.getresponse()
        return YahooResponse(response.status, dict(response.getheaders()), response.read())
    finally:
        connection.close()


class YahooClient:
    def __init__(
        self,
        *,
        transport: YahooTransport = _stdlib_get,
        connect_timeout: float = 5.0,
        read_timeout: float = 30.0,
        max_retries: int = 2,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if connect_timeout <= 0 or read_timeout <= 0 or max_retries < 0:
            raise ValueError("invalid Yahoo client settings")
        self._transport = transport
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._max_retries = max_retries
        self._sleep = sleep

    def get_json(self, url: str) -> object:
        for attempt in range(self._max_retries + 1):
            try:
                response = self._transport(
                    url,
                    {"User-Agent": "Mozilla/5.0 QhapaqFinance/0.2"},
                    self._connect_timeout,
                    self._read_timeout,
                )
            except OSError as exc:
                if attempt < self._max_retries:
                    self._sleep(0.5 * (2**attempt))
                    continue
                raise YahooProviderError("YAHOO_REQUEST_FAILED") from exc
            retryable = response.status_code == 429 or 500 <= response.status_code <= 599
            if retryable and attempt < self._max_retries:
                self._sleep(0.5 * (2**attempt))
                continue
            if not 200 <= response.status_code < 300:
                raise YahooProviderError(f"YAHOO_HTTP_ERROR:{response.status_code}")
            try:
                return json.loads(response.content.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise YahooProviderError("YAHOO_RESPONSE_INVALID_JSON") from exc
        raise AssertionError("unreachable")


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if number > 0 else None


def _canonical_symbol(ticker: str) -> str:
    return ticker.strip().upper()


def _yahoo_symbol(ticker: str) -> str:
    return _canonical_symbol(ticker).replace(".", "-")


class YahooBatchMarketProvider:
    """Acquire chunked multi-symbol daily prices through Yahoo's spark response."""

    BASE_URL = "https://query1.finance.yahoo.com/v7/finance/spark"
    PROVIDER = "yahoo-finance"
    CHUNK_SIZE = 10

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

    @staticmethod
    def _url(symbols: tuple[str, ...]) -> str:
        query = urlencode(
            {
                "symbols": ",".join(symbols),
                "range": "5d",
                "interval": "1d",
            }
        )
        return f"{YahooBatchMarketProvider.BASE_URL}?{query}"

    def _fetch(self, url: str, as_of: date) -> tuple[object, str]:
        if not self._refresh:
            cached = self._cache.load(url)
            if cached is not None and cached.data_as_of == as_of:
                if cached.provider != self.PROVIDER:
                    raise YahooProviderError("YAHOO_CACHE_PROVIDER_MISMATCH")
                self.cache_hits += 1
                return cached.payload, cached.payload_sha256
        self.cache_misses += 1
        if self._client is None:
            raise YahooProviderError("YAHOO_CACHE_MISS_REQUIRES_NETWORK")
        self.provider_requests += 1
        stored = self._cache.store(
            url,
            provider=self.PROVIDER,
            data_as_of=as_of,
            payload=self._client.get_json(url),
        )
        return stored.payload, stored.payload_sha256

    @staticmethod
    def _parse(
        payload: object,
        *,
        symbol_to_ticker: Mapping[str, str],
        as_of: date,
        source_identity: str,
    ) -> dict[str, MarketQuote]:
        if not isinstance(payload, dict):
            raise YahooProviderError("YAHOO_SCHEMA_INVALID")
        spark = payload.get("spark")
        if not isinstance(spark, dict) or spark.get("error") is not None:
            raise YahooProviderError("YAHOO_SCHEMA_INVALID")
        results = spark.get("result")
        if not isinstance(results, list):
            raise YahooProviderError("YAHOO_SCHEMA_INVALID")

        quotes: dict[str, MarketQuote] = {}
        for item in results:
            if not isinstance(item, dict) or not isinstance(item.get("symbol"), str):
                raise YahooProviderError("YAHOO_RESULT_INVALID")
            yahoo_symbol = str(item["symbol"]).upper()
            ticker = symbol_to_ticker.get(yahoo_symbol)
            if ticker is None:
                continue
            responses = item.get("response")
            if (
                not isinstance(responses, list)
                or not responses
                or not isinstance(responses[0], dict)
            ):
                raise YahooProviderError("YAHOO_QUOTE_RESPONSE_INVALID")
            response = responses[0]
            timestamps = response.get("timestamp")
            indicators = response.get("indicators")
            if not isinstance(timestamps, list) or not isinstance(indicators, dict):
                raise YahooProviderError("YAHOO_QUOTE_SERIES_INVALID")
            quote_items = indicators.get("quote")
            if (
                not isinstance(quote_items, list)
                or not quote_items
                or not isinstance(quote_items[0], dict)
            ):
                raise YahooProviderError("YAHOO_QUOTE_SERIES_INVALID")
            closes = quote_items[0].get("close")
            if not isinstance(closes, list) or len(closes) != len(timestamps):
                raise YahooProviderError("YAHOO_QUOTE_SERIES_INVALID")
            selected: tuple[float, date] | None = None
            for timestamp, close in reversed(tuple(zip(timestamps, closes, strict=True))):
                price = _number(close)
                if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
                    continue
                try:
                    observed = datetime.fromtimestamp(timestamp, tz=timezone.utc).date()
                except (OverflowError, OSError, ValueError):
                    continue
                if price is not None and observed <= as_of:
                    selected = (price, observed)
                    break
            if selected is None:
                continue
            meta = response.get("meta")
            raw_currency = meta.get("currency") if isinstance(meta, dict) else None
            currency = (
                raw_currency.strip().upper()
                if isinstance(raw_currency, str) and raw_currency.strip()
                else "UNKNOWN"
            )
            quotes[ticker] = MarketQuote(
                ticker=ticker,
                price=selected[0],
                observed_on=selected[1],
                currency=currency,
                market_cap=None,
                source_provider=YahooBatchMarketProvider.PROVIDER,
                source_identity=source_identity,
            )
        return quotes

    def quotes(self, tickers: tuple[str, ...], as_of: date) -> dict[str, MarketQuote]:
        canonical = tuple(sorted(set(_canonical_symbol(ticker) for ticker in tickers)))
        symbol_to_ticker = {_yahoo_symbol(ticker): ticker for ticker in canonical}
        if len(symbol_to_ticker) != len(canonical):
            raise YahooProviderError("YAHOO_SYMBOL_COLLISION")
        output: dict[str, MarketQuote] = {}
        yahoo_symbols = tuple(sorted(symbol_to_ticker))
        for offset in range(0, len(yahoo_symbols), self.CHUNK_SIZE):
            chunk = yahoo_symbols[offset : offset + self.CHUNK_SIZE]
            url = self._url(chunk)
            payload, identity = self._fetch(url, as_of)
            output.update(
                self._parse(
                    payload,
                    symbol_to_ticker=symbol_to_ticker,
                    as_of=as_of,
                    source_identity=identity,
                )
            )
        return {ticker: output[ticker] for ticker in sorted(output)}
