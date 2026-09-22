"""Polite, concurrency-safe HTTP access for SEC endpoints."""

from __future__ import annotations

import gzip
import json
import threading
import time
import zlib
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.client import HTTPConnection, HTTPSConnection
from typing import Any, Protocol
from urllib.parse import urlsplit

from .sec_config import SecConfig


class SecClientError(RuntimeError):
    """Base error raised by :class:`SecClient`."""


class SecHttpError(SecClientError):
    """An SEC endpoint returned a non-successful response."""

    def __init__(self, status_code: int, url: str, body: bytes) -> None:
        super().__init__(f"SEC request failed with HTTP {status_code}: {url}")
        self.status_code = status_code
        self.url = url
        self.body = body


class SecContentDecodingError(SecClientError):
    """An SEC response body could not be decoded from its declared encoding."""


@dataclass(frozen=True, slots=True)
class SecResponse:
    """A fully-read HTTP response with raw and decoded entity-body access.

    ``content`` is the raw transport body, retained for HTTP diagnostics.
    Consumers of the entity body must use ``decoded_content``.
    """

    status_code: int
    headers: Mapping[str, str]
    content: bytes

    @property
    def raw_content(self) -> bytes:
        """Return the transfer-encoded response bytes for diagnostics."""
        return self.content

    @property
    def decoded_content(self) -> bytes:
        """Return the entity body decoded according to ``Content-Encoding``.

        Encodings are applied in reverse declaration order, as required for
        HTTP content codings.  Unknown encodings fail closed rather than being
        guessed from the payload bytes.
        """
        content = self.content
        encodings = _content_encodings(self.headers)
        for encoding in reversed(encodings):
            if encoding == "identity":
                continue
            try:
                if encoding == "gzip":
                    content = gzip.decompress(content)
                elif encoding == "deflate":
                    content = _decompress_deflate(content)
                else:
                    raise SecContentDecodingError(f"unsupported SEC Content-Encoding: {encoding}")
            except SecContentDecodingError:
                raise
            except (OSError, zlib.error) as exc:
                raise SecContentDecodingError(
                    f"unable to decode SEC response with Content-Encoding: {encoding}"
                ) from exc
        return content

    def json(self) -> Any:
        """Decode the response body as JSON."""
        return json.loads(self.decoded_content)


def _content_encodings(headers: Mapping[str, str]) -> tuple[str, ...]:
    """Read and normalize the case-insensitive HTTP Content-Encoding header."""
    value = next(
        (value for name, value in headers.items() if name.lower() == "content-encoding"), None
    )
    if value is None or not value.strip():
        return ()
    encodings = tuple(encoding.strip().lower() for encoding in value.split(","))
    if any(not encoding for encoding in encodings):
        raise SecContentDecodingError("unsupported SEC Content-Encoding: empty token")
    return encodings


def _decompress_deflate(content: bytes) -> bytes:
    """Decode standard zlib-wrapped deflate, then the raw-deflate fallback."""
    try:
        return zlib.decompress(content)
    except zlib.error as wrapped_error:
        try:
            return zlib.decompress(content, -zlib.MAX_WBITS)
        except zlib.error as raw_error:
            raise wrapped_error from raw_error


class SecTransport(Protocol):
    """Small injectable boundary that keeps client tests off the network."""

    def __call__(
        self,
        url: str,
        headers: Mapping[str, str],
        connect_timeout: float,
        read_timeout: float,
    ) -> SecResponse: ...


def _stdlib_get(
    url: str,
    headers: Mapping[str, str],
    connect_timeout: float,
    read_timeout: float,
) -> SecResponse:
    """Issue a GET with independently configured connect and read timeouts."""
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("SEC URL must be an absolute HTTP(S) URL")

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
        return SecResponse(response.status, dict(response.getheaders()), response.read())
    finally:
        connection.close()


class _RateLimiter:
    """Reserve evenly-spaced request starts, safely across all client callers."""

    def __init__(
        self, max_rps: float, clock: Callable[[], float], sleep: Callable[[float], None]
    ) -> None:
        self._interval = 1.0 / max_rps
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def tighten(self, max_rps: float) -> None:
        """Apply a stricter process-wide rate policy, if one is configured."""
        interval = 1.0 / max_rps
        with self._lock:
            if interval > self._interval:
                self._interval = interval
                self._next_allowed = max(self._next_allowed, self._clock() + interval)

    @contextmanager
    def request_slot(self) -> Iterator[None]:
        """Hold the start gate through the transport call that follows."""
        self._lock.acquire()
        try:
            now = self._clock()
            delay = max(0.0, self._next_allowed - now)
            if delay > 0:
                self._sleep(delay)
            self._next_allowed = self._clock() + self._interval
            yield
        finally:
            self._lock.release()


