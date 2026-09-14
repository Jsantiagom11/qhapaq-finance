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


def test_dynamically_resolved_unconfigured_company_requires_evidence(tmp_path: Path) -> None:
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

    orchestrator = AnalysisOrchestrator(Path(__file__).resolve().parents[1], resolver=resolver)
    result = orchestrator.analyze("acme")

    assert result.status is AnalysisStatus.EVIDENCE_REQUIRED
    assert result.canonical_result is None
    assert result.plan.identity.to_dict()["cik"] == "0000000123"
    assert result.plan.identity.to_dict()["exchange"] is None
