import hashlib
import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from qhapaq_finance.evidence import EvidenceKind, FilingRef, FinancialFact, PeriodKind
from qhapaq_finance.market_evidence import (
    CanonicalMarketFact,
    MarketEvidenceError,
    NormalizedMarketObservation,
    derive_market_cap,
    evaluate_market_quality,
    load_market_source_manifest,
    reconcile_market_cap,
)
from qhapaq_finance.model_requirements import (
    RequirementStatus,
    evaluate_market_stage_readiness,
    load_model_profile,
)
from qhapaq_finance.universe import DomainRegistry

ROOT = Path(__file__).parents[1]
NOW = datetime(2026, 9, 9, tzinfo=timezone.utc)


def _write_market(
    tmp_path: Path,
    *,
    ticker: str,
    price: float,
    provider: str,
    observed: datetime,
    retrieved: datetime,
    market_cap: float | None = None,
    source_id: str = "one",
) -> Path:
    raw = tmp_path / f"{source_id}.json"
    raw.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "ticker": ticker,
                "price": price,
                "currency": "USD",
                "observed_at": observed.isoformat(),
                "retrieved_at": retrieved.isoformat(),
                "source": provider,
                "market_state": "closed",
                "previous_close": None,
                "market_cap": market_cap,
            }
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / f"{source_id}-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "market-source-manifest-v1",
                "security_id": f"nvidia-corporation:{ticker}",
                "source_id": source_id,
                "provider": provider,
                "raw_artifact": raw.name,
                "raw_artifact_sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    return manifest


def _profile(
    tmp_path: Path, manifests: list[Path], policy: dict[str, int], *, max_age: int | None = None
) -> Path:
    raw: dict[str, object] = {
        "schema_version": "market-quality-profile-v1",
        "security_id": "nvidia-corporation:NVDA",
        "source_manifests": [item.name for item in manifests],
        "authority_policy": {"market_price": policy},
    }
    if max_age is not None:
        raw["max_age_seconds"] = max_age
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def test_market_manifest_quality_identity_freshness_and_lineage(tmp_path: Path) -> None:
    manifest = _write_market(
        tmp_path,
        ticker="NVDA",
        price=100,
        provider="fixture",
        observed=NOW - timedelta(minutes=5),
        retrieved=NOW,
    )
    assert load_market_source_manifest(manifest, tmp_path).source_id == "one"
    report = evaluate_market_quality(
        _profile(tmp_path, [manifest], {"fixture": 1}, max_age=600),
        registry=DomainRegistry(ROOT),
        root=tmp_path,
        now=NOW,
    )
    assert (
        report.ready
        and report.canonical_facts[0].normalized.observed_at
        != report.canonical_facts[0].normalized.retrieved_at
    )
    assert (
        report.to_dict()
        == evaluate_market_quality(
            _profile(tmp_path, [manifest], {"fixture": 1}, max_age=600),
            registry=DomainRegistry(ROOT),
            root=tmp_path,
            now=NOW,
        ).to_dict()
    )
    assert report.canonical_facts[0].normalized.source_manifest_ref == "one"
    later = evaluate_market_quality(
        _profile(tmp_path, [manifest], {"fixture": 1}, max_age=600),
        registry=DomainRegistry(ROOT),
        root=tmp_path,
        now=NOW + timedelta(minutes=1),
    )
    assert report.immutable_identity == later.immutable_identity
    assert report.evaluation_identity != later.evaluation_identity


def test_malformed_manifest_and_previous_close_never_become_price(tmp_path: Path) -> None:
    malformed = tmp_path / "broken.json"
    malformed.write_text("{}", encoding="utf-8")
    with pytest.raises(MarketEvidenceError, match="MANIFEST"):
        load_market_source_manifest(malformed, tmp_path)
    manifest = _write_market(
        tmp_path, ticker="NVDA", price=100, provider="fixture", observed=NOW, retrieved=NOW
    )
    report = evaluate_market_quality(
        _profile(tmp_path, [manifest], {"fixture": 1}),
        registry=DomainRegistry(ROOT),
        root=tmp_path,
        now=NOW,
    )
    assert [item.normalized.metric_id for item in report.canonical_facts] == ["price"]


def test_stale_future_conflict_and_currency_fail_closed(tmp_path: Path) -> None:
    stale = _write_market(
        tmp_path,
        ticker="NVDA",
        price=100,
        provider="fixture",
        observed=NOW - timedelta(days=2),
        retrieved=NOW,
    )
    report = evaluate_market_quality(
        _profile(tmp_path, [stale], {"fixture": 1}, max_age=60),
        registry=DomainRegistry(ROOT),
        root=tmp_path,
        now=NOW,
    )
    assert (
        not report.ready
        and next(item for item in report.gates if item.identifier == "freshness").status.value
        == "FAIL"
    )
    future = _write_market(
        tmp_path,
        ticker="NVDA",
        price=100,
        provider="future",
        observed=NOW + timedelta(minutes=5),
        retrieved=NOW,
        source_id="future",
    )
    report = evaluate_market_quality(
        _profile(tmp_path, [future], {"future": 1}, max_age=60),
        registry=DomainRegistry(ROOT),
        root=tmp_path,
        now=NOW,
    )
    assert not report.ready
    left = _write_market(
        tmp_path,
        ticker="NVDA",
        price=100,
        provider="left",
        observed=NOW,
        retrieved=NOW,
        source_id="left",
    )
    right = _write_market(
        tmp_path,
        ticker="NVDA",
        price=101,
        provider="right",
        observed=NOW,
        retrieved=NOW,
        source_id="right",
    )
    report = evaluate_market_quality(
        _profile(tmp_path, [left, right], {"left": 1, "right": 1}),
        registry=DomainRegistry(ROOT),
        root=tmp_path,
        now=NOW,
    )
    assert not report.ready and any(
        "CONFLICT" in failure for item in report.gates for failure in item.failures
    )


