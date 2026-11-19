from __future__ import annotations

import json
from collections.abc import Mapping

import pytest

from qhapaq_finance.diamond.providers.fmp_http import (
    FmpClient,
    FmpHttpError,
    FmpResponse,
)


def test_get_json_decodes_payload_without_putting_api_key_in_url() -> None:
    seen_url: str | None = None
    seen_headers: Mapping[str, str] | None = None
    secret = "test-secret-key"

    def transport(
        url: str,
        headers: Mapping[str, str],
        connect_timeout: float,
        read_timeout: float,
    ) -> FmpResponse:
        nonlocal seen_url, seen_headers
        seen_url = url
        seen_headers = headers

        assert connect_timeout > 0
        assert read_timeout > 0

        return FmpResponse(
            status_code=200,
            headers={"content-type": "application/json"},
            content=json.dumps([{"symbol": "AAPL"}]).encode("utf-8"),
        )

    client = FmpClient(
        api_key=secret,
        transport=transport,
    )

    payload = client.get_json(
        "search-symbol",
        {"query": "AAPL"},
    )

    assert payload == [{"symbol": "AAPL"}]

    assert seen_url is not None
    assert "search-symbol" in seen_url
    assert "query=AAPL" in seen_url
    assert secret not in seen_url
    assert "apikey" not in seen_url.lower()

    assert seen_headers is not None
    assert seen_headers["apikey"] == secret


def test_http_401_fails_immediately_without_leaking_api_key() -> None:
    attempts = 0
    secret = "super-secret-fmp-key"

    def transport(
        url: str,
        headers: Mapping[str, str],
        connect_timeout: float,
        read_timeout: float,
    ) -> FmpResponse:
        nonlocal attempts
        attempts += 1

        assert secret not in url
        assert headers["apikey"] == secret

        return FmpResponse(
            status_code=401,
            headers={"content-type": "application/json"},
            content=b'{"Error Message":"Invalid API KEY"}',
        )

    client = FmpClient(
        api_key=secret,
        transport=transport,
    )

    with pytest.raises(RuntimeError) as exc_info:
        client.get_json("search-symbol", {"query": "AAPL"})

    assert attempts == 1
    assert "401" in str(exc_info.value)
    assert secret not in str(exc_info.value)


def test_http_403_fails_immediately_without_leaking_api_key() -> None:
    attempts = 0
    secret = "super-secret-fmp-key"

    def transport(
        url: str,
        headers: Mapping[str, str],
        connect_timeout: float,
        read_timeout: float,
    ) -> FmpResponse:
        nonlocal attempts
        attempts += 1

        assert secret not in url
        assert headers["apikey"] == secret

        return FmpResponse(
            status_code=403,
            headers={"content-type": "application/json"},
            content=b'{"Error Message":"Access denied"}',
        )

    client = FmpClient(
        api_key=secret,
        transport=transport,
    )

    with pytest.raises(RuntimeError) as exc_info:
        client.get_json("income-statement", {"symbol": "AAPL"})

    assert attempts == 1
    assert "403" in str(exc_info.value)
    assert secret not in str(exc_info.value)


def test_malformed_json_fails_closed_without_leaking_api_key() -> None:
    attempts = 0
    secret = "super-secret-fmp-key"

    def transport(
        url: str,
        headers: Mapping[str, str],
        connect_timeout: float,
        read_timeout: float,
    ) -> FmpResponse:
        nonlocal attempts
        attempts += 1

        assert secret not in url
        assert headers["apikey"] == secret

        return FmpResponse(
            status_code=200,
            headers={"content-type": "application/json"},
            content=b'{"symbol":"AAPL"',
        )

    client = FmpClient(
        api_key=secret,
        transport=transport,
    )

    with pytest.raises(RuntimeError) as exc_info:
        client.get_json("search-symbol", {"query": "AAPL"})

    assert attempts == 1
    assert "JSON" in str(exc_info.value)
    assert secret not in str(exc_info.value)


