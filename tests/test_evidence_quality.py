"""Offline contract tests for generic evidence quality; no issuer branches exist here."""

# ruff: noqa: E501
import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from qhapaq_finance.evidence import (
    EvidenceError,
    FilingRef,
    FinancialFact,
    PeriodKind,
    reconstruct_ttm,
)
from qhapaq_finance.evidence_quality import (
    CanonicalFinancialFact,
    EvidenceQualityError,
    ExtractedFact,
    GateStatus,
    NormalizedFact,
    SourceManifest,
    evaluate_quality,
    explain_fact,
    load_source_manifest,
    normalize_scale,
    resolve_authoritative_fact,
    resolve_effective_sources,
    verify_source_integrity,
)

ROOT = Path(__file__).parents[1]


def _manifest(tmp_path: Path, *, raw: str = "source", supersedes: str | None = None) -> Path:
    artifact = tmp_path / "raw.txt"
    artifact.write_text(raw, encoding="utf-8")
    payload = {
        "schema_version": "source-manifest-v1",
        "issuer_id": "example",
        "source_id": "new",
        "source_type": "regulatory_filing",
        "authority": "SEC",
        "document_type": "10-Q",
        "raw_artifact": "raw.txt",
        "raw_artifact_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        "provenance_status": "verified",
    }
    if supersedes:
        payload["supersedes"] = supersedes
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_manifest_integrity_and_tamper_fail_closed(tmp_path: Path) -> None:
    path = _manifest(tmp_path)
    manifest = load_source_manifest(path, tmp_path)
    verify_source_integrity(manifest)
    (tmp_path / "raw.txt").write_text("tampered", encoding="utf-8")
    with pytest.raises(EvidenceQualityError, match="QUALITY_HASH_MISMATCH"):
        verify_source_integrity(manifest)
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(EvidenceQualityError, match="QUALITY_MANIFEST_INVALID"):
        load_source_manifest(path, tmp_path)


def test_scale_authority_conflict_and_amendment_selection(tmp_path: Path) -> None:
    extracted = ExtractedFact(
        "x",
        "example",
        "Revenue",
        "Revenue",
        12,
        "USD thousands",
        "USD",
        PeriodKind.DURATION,
        date(2025, 1, 1),
        date(2025, 3, 31),
        2025,
        "Q1",
        "a",
        "ctx",
        "p",
    )
    normalized = normalize_scale(
        extracted, multiplier=1000, normalized_unit="USD", transformation_id="scale:1000"
    )
    assert normalized.normalized_value == 12000
    first = CanonicalFinancialFact("a", normalized, "sec", "quality")
    other = CanonicalFinancialFact(
        "b", NormalizedFact(extracted, "Revenue", 13000, "USD", "x"), "issuer", "quality"
    )
    assert (
        resolve_authoritative_fact(
            (first, other),
            data_domain="regulatory_financial_statement",
            authority_policy={
                "regulatory_financial_statement": {"sec": 3, "issuer": 2},
                "market_price": {"issuer": 3, "sec": 1},
            },
        )
        == first
    )
    with pytest.raises(EvidenceQualityError, match="QUALITY_SOURCE_CONFLICT"):
        resolve_authoritative_fact(
            (first, other),
            data_domain="regulatory_financial_statement",
            authority_policy={"regulatory_financial_statement": {"sec": 3, "issuer": 3}},
        )
    old = SourceManifest(
        "source-manifest-v1",
        "example",
        "original",
        "regulatory_filing",
        "SEC",
        "10-Q",
        None,
        None,
        tmp_path / "raw.txt",
        "x",
        None,
        None,
        "verified",
    )
    amended = SourceManifest(
        "source-manifest-v1",
        "example",
        "amendment",
        "regulatory_filing",
        "SEC",
        "10-Q/A",
        None,
        None,
        tmp_path / "raw.txt",
        "x",
        None,
        "original",
        "verified",
    )
    assert resolve_effective_sources((old, amended)) == (amended,)
    assert old.source_id == "original"  # superseded evidence remains auditable


def test_profiles_gate_readiness_lineage_and_determinism() -> None:
    profile = ROOT / "data/research/qcom/evidence-quality-profile.json"
    first, second = evaluate_quality(profile, ROOT), evaluate_quality(profile, ROOT)
    assert first.research_ready and first.to_dict() == second.to_dict()
    assert (
        next(item for item in first.gates if item.identifier == "reconciliation").status
        is GateStatus.NOT_APPLICABLE
    )
    lineage = explain_fact(profile, "revenue_fy25", ROOT)
    assert lineage["raw_artifact_sha256"] and lineage["source_context"]


