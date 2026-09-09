from dataclasses import replace
from pathlib import Path

import pytest

from qhapaq_finance.accounting import AccountingError, AccountingSnapshot
from qhapaq_finance.evidence import EvidenceError, load_facts, reconstruct_ttm
from qhapaq_finance.qcom_case import QCOM_AS_OF, _accounting_snapshot

ROOT = Path(__file__).parents[1]
EVIDENCE = ROOT / "data/research/qcom/financial-evidence.json"


def test_evidence_normalizes_to_complete_ttm_accounting_snapshot() -> None:
    snapshot = _accounting_snapshot(load_facts(EVIDENCE, ROOT, as_of=QCOM_AS_OF))

    assert snapshot.period_label == "TTM"
    assert snapshot.revenue == 44_069
    assert snapshot.ebit == 10_220
    assert snapshot.nopat == pytest.approx(8_380.4)
    assert snapshot.depreciation_amortization == 1_934
    assert snapshot.capex == 1_858
    assert snapshot.change_in_working_capital == 475
    assert snapshot.fcff == pytest.approx(7_981.4)
    assert snapshot.cash == 4_533
    assert snapshot.debt == 15_270
    assert snapshot.valuation_shares == 1_050
    assert snapshot.invested_capital == pytest.approx(37_416.5)
    assert "ebit_fy25" in snapshot.source_lineage


def test_accounting_fails_closed_when_required_evidence_is_missing() -> None:
    facts = load_facts(EVIDENCE, ROOT, as_of=QCOM_AS_OF)
    facts.pop("capex_9m26")
    with pytest.raises(AccountingError, match="missing evidence for capex"):
        _accounting_snapshot(facts)


def test_accounting_never_treats_an_unknown_tax_basis_as_zero() -> None:
    snapshot = _accounting_snapshot(load_facts(EVIDENCE, ROOT, as_of=QCOM_AS_OF))
    unknown_tax = replace(snapshot, tax_rate=None)
    assert unknown_tax.nopat is None
    assert unknown_tax.fcff is None


def test_accounting_normalizes_negative_raw_capex_to_positive_cash_use() -> None:
    snapshot = _accounting_snapshot(load_facts(EVIDENCE, ROOT, as_of=QCOM_AS_OF))
    assert snapshot.capex == 1_858


def test_accounting_rejects_raw_capex_with_the_wrong_declared_sign() -> None:
    facts = load_facts(EVIDENCE, ROOT, as_of=QCOM_AS_OF)
    malformed = dict(facts)
    malformed["capex_fy25"] = replace(malformed["capex_fy25"], value=1_192)
    with pytest.raises(AccountingError, match="negative_cash_outflow"):
        _accounting_snapshot(malformed)


def test_accounting_rejects_negative_normalized_capex_cash_use() -> None:
    snapshot = _accounting_snapshot(load_facts(EVIDENCE, ROOT, as_of=QCOM_AS_OF))
    with pytest.raises(AccountingError, match="capex_cash_use"):
        AccountingSnapshot(**{**snapshot.__dict__, "capex": -1.0})


def test_accounting_rejects_mismatched_flow_end_and_share_scale() -> None:
    facts = load_facts(EVIDENCE, ROOT, as_of=QCOM_AS_OF)
    wrong_end = dict(facts)
    wrong_end["revenue_9m26"] = replace(wrong_end["revenue_9m26"], period_end=QCOM_AS_OF)
    with pytest.raises(EvidenceError, match="not comparable"):
        _accounting_snapshot(wrong_end)

    wrong_shares = dict(facts)
    wrong_shares["shares_cover_q3fy26"] = replace(
        wrong_shares["shares_cover_q3fy26"], unit="shares"
    )
    with pytest.raises(AccountingError, match="share-count scale"):
        _accounting_snapshot(wrong_shares)


def test_accounting_rejects_valid_six_month_balance_sheets_for_ttm_working_capital() -> None:
    facts = load_facts(EVIDENCE, ROOT, as_of=QCOM_AS_OF)
    mismatched = dict(facts)
    for identifier in (
        "ar_fy25",
        "inventory_fy25",
        "ap_fy25",
        "accruals_fy25",
        "net_operating_assets_fy25",
    ):
        mismatched[identifier] = replace(mismatched[identifier], period_end=QCOM_AS_OF)
    with pytest.raises(AccountingError, match="opening balance-sheet date"):
        from qhapaq_finance.accounting import normalize_accounting_snapshot
        from qhapaq_finance.qcom_case import QCOM_ACCOUNTING_SPEC

        normalize_accounting_snapshot(
            mismatched,
            spec=replace(QCOM_ACCOUNTING_SPEC, require_ttm_endpoint_alignment=True),
            tax_rate=0.18,
        )


def test_accounting_rejects_basic_shares_mislabeled_as_diluted() -> None:
    facts = load_facts(EVIDENCE, ROOT, as_of=QCOM_AS_OF)
    # The QCOM mapping is explicitly a current-common-share basis. Declaring its
    # cover-page fact to be diluted weighted-average shares must fail closed.
    from qhapaq_finance.qcom_case import QCOM_ACCOUNTING_SPEC

    bad_spec = replace(QCOM_ACCOUNTING_SPEC, valuation_share_basis="diluted_weighted_average")
    with pytest.raises(AccountingError, match="does not match its declared basis"):
        from qhapaq_finance.accounting import normalize_accounting_snapshot

        normalize_accounting_snapshot(facts, spec=bad_spec, tax_rate=0.18)


def test_ttm_rejects_unit_mismatch_and_nonfinite_evidence() -> None:
    facts = load_facts(EVIDENCE, ROOT, as_of=QCOM_AS_OF)
    with pytest.raises(EvidenceError, match="one unit"):
        reconstruct_ttm(
            annual=facts["revenue_fy25"],
            prior_ytd=replace(facts["revenue_9m25"], unit="EUR million"),
            current_ytd=facts["revenue_9m26"],
            identifier="bad-unit",
        )
    with pytest.raises(EvidenceError, match="finite"):
        replace(facts["revenue_fy25"], value=float("nan"))
