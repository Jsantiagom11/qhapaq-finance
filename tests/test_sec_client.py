from __future__ import annotations

import gzip
import threading
import zlib
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest

from qhapaq_finance.sec_client import (
    SecClient,
    SecContentDecodingError,
    SecHttpError,
    SecResponse,
    _reset_process_rate_limiter_for_tests,
)
from qhapaq_finance.sec_config import SecConfig


class FakeTransport:
    def __init__(self, responses: list[SecResponse]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, Mapping[str, str], float, float]] = []

    def __call__(
        self, url: str, headers: Mapping[str, str], connect_timeout: float, read_timeout: float
    ) -> SecResponse:
        self.calls.append((url, headers, connect_timeout, read_timeout))
        return self._responses.pop(0)


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def config() -> SecConfig:
    return SecConfig("Qhapaq Finance", "ops@example.com", 10.0)


def _raw_deflate(content: bytes) -> bytes:
    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    return compressor.compress(content) + compressor.flush()


@pytest.fixture(autouse=True)
def reset_process_rate_limiter() -> None:
    _reset_process_rate_limiter_for_tests()
    yield
    _reset_process_rate_limiter_for_tests()


def test_get_sends_config_headers_and_explicit_timeouts() -> None:
    transport = FakeTransport([SecResponse(200, {}, b'{"ok": true}')])
    client = SecClient(config(), transport=transport, connect_timeout=2, read_timeout=9)

    assert client.get_json("https://www.sec.gov/data.json") == {"ok": True}
    assert transport.calls == [
        (
            "https://www.sec.gov/data.json",
            config().headers,
            2,
            9,
        )
    ]


def test_response_json_accepts_uncompressed_json() -> None:
    response = SecResponse(200, {}, b'{"ok": true}')

    assert response.decoded_content == b'{"ok": true}'
    assert response.json() == {"ok": True}


def test_response_decodes_case_insensitive_gzip_json() -> None:
    entity = b'{"issuer": "AAPL"}'
    encoded = gzip.compress(entity, mtime=0)
    response = SecResponse(200, {"cOnTeNt-EnCoDiNg": "gzip"}, encoded)

    assert response.content == encoded
    assert response.raw_content == encoded
    assert response.decoded_content == entity
    assert response.json() == {"issuer": "AAPL"}


@pytest.mark.parametrize(
    "encoded",
    [zlib.compress(b'{"issuer": "QCOM"}'), _raw_deflate(b'{"issuer": "QCOM"}')],
)
def test_response_decodes_zlib_and_raw_deflate_json(encoded: bytes) -> None:
    response = SecResponse(200, {"Content-Encoding": "deflate"}, encoded)

    assert response.json() == {"issuer": "QCOM"}


def test_response_rejects_malformed_gzip() -> None:
    response = SecResponse(200, {"Content-Encoding": "gzip"}, b"not a gzip stream")

    with pytest.raises(SecContentDecodingError, match="unable to decode"):
        _ = response.decoded_content


def test_response_rejects_unsupported_content_encoding() -> None:
    response = SecResponse(200, {"Content-Encoding": "br"}, b"opaque")

    with pytest.raises(SecContentDecodingError, match="unsupported SEC Content-Encoding: br"):
        _ = response.decoded_content


def test_retry_after_seconds_is_respected() -> None:
    transport = FakeTransport(
        [
            SecResponse(429, {"Retry-After": "7"}, b"slow down"),
            SecResponse(200, {}, b"ok"),
        ]
    )
    fake_time = FakeTime()
    client = SecClient(
        config(),
        transport=transport,
        clock=fake_time.clock,
        sleep=fake_time.sleep,
        backoff_base=0.1,
    )

    assert client.get("https://www.sec.gov/data.json").content == b"ok"
    assert fake_time.sleeps == [7.0]
    assert len(transport.calls) == 2


def test_retry_after_http_date_is_respected() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    retry_at = format_datetime(now + timedelta(seconds=12), usegmt=True)
    transport = FakeTransport(
        [SecResponse(503, {"Retry-After": retry_at}, b"busy"), SecResponse(200, {}, b"")]
    )
    fake_time = FakeTime()
    client = SecClient(
        config(),
        transport=transport,
        clock=fake_time.clock,
        sleep=fake_time.sleep,
        wall_clock=lambda: now,
    )

    client.get("https://www.sec.gov/data.json")
    assert fake_time.sleeps == [12.0]


