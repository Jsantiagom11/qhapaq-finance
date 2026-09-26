from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import cast

import pytest

from qhapaq_finance.analysis import AnalysisOrchestrator
from qhapaq_finance.company_resolver import (
    CompanyProvenance,
    RefreshableSymbolResolver,
    ResolvedCompany,
)
from qhapaq_finance.diamond.contracts import SecurityRef
from qhapaq_finance.diamond.engine import DiamondResult
from qhapaq_finance.sec_client import SecClient

ROOT = Path(__file__).resolve().parents[2]


def _module() -> ModuleType:
    try:
        return importlib.import_module("qhapaq_finance.executive.identity_resolver")
    except ModuleNotFoundError as exc:
        pytest.fail(
            f"identity resolver module missing: {exc}",
            pytrace=False,
        )


def _candidate(
    *,
    ticker: str = "ACME",
    provider: str = "sec-first",
    source_security: SecurityRef | None,
) -> DiamondResult:
    return cast(
        DiamondResult,
        SimpleNamespace(
            ticker=ticker,
            company_name="Acme Corporation",
            provider=provider,
            source_security=source_security,
        ),
    )


def _fallback_company() -> ResolvedCompany:
    return ResolvedCompany(
        ticker="ACME",
        company_name="Fallback Corporation",
        cik="0000000999",
        exchange=None,
        provenance=CompanyProvenance(
            source_url="fixture://fallback",
            fetched_at=None,
            raw_sha256=None,
            raw_byte_size=None,
        ),
    )


class FakeFallback:
    def __init__(
        self,
        result: ResolvedCompany | None = None,
    ) -> None:
        self.result = result
        self.resolve_calls: list[str] = []
        self.refresh_calls: list[SecClient] = []

    def resolve(self, ticker: str) -> ResolvedCompany | None:
        self.resolve_calls.append(ticker)
        return self.result

    def refresh(self, client: SecClient) -> int:
        self.refresh_calls.append(client)
        return 7


def test_authoritative_sec_first_identity_wins_without_fallback() -> None:
    module = _module()
    fallback = FakeFallback(_fallback_company())
    candidate = _candidate(
        source_security=SecurityRef(
            ticker="ACME",
            security_id="security:acme",
            issuer_id="sec-cik:0000000123",
        )
    )

    resolver = module.DiamondIdentityResolver(
        (candidate,),
        fallback,
    )

    resolved = resolver.resolve("acme")

    assert isinstance(resolver, RefreshableSymbolResolver)
    assert resolved is not None
    assert resolved.ticker == "ACME"
    assert resolved.company_name == "Acme Corporation"
    assert resolved.cik == "0000000123"
    assert resolved.exchange is None
    assert resolved.provenance == CompanyProvenance(
        source_url="diamond://sec-first/security-ref",
        fetched_at=None,
        raw_sha256=None,
        raw_byte_size=None,
    )
    assert fallback.resolve_calls == []


def test_non_sec_first_candidate_uses_fallback() -> None:
    module = _module()
    expected = _fallback_company()
    fallback = FakeFallback(expected)
    candidate = _candidate(
        provider="local-json",
        source_security=SecurityRef(
            ticker="ACME",
            security_id="security:acme",
            issuer_id="sec-cik:0000000123",
        ),
    )

    resolved = module.DiamondIdentityResolver(
        (candidate,),
        fallback,
    ).resolve("acme")

    assert resolved is expected
    assert fallback.resolve_calls == ["ACME"]


def test_missing_source_security_uses_fallback() -> None:
    module = _module()
    expected = _fallback_company()
    fallback = FakeFallback(expected)

    resolved = module.DiamondIdentityResolver(
        (_candidate(source_security=None),),
        fallback,
    ).resolve("acme")

    assert resolved is expected
    assert fallback.resolve_calls == ["ACME"]


def test_source_security_ticker_mismatch_uses_fallback() -> None:
    module = _module()
    expected = _fallback_company()
    fallback = FakeFallback(expected)
    candidate = _candidate(
        source_security=SecurityRef(
            ticker="OTHER",
            security_id="security:other",
            issuer_id="sec-cik:0000000123",
        )
    )

    resolved = module.DiamondIdentityResolver(
        (candidate,),
        fallback,
    ).resolve("acme")

    assert resolved is expected
    assert fallback.resolve_calls == ["ACME"]


@pytest.mark.parametrize(
    "issuer_id",
    (
        "other:0000000123",
        "sec-cik:not-digits",
        "sec-cik:123-45",
    ),
)
def test_malformed_sec_cik_uses_fallback(
    issuer_id: str,
) -> None:
    module = _module()
    expected = _fallback_company()
    fallback = FakeFallback(expected)
    candidate = _candidate(
        source_security=SecurityRef(
            ticker="ACME",
            security_id="security:acme",
            issuer_id=issuer_id,
        )
    )

    resolved = module.DiamondIdentityResolver(
        (candidate,),
        fallback,
    ).resolve("acme")

    assert resolved is expected
    assert fallback.resolve_calls == ["ACME"]


def test_refresh_delegates_to_existing_refreshable_resolver() -> None:
    module = _module()
    fallback = FakeFallback()
    resolver = module.DiamondIdentityResolver((), fallback)
    client = cast(SecClient, object())

    refreshed = resolver.refresh(client)

    assert refreshed == 7
    assert fallback.refresh_calls == [client]


def test_analysis_orchestrator_accepts_diamond_cik_without_authoritative_refresh() -> None:
    module = _module()
    fallback = FakeFallback()
    candidate = _candidate(
        source_security=SecurityRef(
            ticker="ACME",
            security_id="security:acme",
            issuer_id="sec-cik:0000000123",
        )
    )
    resolver = module.DiamondIdentityResolver(
        (candidate,),
        fallback,
    )

    plan = AnalysisOrchestrator(
        ROOT,
        resolver=resolver,
    ).plan("acme")

    assert plan.identity.to_dict()["ticker"] == "ACME"
    assert plan.identity.to_dict()["cik"] == "0000000123"
    assert fallback.resolve_calls == []
    assert fallback.refresh_calls == []
