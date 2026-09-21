from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from qhapaq_finance.financial_canonicalization import (
    PeriodKind,
    SemanticEvidence,
    XbrlCalculationArc,
    XbrlConcept,
    XbrlLabel,
    XbrlPresentationArc,
    XbrlRelationshipSet,
    extract_company_facts,
)
from qhapaq_finance.sec_canonical_gate import (
    SecCanonicalGapReason,
    SecCanonicalGateState,
    evaluate_sec_canonical_gate,
)

ROOT = Path(__file__).resolve().parents[1]


def _aapl_facts():
    path = ROOT / "tests/fixtures/sec_corpus/AAPL/companyfacts.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return extract_company_facts(payload, source_identity="fixture-companyfacts")


def test_gate_returns_ready_snapshot_from_complete_canonical_sec_evidence() -> None:
    result = evaluate_sec_canonical_gate(_aapl_facts())

    assert result.state is SecCanonicalGateState.READY
    assert result.reason is None
    assert result.snapshot is not None
    assert result.snapshot.revenue == 466_823_000_000.0


def test_gate_returns_typed_recoverable_gap_when_standard_concept_is_absent() -> None:
    facts = tuple(
        fact
        for fact in _aapl_facts()
        if fact.concept != "RevenueFromContractWithCustomerExcludingAssessedTax"
    )

    result = evaluate_sec_canonical_gate(facts)

    assert result.state is SecCanonicalGateState.GAP
    assert result.reason is SecCanonicalGapReason.MISSING_STANDARD_CONCEPT
    assert result.snapshot is None


def test_gate_blocks_conflicting_source_observations() -> None:
    facts = _aapl_facts()
    revenue = next(
        fact
        for fact in facts
        if fact.concept == "RevenueFromContractWithCustomerExcludingAssessedTax"
        and fact.fiscal_period == "FY"
        and fact.end.isoformat() == "2025-09-27"
    )
    conflicting = replace(
        revenue,
        fact_id=f"{revenue.fact_id}:conflict",
        value=revenue.value + 1.0,
        source_identity="verified-filing",
    )

    result = evaluate_sec_canonical_gate((*facts, conflicting))

    assert result.state is SecCanonicalGateState.BLOCKED
    assert result.reason is SecCanonicalGapReason.CANONICAL_CONFLICT
    assert result.snapshot is None


def test_gate_blocks_ambiguous_required_instant_evidence() -> None:
    facts = _aapl_facts()
    cash = next(
        fact
        for fact in facts
        if fact.concept == "CashAndCashEquivalentsAtCarryingValue"
        and fact.end.isoformat() == "2026-06-27"
    )

    result = evaluate_sec_canonical_gate((*facts, replace(cash, fact_id="ambiguous-cash")))

    assert result.state is SecCanonicalGateState.BLOCKED
    assert result.reason is SecCanonicalGapReason.AMBIGUOUS_CONTEXT
    assert result.snapshot is None


def test_gate_returns_period_coverage_gap_for_missing_ttm_anchor() -> None:
    facts = tuple(
        fact
        for fact in _aapl_facts()
        if not (
            fact.concept == "RevenueFromContractWithCustomerExcludingAssessedTax"
            and fact.fiscal_period == "FY"
        )
    )

    result = evaluate_sec_canonical_gate(facts)

    assert result.state is SecCanonicalGateState.GAP
    assert result.reason is SecCanonicalGapReason.PERIOD_COVERAGE_GAP
    assert result.snapshot is None


def test_gate_returns_component_gap_when_required_composite_component_is_absent() -> None:
    facts = tuple(
        fact for fact in _aapl_facts() if fact.concept != "MarketableSecuritiesNoncurrent"
    )

    result = evaluate_sec_canonical_gate(facts)

    assert result.state is SecCanonicalGateState.GAP
    assert result.reason is SecCanonicalGapReason.REQUIRED_COMPONENT_MISSING
    assert result.snapshot is None


def _revenue_semantic() -> SemanticEvidence:
    qname = "acme:CustomRevenue"
    role = "statement"
    return SemanticEvidence(
        XbrlConcept(qname, "http://example.com/acme", None, PeriodKind.DURATION, None, None),
        (XbrlLabel("label", "Revenue"),),
        XbrlRelationshipSet(
            (XbrlPresentationArc("us-gaap:Revenue", qname, role, 1.0, None),),
            (XbrlCalculationArc("us-gaap:Revenue", qname, 1.0, role, True),),
        ),
        "revenue",
        "verified-relationships",
    )


