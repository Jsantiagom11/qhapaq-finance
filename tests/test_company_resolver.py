from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

import pytest

from qhapaq_finance.analysis import AnalysisOrchestrator, AnalysisStatus
from qhapaq_finance.company_resolver import (
    SEC_COMPANY_TICKERS_URL,
    CompanyResolver,
    ResolvedCompany,
    ResolverError,
)
from qhapaq_finance.sec_client import SecClient, SecResponse, _reset_process_rate_limiter_for_tests
from qhapaq_finance.sec_config import SecConfig


class FakeTransport:
    def __init__(self, response: SecResponse) -> None:
        self.response = response
        self.urls: list[str] = []

    def __call__(
        self, url: str, headers: Mapping[str, str], connect_timeout: float, read_timeout: float
    ) -> SecResponse:
        del headers, connect_timeout, read_timeout
        self.urls.append(url)
        return self.response


class CountingResolver:
    def __init__(self, resolver: CompanyResolver) -> None:
        self.resolver = resolver
        self.resolve_calls = 0
        self.refresh_calls = 0

    def resolve(self, ticker: str) -> ResolvedCompany | None:
        self.resolve_calls += 1
        return self.resolver.resolve(ticker)

    def refresh(self, client: SecClient) -> int:
        self.refresh_calls += 1
        return self.resolver.refresh(client)


@pytest.fixture(autouse=True)
def reset_process_rate_limiter() -> None:
    _reset_process_rate_limiter_for_tests()
    yield
    _reset_process_rate_limiter_for_tests()


def _client(response: SecResponse) -> tuple[SecClient, FakeTransport]:
    transport = FakeTransport(response)
    return (
        SecClient(SecConfig("Qhapaq Finance", "ops@example.com", 10), transport=transport),
        transport,
    )


def _payload() -> bytes:
    return json.dumps(
        {
            "0": {"cik_str": 320193, "ticker": "aapl", "title": " Apple   Inc. "},
            "1": {"cik_str": "804328", "ticker": "QCOM", "title": "QUALCOMM Incorporated"},
        }
    ).encode()


def _single_company_payload(ticker: str = "COST") -> bytes:
    return json.dumps(
        {"0": {"cik_str": 909832, "ticker": ticker, "title": "Costco Wholesale Corporation"}}
    ).encode()


def test_refresh_uses_sec_client_and_resolves_normalized_cached_identity(tmp_path: Path) -> None:
    raw = _payload()
    client, transport = _client(SecResponse(200, {"Content-Type": "application/json"}, raw))
    resolver = CompanyResolver(cache_path=tmp_path / "company_tickers.json")

    assert resolver.refresh(client, now=lambda: datetime(2026, 9, 11, tzinfo=timezone.utc)) == 2
    company = resolver.resolve(" aapl ")

    assert transport.urls == [SEC_COMPANY_TICKERS_URL]
    assert company is not None
    assert (company.ticker, company.company_name, company.cik, company.exchange) == (
        "AAPL",
        "Apple Inc.",
        "0000320193",
        None,
    )
    assert company.provenance.raw_sha256 == hashlib.sha256(raw).hexdigest()
    assert company.provenance.fetched_at == "2026-09-11T00:00:00Z"


def test_malformed_refresh_preserves_the_existing_valid_cache(tmp_path: Path) -> None:
    cache = tmp_path / "company_tickers.json"
    resolver = CompanyResolver(cache_path=cache)
    valid_client, _ = _client(SecResponse(200, {}, _payload()))
    resolver.refresh(valid_client)
    original = cache.read_bytes()
    malformed_client, _ = _client(SecResponse(200, {}, b"[]"))

    with pytest.raises(ResolverError, match="payload"):
        resolver.refresh(malformed_client)

    assert cache.read_bytes() == original
    assert resolver.resolve("QCOM") is not None


def test_dynamically_resolved_unconfigured_company_acquisition_failure_is_blocked(
    tmp_path: Path,
) -> None:
    resolver = CompanyResolver(cache_path=tmp_path / "company_tickers.json")
    client, _ = _client(
        SecResponse(
            200,
            {},
            json.dumps(
                {"0": {"cik_str": 123, "ticker": "ACME", "title": "Acme Corporation"}}
            ).encode(),
        )
    )
    resolver.refresh(client)

    factory_calls = 0

    def unavailable_sec_client() -> SecClient:
        nonlocal factory_calls
        factory_calls += 1
        raise RuntimeError("missing SEC configuration")

    orchestrator = AnalysisOrchestrator(
        Path(__file__).resolve().parents[1],
        resolver=resolver,
        sec_client_factory=unavailable_sec_client,
    )
    result = orchestrator.analyze("acme")

    assert result.status is AnalysisStatus.BLOCKED
    assert result.canonical_result is None
    assert factory_calls == 1
    assert result.plan.identity.to_dict()["cik"] == "0000000123"
    assert result.plan.identity.to_dict()["exchange"] is None


def test_analyze_local_resolution_hit_does_not_refresh() -> None:
    resolver = CountingResolver(
        CompanyResolver(cache_path=Path("data/cache/sec/company_tickers.json"))
    )

    def unexpected_client() -> SecClient:
        raise AssertionError("a local resolution hit must not create an SEC client")

    result = AnalysisOrchestrator(
        Path(__file__).resolve().parents[1],
        resolver=resolver,
        sec_client_factory=unexpected_client,
    ).analyze("qcom")

    assert result.status is AnalysisStatus.COMPLETED
    assert resolver.resolve_calls == 1
    assert resolver.refresh_calls == 0