def test_403_and_transient_errors_use_bounded_exponential_backoff() -> None:
    transport = FakeTransport(
        [SecResponse(403, {}, b"one"), SecResponse(503, {}, b"two"), SecResponse(200, {}, b"ok")]
    )
    fake_time = FakeTime()
    client = SecClient(
        config(),
        transport=transport,
        clock=fake_time.clock,
        sleep=fake_time.sleep,
        backoff_base=2,
        backoff_cap=3,
    )

    client.get("https://www.sec.gov/data.json")
    assert fake_time.sleeps == [2, 3]


def test_permanent_client_errors_are_not_retried() -> None:
    transport = FakeTransport([SecResponse(404, {}, b"missing")])
    client = SecClient(config(), transport=transport)

    with pytest.raises(SecHttpError, match="HTTP 404"):
        client.get("https://www.sec.gov/data.json")
    assert len(transport.calls) == 1


def test_process_limiter_spaces_concurrent_callers_on_one_client() -> None:
    fake_time = FakeTime()
    starts: list[float] = []
    starts_lock = threading.Lock()
    barrier = threading.Barrier(4)

    def transport(
        url: str, headers: Mapping[str, str], connect_timeout: float, read_timeout: float
    ) -> SecResponse:
        del url, headers, connect_timeout, read_timeout
        with starts_lock:
            starts.append(fake_time.clock())
        return SecResponse(200, {}, b"ok")

    client = SecClient(config(), transport=transport, clock=fake_time.clock, sleep=fake_time.sleep)

    def fetch() -> None:
        barrier.wait()
        client.get("https://www.sec.gov/data.json")

    threads = [threading.Thread(target=fetch) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(starts) == 4
    ordered = sorted(starts)
    assert ordered == pytest.approx([0.0, 0.1, 0.2, 0.3])
    assert fake_time.sleeps == pytest.approx([0.1, 0.1, 0.1])


def test_process_limiter_is_shared_by_concurrent_clients() -> None:
    fake_time = FakeTime()
    starts: list[float] = []
    starts_lock = threading.Lock()
    barrier = threading.Barrier(6)

    def transport(
        url: str, headers: Mapping[str, str], connect_timeout: float, read_timeout: float
    ) -> SecResponse:
        del url, headers, connect_timeout, read_timeout
        with starts_lock:
            starts.append(fake_time.clock())
        return SecResponse(200, {}, b"ok")

    clients = [
        SecClient(config(), transport=transport, clock=fake_time.clock, sleep=fake_time.sleep),
        SecClient(config(), transport=transport, clock=fake_time.clock, sleep=fake_time.sleep),
    ]

    def fetch(index: int) -> None:
        barrier.wait()
        clients[index % len(clients)].get("https://www.sec.gov/data.json")

    threads = [threading.Thread(target=fetch, args=(index,)) for index in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(starts) == pytest.approx([0.0, 0.1, 0.2, 0.3, 0.4, 0.5])


def test_process_limiter_keeps_aggregate_spacing_with_configured_max_rps() -> None:
    fake_time = FakeTime()
    starts: list[float] = []
    starts_lock = threading.Lock()
    barrier = threading.Barrier(4)
    limited_config = SecConfig("Qhapaq Finance", "ops@example.com", 4.0)

    def transport(
        url: str, headers: Mapping[str, str], connect_timeout: float, read_timeout: float
    ) -> SecResponse:
        del url, headers, connect_timeout, read_timeout
        with starts_lock:
            starts.append(fake_time.clock())
        return SecResponse(200, {}, b"ok")

    clients = [
        SecClient(
            limited_config,
            transport=transport,
            clock=fake_time.clock,
            sleep=fake_time.sleep,
        ),
        SecClient(
            limited_config,
            transport=transport,
            clock=fake_time.clock,
            sleep=fake_time.sleep,
        ),
    ]

    def fetch(index: int) -> None:
        barrier.wait()
        clients[index % len(clients)].get("https://www.sec.gov/data.json")

    threads = [threading.Thread(target=fetch, args=(index,)) for index in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    ordered = sorted(starts)
    interval = 1.0 / limited_config.max_rps
    assert all(
        later - earlier >= interval for earlier, later in zip(ordered, ordered[1:], strict=False)
    )