def test_verified_standard_filing_fact_repairs_companyfacts_gap() -> None:
    facts = _aapl_facts()
    companyfacts = tuple(
        fact
        for fact in facts
        if fact.concept != "RevenueFromContractWithCustomerExcludingAssessedTax"
    )
    filing_native = tuple(
        replace(fact, fact_id=f"filing:{fact.fact_id}", source_identity="verified-filing")
        for fact in facts
        if fact.concept == "RevenueFromContractWithCustomerExcludingAssessedTax"
    )

    before = evaluate_sec_canonical_gate(companyfacts)
    after = evaluate_sec_canonical_gate((*companyfacts, *filing_native))

    assert before.state is SecCanonicalGateState.GAP
    assert after.state is SecCanonicalGateState.READY


def test_structurally_authorized_extension_repairs_gap_but_label_does_not() -> None:
    facts = _aapl_facts()
    companyfacts = tuple(
        fact
        for fact in facts
        if fact.concept != "RevenueFromContractWithCustomerExcludingAssessedTax"
    )
    extension_facts = tuple(
        replace(
            fact,
            fact_id=f"extension:{fact.fact_id}",
            taxonomy="acme",
            concept="CustomRevenue",
            source_identity="verified-filing",
        )
        for fact in facts
        if fact.concept == "RevenueFromContractWithCustomerExcludingAssessedTax"
    )

    label_only = evaluate_sec_canonical_gate((*companyfacts, *extension_facts))
    structural = evaluate_sec_canonical_gate(
        (*companyfacts, *extension_facts),
        semantic_extensions={("acme", "CustomRevenue"): _revenue_semantic()},
    )

    assert label_only.state is SecCanonicalGateState.GAP
    assert structural.state is SecCanonicalGateState.READY


def test_structural_extension_conflict_fails_closed() -> None:
    facts = _aapl_facts()
    extension_facts = tuple(
        replace(
            fact,
            fact_id=f"conflicting-extension:{fact.fact_id}",
            taxonomy="acme",
            concept="CustomRevenue",
            value=fact.value + 1_000_000.0,
            source_identity="verified-filing",
        )
        for fact in facts
        if fact.concept == "RevenueFromContractWithCustomerExcludingAssessedTax"
    )

    result = evaluate_sec_canonical_gate(
        (*facts, *extension_facts),
        semantic_extensions={("acme", "CustomRevenue"): _revenue_semantic()},
    )

    assert result.state is SecCanonicalGateState.BLOCKED


def test_unrelated_disclosure_conflict_does_not_block_accounting_gate() -> None:
    facts = _aapl_facts()
    revenue = next(
        fact
        for fact in facts
        if fact.concept == "RevenueFromContractWithCustomerExcludingAssessedTax"
        and fact.fiscal_period == "FY"
    )

    unrelated_a = replace(
        revenue,
        fact_id="unrelated-disclosure:a",
        concept="UnrecognizedTaxBenefits",
        value=1_000_000_000.0,
        source_identity="verified-filing:a",
    )
    unrelated_b = replace(
        revenue,
        fact_id="unrelated-disclosure:b",
        concept="UnrecognizedTaxBenefits",
        value=1_100_000_000.0,
        source_identity="verified-filing:b",
    )

    result = evaluate_sec_canonical_gate((*facts, unrelated_a, unrelated_b))

    assert result.state is SecCanonicalGateState.READY
    assert result.reason is None


def test_nested_authorized_policy_concept_conflict_still_blocks() -> None:
    facts = _aapl_facts()
    revenue = next(
        fact
        for fact in facts
        if fact.concept == "RevenueFromContractWithCustomerExcludingAssessedTax"
        and fact.fiscal_period == "FY"
    )

    depreciation_a = replace(
        revenue,
        fact_id="nested-policy:a",
        concept="Depreciation",
        value=1_000_000_000.0,
        source_identity="verified-filing:a",
    )
    depreciation_b = replace(
        revenue,
        fact_id="nested-policy:b",
        concept="Depreciation",
        value=1_100_000_000.0,
        source_identity="verified-filing:b",
    )

    result = evaluate_sec_canonical_gate((*facts, depreciation_a, depreciation_b))

    assert result.state is SecCanonicalGateState.BLOCKED
    assert result.reason is SecCanonicalGapReason.CANONICAL_CONFLICT