def test_analyze_local_miss_refreshes_once_then_runs_bounded_acquisition(
    tmp_path: Path,
) -> None:
    client, transport = _client(SecResponse(200, {}, _single_company_payload()))
    resolver = CountingResolver(CompanyResolver(cache_path=tmp_path / "company_tickers.json"))

    result = AnalysisOrchestrator(
        Path(__file__).resolve().parents[1],
        resolver=resolver,
        sec_client_factory=lambda: client,
    ).analyze(" cost ")

    assert result.status is AnalysisStatus.BLOCKED
    assert result.plan.identity.ticker == "COST"
    assert result.plan.identity.cik == "0000909832"
    assert resolver.resolve_calls == 2
    assert resolver.refresh_calls == 1
    assert transport.urls == [
        SEC_COMPANY_TICKERS_URL,
        "https://data.sec.gov/submissions/CIK0000909832.json",
    ]


def test_analyze_authoritative_negative_is_unsupported_after_one_refresh(
    tmp_path: Path,
) -> None:
    client, transport = _client(SecResponse(200, {}, _single_company_payload()))
    resolver = CountingResolver(CompanyResolver(cache_path=tmp_path / "company_tickers.json"))

    result = AnalysisOrchestrator(
        Path(__file__).resolve().parents[1],
        resolver=resolver,
        sec_client_factory=lambda: client,
    ).analyze("zzzzzinvalid")

    assert result.status is AnalysisStatus.UNSUPPORTED_TICKER
    assert resolver.resolve_calls == 2
    assert resolver.refresh_calls == 1
    assert transport.urls == [SEC_COMPANY_TICKERS_URL]


def test_analyze_configuration_failure_is_blocked(tmp_path: Path) -> None:
    resolver = CountingResolver(CompanyResolver(cache_path=tmp_path / "company_tickers.json"))

    def invalid_config() -> SecClient:
        raise RuntimeError("missing SEC configuration")

    result = AnalysisOrchestrator(
        Path(__file__).resolve().parents[1],
        resolver=resolver,
        sec_client_factory=invalid_config,
    ).analyze("COST")

    assert result.status is AnalysisStatus.BLOCKED
    assert resolver.resolve_calls == 1
    assert resolver.refresh_calls == 0


def test_analyze_local_resolution_failure_is_blocked_without_refresh() -> None:
    class FailingLocalResolver:
        def resolve(self, ticker: str) -> ResolvedCompany | None:
            del ticker
            raise OSError("local reference unavailable")

        def refresh(self, client: SecClient) -> int:
            del client
            raise AssertionError("a failed local lookup is not an authoritative miss")

    result = AnalysisOrchestrator(
        Path(__file__).resolve().parents[1],
        resolver=FailingLocalResolver(),
        sec_client_factory=lambda: _client(SecResponse(200, {}, _single_company_payload()))[0],
    ).analyze("COST")

    assert result.status is AnalysisStatus.BLOCKED


def test_analyze_network_failure_is_blocked(tmp_path: Path) -> None:
    def unavailable_transport(
        url: str,
        headers: Mapping[str, str],
        connect_timeout: float,
        read_timeout: float,
    ) -> SecResponse:
        del url, headers, connect_timeout, read_timeout
        raise OSError("SEC unavailable")

    client = SecClient(
        SecConfig("Qhapaq Finance", "ops@example.com", 10),
        transport=unavailable_transport,
        max_retries=0,
    )
    resolver = CountingResolver(CompanyResolver(cache_path=tmp_path / "company_tickers.json"))

    result = AnalysisOrchestrator(
        Path(__file__).resolve().parents[1],
        resolver=resolver,
        sec_client_factory=lambda: client,
    ).analyze("COST")

    assert result.status is AnalysisStatus.BLOCKED
    assert resolver.resolve_calls == 1
    assert resolver.refresh_calls == 1


def test_analyze_reference_validation_failure_is_blocked(tmp_path: Path) -> None:
    client, _ = _client(SecResponse(200, {}, b"[]"))
    resolver = CountingResolver(CompanyResolver(cache_path=tmp_path / "company_tickers.json"))

    result = AnalysisOrchestrator(
        Path(__file__).resolve().parents[1],
        resolver=resolver,
        sec_client_factory=lambda: client,
    ).analyze("COST")

    assert result.status is AnalysisStatus.BLOCKED
    assert resolver.resolve_calls == 1
    assert resolver.refresh_calls == 1


def test_analyze_reference_persistence_failure_is_blocked(tmp_path: Path) -> None:
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("file", encoding="utf-8")
    client, _ = _client(SecResponse(200, {}, _single_company_payload()))
    resolver = CountingResolver(CompanyResolver(cache_path=blocked_parent / "company_tickers.json"))

    result = AnalysisOrchestrator(
        Path(__file__).resolve().parents[1],
        resolver=resolver,
        sec_client_factory=lambda: client,
    ).analyze("COST")

    assert result.status is AnalysisStatus.BLOCKED
    assert resolver.resolve_calls == 1
    assert resolver.refresh_calls == 1
