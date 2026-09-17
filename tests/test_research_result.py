from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from qhapaq_finance.evidence_quality import content_identity
from qhapaq_finance.market_inputs import MarketProvenance
from qhapaq_finance.research_result import (
    ResearchResultError,
    _market,
    build_canonical_research_result,
    canonical_research_json,
)
from qhapaq_finance.universe import DomainRegistry
from qhapaq_finance.valuation import analyze_case, load_fixture_case

ROOT = Path(__file__).resolve().parents[1]


def test_canonical_research_result_is_stable_and_has_no_machine_path() -> None:
    first = build_canonical_research_result("QCOM", ROOT)
    second = build_canonical_research_result("QCOM", ROOT)
    assert first.schema_version == "research-result-v1"
    assert first.content_identity == second.content_identity
    assert canonical_research_json(first) == canonical_research_json(second)
    assert "/home/" not in canonical_research_json(first)
    assert "/tmp/" not in canonical_research_json(first)


def test_qcom_keeps_legacy_market_and_financial_identity() -> None:
    result = build_canonical_research_result("QCOM", ROOT)
    assert result.issuer["issuer_id"] == "qualcomm-incorporated"
    assert result.security["security_id"] == "qualcomm-incorporated:QCOM"
    assert result.research_as_of.isoformat() == "2026-09-08"
    assert result.market_provenance.source_mode == "legacy"
    assert result.market_provenance.market_quality_identity is None
    assert result.model["profile_id"] == "fcff-research"
    qcom_valuation = analyze_case(load_fixture_case("QCOM", ROOT))
    assert result.valuation["normalized_fcff"] == qcom_valuation.normalized_fcff


def test_nvda_keeps_canonical_market_identities() -> None:
    result = build_canonical_research_result("NVDA", ROOT)
    market = result.market_provenance
    assert market.source_mode == "canonical"
    assert market.market_quality_identity
    assert market.price_fact_identity
    assert market.canonical_observation_identity


def test_fixture_stays_fixture_and_semantic_change_changes_identity() -> None:
    fixture = build_canonical_research_result("CSCO", ROOT)
    assert fixture.financial_evidence["kind"] == "fixture"
    assert fixture.market_provenance.source_mode == "fixture"
    changed = replace(
        fixture,
        research_as_of=fixture.research_as_of.replace(day=fixture.research_as_of.day - 1),
        content_identity="",
    )
    assert content_identity(changed.payload(include_identity=False)) != fixture.content_identity


def test_market_security_mismatch_is_rejected() -> None:
    result = analyze_case(load_fixture_case("QCOM", ROOT))
    bad = MarketProvenance(
        "nvidia-corporation:NVDA",
        "nvidia-corporation",
        "legacy",
        None,
        result.case.as_of_date,
        "USD",
    )
    with pytest.raises(ResearchResultError, match="SECURITY"):
        _market(
            replace(result, case=replace(result.case, market_provenance=bad)),
            DomainRegistry(ROOT).security("QCOM"),
        )