_PROCESS_LIMITER_LOCK = threading.Lock()
_PROCESS_LIMITER: _RateLimiter | None = None


def _process_rate_limiter(
    max_rps: float, clock: Callable[[], float], sleep: Callable[[float], None]
) -> _RateLimiter:
    """Return the single request-start limiter used by this process.

    SEC configuration is normally process-wide.  If a later client supplies a
    stricter value, retain the stricter policy so it cannot loosen the shared
    request budget.
    """
    global _PROCESS_LIMITER
    with _PROCESS_LIMITER_LOCK:
        if _PROCESS_LIMITER is None:
            _PROCESS_LIMITER = _RateLimiter(max_rps, clock, sleep)
        else:
            _PROCESS_LIMITER.tighten(max_rps)
        return _PROCESS_LIMITER


def _reset_process_rate_limiter_for_tests() -> None:
    """Clear process-global limiter state for isolated tests."""
    global _PROCESS_LIMITER
    with _PROCESS_LIMITER_LOCK:
        _PROCESS_LIMITER = None


class SecClient:
    """Centralized SEC GET client with retries and a process-wide rate limiter."""

    def __init__(
        self,
        config: SecConfig,
        *,
        connect_timeout: float = 5.0,
        read_timeout: float = 30.0,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        backoff_cap: float = 30.0,
        transport: SecTransport = _stdlib_get,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        wall_clock: Callable[[], datetime] | None = None,
    ) -> None:
        if config.max_rps <= 0:
            raise ValueError("config.max_rps must be positive")
        if connect_timeout <= 0 or read_timeout <= 0:
            raise ValueError("connect_timeout and read_timeout must be positive")
        if max_retries < 0 or backoff_base < 0 or backoff_cap < 0:
            raise ValueError("retry settings must be non-negative")
        self.config = config
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self._transport = transport
        self._sleep = sleep
        self._clock = clock
        self._wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        self._rate_limiter = _process_rate_limiter(config.max_rps, clock, sleep)

    def get(
        self,
        url: str,
        *,
        request_headers: Mapping[str, str] | None = None,
        accepted_statuses: frozenset[int] = frozenset(),
    ) -> SecResponse:
        """Fetch ``url``, retrying only throttling and transient server failures."""
        headers = dict(self.config.headers)
        if request_headers is not None:
            headers.update(request_headers)

        for attempt in range(self.max_retries + 1):
            try:
                with self._rate_limiter.request_slot():
                    response = self._transport(
                        url,
                        headers,
                        self.connect_timeout,
                        self.read_timeout,
                    )
            except OSError:
                if attempt == self.max_retries:
                    raise
                self._sleep(self._backoff_delay(attempt))
                continue

            if 200 <= response.status_code < 300 or response.status_code in accepted_statuses:
                return response
            if not self._is_retryable(response.status_code) or attempt == self.max_retries:
                raise SecHttpError(response.status_code, url, response.content)
            self._sleep(self._retry_delay(response.headers, attempt))

        raise AssertionError("unreachable")

    def get_json(self, url: str) -> Any:
        """Fetch and decode a JSON SEC endpoint."""
        return self.get(url).json()

    @staticmethod
    def _is_retryable(status_code: int) -> bool:
        return status_code in {403, 429} or 500 <= status_code <= 599

    def _backoff_delay(self, attempt: int) -> float:
        return min(self.backoff_cap, self.backoff_base * (2**attempt))

    def _retry_delay(self, headers: Mapping[str, str], attempt: int) -> float:
        retry_after = _retry_after_seconds(headers, self._wall_clock)
        return retry_after if retry_after is not None else self._backoff_delay(attempt)


def _retry_after_seconds(
    headers: Mapping[str, str], wall_clock: Callable[[], datetime]
) -> float | None:
    """Return a non-negative Retry-After delay, supporting seconds and HTTP dates."""
    value = next((v for k, v in headers.items() if k.lower() == "retry-after"), None)
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(0.0, retry_at.timestamp() - wall_clock().timestamp())
