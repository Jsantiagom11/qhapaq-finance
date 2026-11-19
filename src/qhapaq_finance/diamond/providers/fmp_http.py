"""Minimal HTTP boundary for Financial Modeling Prep."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http.client import HTTPConnection, HTTPSConnection
from typing import Protocol
from urllib.parse import urlencode, urlsplit


@dataclass(frozen=True, slots=True)
class FmpResponse:
    status_code: int
    headers: Mapping[str, str]
    content: bytes


class FmpHttpError(RuntimeError):
    """An FMP endpoint returned a non-successful HTTP status."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"FMP request failed with HTTP {status_code}")
        self.status_code = status_code


class FmpTransport(Protocol):
    def __call__(
        self,
        url: str,
        headers: Mapping[str, str],
        connect_timeout: float,
        read_timeout: float,
    ) -> FmpResponse: ...


def _stdlib_get(
    url: str,
    headers: Mapping[str, str],
    connect_timeout: float,
    read_timeout: float,
) -> FmpResponse:
    """Issue one GET request using only the Python standard library."""
    parts = urlsplit(url)

    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("FMP URL must be an absolute HTTP(S) URL")

    connection_type = HTTPSConnection if parts.scheme == "https" else HTTPConnection
    target = parts.path or "/"

    if parts.query:
        target = f"{target}?{parts.query}"

    connection = connection_type(
        parts.hostname,
        parts.port,
        timeout=connect_timeout,
    )

    try:
        connection.request(
            "GET",
            target,
            headers=dict(headers),
        )

        if connection.sock is not None:
            connection.sock.settimeout(read_timeout)

        response = connection.getresponse()

        return FmpResponse(
            status_code=response.status,
            headers=dict(response.getheaders()),
            content=response.read(),
        )
    finally:
        connection.close()


class FmpClient:
    """Small injectable FMP client.

    Authentication is sent only through the HTTP header so the secret
    never becomes part of the request URL or its cache identity.
    """

    BASE_URL = "https://financialmodelingprep.com/stable"

    def __init__(
        self,
        *,
        api_key: str,
        transport: FmpTransport = _stdlib_get,
        connect_timeout: float = 5.0,
        read_timeout: float = 30.0,
        max_retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._api_key = api_key
        self._transport = transport
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._max_retries = max_retries
        self._sleep = sleep

    def get_json(
        self,
        endpoint: str,
        params: Mapping[str, str] | None = None,
    ) -> object:
        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"

        if params:
            url = f"{url}?{urlencode(params)}"

        for attempt in range(self._max_retries + 1):
            response = self._transport(
                url,
                {"apikey": self._api_key},
                self._connect_timeout,
                self._read_timeout,
            )

            if 400 <= response.status_code <= 499 and response.status_code != 429:
                raise FmpHttpError(response.status_code)

            if response.status_code == 429:
                if attempt == self._max_retries:
                    raise FmpHttpError(429)

                retry_after = next(
                    (
                        value
                        for name, value in response.headers.items()
                        if name.lower() == "retry-after"
                    ),
                    "0",
                )
                try:
                    delay = max(0.0, float(retry_after))
                except (TypeError, ValueError):
                    delay = 0.0

                self._sleep(delay)
                continue

            if 500 <= response.status_code <= 599:
                if attempt == self._max_retries:
                    raise FmpHttpError(response.status_code)

                self._sleep(0.5 * (2**attempt))
                continue

            try:
                return json.loads(response.content.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RuntimeError("FMP response contained invalid JSON") from exc

        raise AssertionError("unreachable")