def test_golden_or_required_fact_failure_blocks_quality(tmp_path: Path) -> None:
    source = ROOT / "data/research/qcom/evidence-quality-profile.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["golden_facts"][0]["value"] = -1
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    report = evaluate_quality(path, ROOT)
    assert not report.research_ready
    assert (
        next(item for item in report.gates if item.identifier == "golden_facts").status
        is GateStatus.FAIL
    )
    payload["golden_facts"] = []
    payload["required_facts"].append("missing_fact")
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert not evaluate_quality(path, ROOT).research_ready


def test_golden_facts_are_optional_but_declared_mismatches_block(tmp_path: Path) -> None:
    payload = json.loads(
        (ROOT / "data/research/qcom/evidence-quality-profile.json").read_text(encoding="utf-8")
    )
    payload["golden_facts"] = []
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    absent = evaluate_quality(path, ROOT)
    gate = next(item for item in absent.gates if item.identifier == "golden_facts")
    assert gate.status is GateStatus.NOT_APPLICABLE and not gate.blocking
    payload["golden_facts"] = [
        {
            "fact_id": "revenue_fy25",
            "concept": "Revenue",
            "value": 44284,
            "unit": "USD million",
            "period_end": "2025-09-28",
        }
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")
    matched = evaluate_quality(path, ROOT)
    assert (
        next(item for item in matched.gates if item.identifier == "golden_facts").status
        is GateStatus.PASS
    )
    payload["golden_facts"][0]["value"] = 0
    path.write_text(json.dumps(payload), encoding="utf-8")
    mismatch = evaluate_quality(path, ROOT)
    gate = next(item for item in mismatch.gates if item.identifier == "golden_facts")
    assert gate.status is GateStatus.FAIL and gate.blocking and not mismatch.research_ready


def test_domain_authority_policy_can_differ() -> None:
    extracted = ExtractedFact(
        "x",
        "example",
        "Price",
        "Price",
        12,
        "USD",
        "USD",
        PeriodKind.INSTANT,
        None,
        date(2025, 3, 31),
        2025,
        "Q1",
        "a",
        None,
        "p",
    )
    first = CanonicalFinancialFact(
        "a",
        normalize_scale(extracted, multiplier=1, normalized_unit="USD", transformation_id="x"),
        "regulator",
        "quality",
        "market_price",
    )
    other = CanonicalFinancialFact(
        "b",
        normalize_scale(extracted, multiplier=1, normalized_unit="USD", transformation_id="x"),
        "market",
        "quality",
        "market_price",
    )
    policy = {
        "regulatory_financial_statement": {"regulator": 3, "market": 1},
        "market_price": {"regulator": 1, "market": 3},
    }
    assert (
        resolve_authoritative_fact(
            (first, other), data_domain="market_price", authority_policy=policy
        )
        == other
    )


def test_quality_content_identity_is_deterministic_and_input_sensitive(tmp_path: Path) -> None:
    source = ROOT / "data/research/qcom/evidence-quality-profile.json"
    first = evaluate_quality(source, ROOT)
    second = evaluate_quality(source, ROOT)
    assert first.to_dict() == second.to_dict() and first.content_identity == second.content_identity
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["evidence_set_id"] = "different-deterministic-input"
    changed = tmp_path / "profile.json"
    changed.write_text(json.dumps(payload), encoding="utf-8")
    assert evaluate_quality(changed, ROOT).content_identity != first.content_identity


def test_ttm_rejects_incompatible_periods() -> None:
    filing = FilingRef(
        "a", "10-Q", date(2025, 1, 1), ROOT / "data/evidence/nvda/nvda-fy26-10k-evidence.txt", "x"
    )

    def fact(identifier: str, value: float, start: date, end: date, period: str) -> FinancialFact:
        return FinancialFact(
            identifier,
            "Revenue",
            value,
            "USD",
            __import__("qhapaq_finance.evidence", fromlist=["EvidenceKind"]).EvidenceKind.FACT,
            PeriodKind.DURATION,
            start,
            end,
            2025,
            period,
            filing,
            "ctx",
            "x",
        )

    annual = fact("fy", 100, date(2024, 1, 1), date(2024, 12, 31), "FY")
    prior = fact("prior", 50, date(2024, 1, 1), date(2024, 6, 30), "H1")
    current = fact("current", 60, date(2025, 1, 1), date(2025, 3, 31), "H1")
    with pytest.raises(EvidenceError, match="not comparable"):
        reconstruct_ttm(annual=annual, prior_ytd=prior, current_ytd=current, identifier="ttm")
