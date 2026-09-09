from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from qhapaq_finance.evidence import (
    EvidenceError,
    EvidenceKind,
    PeriodKind,
    load_facts,
    reconstruct_ttm,
)
from qhapaq_finance.qcom_case import (
    QCOM_AS_OF,
    _require_reconciled,
    load_qcom_case,
    qcom_audit,
)
from qhapaq_finance.valuation import analyze_case

ROOT = Path(__file__).parents[1]
EVIDENCE = ROOT / "data/research/qcom/financial-evidence.json"


def test_filing_metadata_provenance_and_no_lookahead() -> None:
    facts = load_facts(EVIDENCE, ROOT, as_of=QCOM_AS_OF)
    fact = facts["ebit_9m26"]
    assert fact.filing.accession_number == "0000804328-26-000086"
    assert fact.filing.filing_date == date(2026, 7, 29)
    assert fact.filing.sha256 and fact.locator and fact.method
    assert fact.kind is EvidenceKind.FACT
    with pytest.raises(EvidenceError, match="as-of"):
        load_facts(EVIDENCE, ROOT, as_of=date(2026, 7, 1))


def test_period_aware_ttm_rejects_overlap_and_instant_mix() -> None:
    facts = load_facts(EVIDENCE, ROOT, as_of=QCOM_AS_OF)
    ttm = reconstruct_ttm(
        annual=facts["revenue_fy25"],
        prior_ytd=facts["revenue_9m25"],
        current_ytd=facts["revenue_9m26"],
        identifier="test",
    )
    assert ttm.kind is EvidenceKind.DERIVED and ttm.value == 44069
    with pytest.raises(EvidenceError, match="duration"):
        reconstruct_ttm(
            annual=facts["revenue_fy25"],
            prior_ytd=facts["revenue_9m25"],
            current_ytd=facts["cash_q3fy26"],
            identifier="bad",
        )
    with pytest.raises(EvidenceError, match="comparable"):
        reconstruct_ttm(
            annual=facts["revenue_fy25"],
            prior_ytd=facts["revenue_fy25"],
            current_ytd=facts["revenue_9m26"],
            identifier="bad",
        )


def test_qcom_case_fcff_nwc_sbc_and_offline_replay() -> None:
    first, second = load_qcom_case(ROOT), load_qcom_case(ROOT)
    assert first == second
    result = analyze_case(first)
    audit = qcom_audit(ROOT)
    assert result.normalized_fcff == result.reconstructed_fcff
    assert audit["change_operating_nwc"] == 475
    assert "not added again" in str(audit["sbc_treatment"])
    assert first.market_snapshot.shares_outstanding == 1050
    assert first.market_snapshot.debt == 15270
    assert first.market_snapshot.cash_and_equivalents == 4533
    assert first.market_snapshot.marketable_securities == 3771
    assert result.roic == pytest.approx(result.nopat / first.invested_capital)


def test_normalization_conservation_and_period_kind_are_explicit() -> None:
    case = load_qcom_case(ROOT)
    result = analyze_case(case)
    adjustment_total = sum(item.amount for item in case.normalization_adjustments)
    assert result.normalized_fcff == result.reconstructed_fcff + adjustment_total
    facts = load_facts(EVIDENCE, ROOT, as_of=QCOM_AS_OF)
    assert facts["cash_q3fy26"].period_kind is PeriodKind.INSTANT
    assert facts["capex_9m26"].period_kind is PeriodKind.DURATION


def test_audited_ttm_and_primary_balance_sheet_bridges() -> None:
    facts = load_facts(EVIDENCE, ROOT, as_of=QCOM_AS_OF)
    assert (
        reconstruct_ttm(
            annual=facts["revenue_fy25"],
            prior_ytd=facts["revenue_9m25"],
            current_ytd=facts["revenue_9m26"],
            identifier="revenue",
        ).value
        == 44_069
    )
    assert (
        reconstruct_ttm(
            annual=facts["ebit_fy25"],
            prior_ytd=facts["ebit_9m25"],
            current_ytd=facts["ebit_9m26"],
            identifier="ebit",
        ).value
        == 10_220
    )
    assert facts["cash_q3fy26"].value + facts["marketable_securities_q3fy26"].value == 8_304
    assert facts["short_term_debt_q3fy26"].value + facts["long_term_debt_q3fy26"].value == 15_270
    assert facts["shares_balance_q3fy26"].period_end == date(2026, 6, 28)
    assert facts["shares_cover_q3fy26"].period_end == date(2026, 7, 27)


def test_qcom_valuation_gate_refuses_unreconciled_primary_evidence() -> None:
    facts = load_facts(EVIDENCE, ROOT, as_of=QCOM_AS_OF)
    bad = dict(facts)
    bad["revenue_9m26"] = replace(bad["revenue_9m26"], value=32_799)
    with pytest.raises(ValueError, match="reconciliation failed for TTM revenue"):
        _require_reconciled(bad)