def test_http_429_honors_retry_after_then_retries() -> None:
    attempts = 0
    sleeps: list[float] = []

    def transport(
        url: str,
        headers: Mapping[str, str],
        connect_timeout: float,
        read_timeout: float,
    ) -> FmpResponse:
        nonlocal attempts
        attempts += 1

        if attempts == 1:
            return FmpResponse(
                status_code=429,
                headers={"Retry-After": "2"},
                content=b'{"Error Message":"Rate limit"}',
            )

        return FmpResponse(
            status_code=200,
            headers={"content-type": "application/json"},
            content=b'[{"symbol":"AAPL"}]',
        )

    client = FmpClient(
        api_key="test-key",
        transport=transport,
        max_retries=2,
        sleep=sleeps.append,
    )

    payload = client.get_json("search-symbol", {"query": "AAPL"})

    assert payload == [{"symbol": "AAPL"}]
    assert attempts == 2
    assert sleeps == [2.0]


def test_transient_500_retries_with_exponential_backoff() -> None:
    attempts = 0
    sleeps: list[float] = []

    def transport(
        url: str,
        headers: Mapping[str, str],
        connect_timeout: float,
        read_timeout: float,
    ) -> FmpResponse:
        nonlocal attempts
        attempts += 1

        if attempts == 1:
            return FmpResponse(
                status_code=500,
                headers={},
                content=b'{"Error Message":"temporary failure"}',
            )

        return FmpResponse(
            status_code=200,
            headers={"content-type": "application/json"},
            content=b'[{"symbol":"AAPL"}]',
        )

    client = FmpClient(
        api_key="test-key",
        transport=transport,
        max_retries=2,
        sleep=sleeps.append,
    )

    payload = client.get_json("search-symbol", {"query": "AAPL"})

    assert payload == [{"symbol": "AAPL"}]
    assert attempts == 2
    assert sleeps == [0.5]


def test_persistent_503_exhausts_retries_and_fails_sanitized() -> None:
    attempts = 0
    sleeps: list[float] = []
    secret = "super-secret-fmp-key"

    def transport(
        url: str,
        headers: Mapping[str, str],
        connect_timeout: float,
        read_timeout: float,
    ) -> FmpResponse:
        nonlocal attempts
        attempts += 1

        assert secret not in url
        assert headers["apikey"] == secret

        return FmpResponse(
            status_code=503,
            headers={},
            content=b'{"Error Message":"temporary failure"}',
        )

    client = FmpClient(
        api_key=secret,
        transport=transport,
        max_retries=2,
        sleep=sleeps.append,
    )

    with pytest.raises(RuntimeError) as exc_info:
        client.get_json("income-statement", {"symbol": "AAPL"})

    assert attempts == 3
    assert sleeps == [0.5, 1.0]
    assert "503" in str(exc_info.value)
    assert secret not in str(exc_info.value)


def test_http_404_fails_immediately_without_retry_or_secret_leak() -> None:
    attempts = 0
    sleeps: list[float] = []
    secret = "super-secret-fmp-key"

    def transport(
        url: str,
        headers: Mapping[str, str],
        connect_timeout: float,
        read_timeout: float,
    ) -> FmpResponse:
        nonlocal attempts
        attempts += 1

        assert secret not in url
        assert headers["apikey"] == secret

        return FmpResponse(
            status_code=404,
            headers={"content-type": "application/json"},
            content=b'{"Error Message":"Not found"}',
        )

    client = FmpClient(
        api_key=secret,
        transport=transport,
        max_retries=3,
        sleep=sleeps.append,
    )

    with pytest.raises(RuntimeError) as exc_info:
        client.get_json("missing-endpoint")

    assert attempts == 1
    assert sleeps == []
    assert "404" in str(exc_info.value)
    assert secret not in str(exc_info.value)


def test_http_failure_exposes_typed_status_without_secret() -> None:
    secret = "super-secret-fmp-key"

    def transport(
        url: str,
        headers: Mapping[str, str],
        connect_timeout: float,
        read_timeout: float,
    ) -> FmpResponse:
        return FmpResponse(
            status_code=404,
            headers={},
            content=b'{"Error Message":"Not found"}',
        )

    client = FmpClient(
        api_key=secret,
        transport=transport,
    )

    with pytest.raises(FmpHttpError) as exc_info:
        client.get_json("missing-endpoint")

    assert exc_info.value.status_code == 404
    assert "404" in str(exc_info.value)
    assert secret not in str(exc_info.value)


def test_client_has_production_transport_by_default() -> None:
    client = FmpClient(api_key="test-key")

    assert client is not None