def test_frozen_profile_and_stage_aware_requirements() -> None:
    registry = DomainRegistry(ROOT)
    report = evaluate_market_quality(
        ROOT / "data/research/nvda/market-quality-profile.json",
        registry=registry,
        root=ROOT,
        now=NOW,
    )
    assert report.ready  # frozen evidence has no currentness requirement
    profile = load_model_profile(ROOT / "data/model_profiles/fcff-research-v1.json")
    market_stage = evaluate_market_stage_readiness(profile, report, stage="market_comparison")
    assert market_stage.ready
    assert (
        evaluate_market_stage_readiness(profile, None, stage="market_comparison")
        .requirements[0]
        .status
        is RequirementStatus.QUALITY_BLOCKED
    )
    assert evaluate_market_stage_readiness(profile, None, stage="enterprise_valuation_core").ready
    eur_fact = replace(
        report.canonical_facts[0],
        normalized=replace(report.canonical_facts[0].normalized, currency="EUR"),
    )
    mismatch = replace(report, canonical_facts=(eur_fact,))
    assert (
        evaluate_market_stage_readiness(profile, mismatch, stage="market_comparison")
        .requirements[0]
        .status
        is RequirementStatus.MISSING
    )


def test_alphabet_security_separation_and_share_class_safety() -> None:
    registry = DomainRegistry(ROOT)
    assert registry.issuer_for("GOOG") == registry.issuer_for("GOOGL")
    first = NormalizedMarketObservation(
        "alphabet-inc:GOOGL",
        "price",
        101,
        "currency_per_share",
        "USD",
        NOW,
        NOW,
        "synthetic",
        "synthetic",
        "closed",
        "x",
        "one",
    )
    second = replace(first, security_id="alphabet-inc:GOOG", value=99, immutable_identity="two")
    assert (
        CanonicalMarketFact("price", first, "test").normalized.value
        != CanonicalMarketFact("price", second, "test").normalized.value
    )
    share = FinancialFact(
        "shares",
        "EntityCommonStockSharesOutstanding",
        100,
        "million shares",
        EvidenceKind.FACT,
        PeriodKind.INSTANT,
        None,
        date(2026, 9, 1),
        2026,
        "Q3",
        FilingRef(
            "x",
            "10-Q",
            date(2026, 9, 1),
            ROOT / "data/evidence/nvda/nvda-q2fy27-sec-evidence.txt",
            "x",
        ),
        "x",
        "x",
    )
    with pytest.raises(MarketEvidenceError, match="SHARE_CLASS"):
        derive_market_cap(
            price=CanonicalMarketFact("price", first, "test"),
            shares=share,
            share_count_semantic="current_shares_outstanding",
            security_has_single_listed_share_class=False,
        )


def test_market_cap_derivation_and_reconciliation() -> None:
    normalized = NormalizedMarketObservation(
        "nvidia-corporation:NVDA",
        "price",
        100,
        "currency_per_share",
        "USD",
        NOW,
        NOW,
        "fixture",
        "fixture",
        "closed",
        "x",
        "one",
    )
    share = FinancialFact(
        "shares",
        "EntityCommonStockSharesOutstanding",
        10,
        "million shares",
        EvidenceKind.FACT,
        PeriodKind.INSTANT,
        None,
        date(2026, 9, 1),
        2026,
        "Q3",
        FilingRef(
            "x",
            "10-Q",
            date(2026, 9, 1),
            ROOT / "data/evidence/nvda/nvda-q2fy27-sec-evidence.txt",
            "x",
        ),
        "x",
        "x",
    )
    derived = derive_market_cap(
        price=CanonicalMarketFact("price", normalized, "test"),
        shares=share,
        share_count_semantic="current_shares_outstanding",
        security_has_single_listed_share_class=True,
    )
    assert derived.value == 1_000_000_000
    provider = replace(normalized, metric_id="provider_market_cap", value=1_001_000_000)
    assert (
        reconcile_market_cap(
            derived=derived, provider=provider, tolerance=0.01, blocking=True
        ).status.value
        == "PASS"
    )
    assert (
        reconcile_market_cap(
            derived=derived,
            provider=replace(provider, value=2_000_000_000),
            tolerance=0.01,
            blocking=True,
        ).status.value
        == "FAIL"
    )
    with pytest.raises(MarketEvidenceError, match="INELIGIBLE"):
        derive_market_cap(
            price=CanonicalMarketFact("price", normalized, "test"),
            shares=share,
            share_count_semantic="diluted_weighted_average_shares",
            security_has_single_listed_share_class=True,
        )
