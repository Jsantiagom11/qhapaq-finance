import shutil
from dataclasses import replace
from pathlib import Path

import pytest

import qhapaq_finance.accounting as accounting
from qhapaq_finance.accounting import AccountingError, AccountingSnapshot
from qhapaq_finance.analysis import CompanyIdentity
from qhapaq_finance.evidence import EvidenceError, load_facts, reconstruct_ttm
from qhapaq_finance.local_sec_corpus import LocalSecCorpus
from qhapaq_finance.qcom_case import QCOM_AS_OF, _accounting_snapshot

ROOT = Path(__file__).parents[1]
EVIDENCE = ROOT / "data/research/qcom/financial-evidence.json"


@pytest.fixture
def aapl_corpus(tmp_path: Path) -> LocalSecCorpus:
    shutil.copytree(
        ROOT / "tests/fixtures/sec_corpus/AAPL",
        tmp_path / "data/cache/sec_corpus_live/AAPL",
    )
    return LocalSecCorpus(tmp_path)


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
    assert snapshot.invested_capital is not None
    assert snapshot.invested_capital.opening.top_down.value == pytest.approx(37_429)
    assert snapshot.invested_capital.closing.top_down.value == pytest.approx(37_404)
    assert snapshot.invested_capital.average == pytest.approx(37_416.5)
    assert "ebit_fy25" in snapshot.source_lineage


def test_promoted_evidence_translates_to_accounting_evidence_spec() -> None:
    source = load_facts(EVIDENCE, ROOT, as_of=QCOM_AS_OF)

    facts = {
        "revenue": source["revenue_fy25"],
        "ebit": source["ebit_fy25"],
        "depreciation_amortization": source["da_fy25"],
        "capex": source["capex_fy25"],
        "income_tax_expense": replace(
            source["revenue_fy25"],
            id="income_tax_expense",
        ),
        "pretax_income": replace(
            source["ebit_fy25"],
            id="pretax_income",
        ),
        "operating_current_assets_opening": replace(
            source["ar_q3fy26"],
            id="operating_current_assets_opening",
        ),
        "operating_current_liabilities_opening": replace(
            source["ap_q3fy26"],
            id="operating_current_liabilities_opening",
        ),
        "operating_current_assets_closing": replace(
            source["ar_q3fy26"],
            id="operating_current_assets_closing",
        ),
        "operating_current_liabilities_closing": replace(
            source["ap_q3fy26"],
            id="operating_current_liabilities_closing",
        ),
        "net_operating_assets_opening": replace(
            source["net_operating_assets_q3fy26"],
            id="net_operating_assets_opening",
        ),
        "net_operating_assets_closing": replace(
            source["net_operating_assets_q3fy26"],
            id="net_operating_assets_closing",
        ),
        "cash": source["cash_q3fy26"],
        "marketable_securities": source["marketable_securities_q3fy26"],
        "total_debt": source["long_term_debt_q3fy26"],
        "valuation_shares": source["shares_cover_q3fy26"],
    }

    spec = accounting.accounting_evidence_spec_from_promoted_facts(facts)

    assert spec.operating_nwc_opening_assets == ("operating_current_assets_opening",)
    assert spec.operating_nwc_opening_liabilities == ("operating_current_liabilities_opening",)
    assert spec.operating_nwc_closing_assets == ("operating_current_assets_closing",)
    assert spec.operating_nwc_closing_liabilities == ("operating_current_liabilities_closing",)
    assert spec.net_operating_assets_opening == ("net_operating_assets_opening",)
    assert spec.net_operating_assets_closing == ("net_operating_assets_closing",)
    assert spec.require_ttm_endpoint_alignment is True


def test_promoted_evidence_adapter_fails_closed_when_a_canonical_metric_is_missing() -> None:
    with pytest.raises(AccountingError, match="missing promoted accounting metric"):
        accounting.accounting_evidence_spec_from_promoted_facts({})


def test_local_sec_corpus_promotes_aapl_to_accounting_evidence_spec(
    aapl_corpus: LocalSecCorpus,
) -> None:
    facts, spec = accounting.promote_local_sec_accounting_evidence(
        aapl_corpus,
        CompanyIdentity("AAPL", None, None, None, None, None, "0000320193", None),
    )

    assert facts["cash"].source_accessions
    assert spec.cash == ("cash",)
    assert spec.debt == ("total_debt",)


def test_local_sec_corpus_promotes_aapl_to_accounting_snapshot(
    aapl_corpus: LocalSecCorpus,
) -> None:
    facts, spec = accounting.promote_local_sec_accounting_evidence(
        aapl_corpus,
        CompanyIdentity("AAPL", None, None, None, None, None, "0000320193", None),
    )

    snapshot = accounting.normalize_accounting_snapshot(facts, spec=spec, tax_rate=None)

    assert snapshot.cash is not None


def test_local_sec_corpus_promotes_aapl_effective_tax_rate_from_compatible_ttm_facts(
    aapl_corpus: LocalSecCorpus,
) -> None:
    facts, spec = accounting.promote_local_sec_accounting_evidence(
        aapl_corpus,
        CompanyIdentity("AAPL", None, None, None, None, None, "0000320193", None),
    )

    snapshot = accounting.normalize_accounting_snapshot(facts, spec=spec, tax_rate=None)

    assert facts["income_tax_expense"].period_end == facts["pretax_income"].period_end
    assert snapshot.income_tax_expense == pytest.approx(26_976_000_000)
    assert snapshot.pretax_income == pytest.approx(155_906_000_000)
    assert snapshot.tax_rate == pytest.approx(26_976_000_000 / 155_906_000_000)
    assert "income_tax_expense" in snapshot.source_lineage
    assert "pretax_income" in snapshot.source_lineage


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


def test_local_sec_accounting_derives_balance_sheet_endpoints_from_ttm_period(
    aapl_corpus: LocalSecCorpus,
) -> None:
    from datetime import timedelta

    facts, spec = accounting.promote_local_sec_accounting_evidence(
        aapl_corpus,
        CompanyIdentity("AAPL", None, None, None, None, None, "0000320193", None),
    )

    revenue = facts["revenue"]
    assert revenue.period_start is not None

    opening_end = revenue.period_start - timedelta(days=1)
    closing_end = revenue.period_end

    assert facts["operating_current_assets_opening"].period_end == opening_end
    assert facts["operating_current_liabilities_opening"].period_end == opening_end

    assert facts["operating_current_assets_closing"].period_end == closing_end
    assert facts["operating_current_liabilities_closing"].period_end == closing_end

    assert facts["cash"].period_end == closing_end
    assert facts["marketable_securities"].period_end == closing_end
    assert facts["total_debt"].period_end == closing_end

    # AAPL lacks a homogeneous opening/closing NOA representation for this TTM.
    assert "net_operating_assets_opening" not in facts
    assert "net_operating_assets_closing" not in facts
    assert spec.net_operating_assets_opening == ()
    assert spec.net_operating_assets_closing == ()


def test_accounting_snapshot_can_omit_invested_capital_when_noa_pair_is_unavailable() -> None:
    from dataclasses import replace

    from qhapaq_finance.qcom_case import QCOM_ACCOUNTING_SPEC

    facts = load_facts(EVIDENCE, ROOT, as_of=QCOM_AS_OF)
    spec = replace(
        QCOM_ACCOUNTING_SPEC,
        net_operating_assets_opening=(),
        net_operating_assets_closing=(),
    )

    snapshot = accounting.normalize_accounting_snapshot(
        facts,
        spec=spec,
        tax_rate=0.18,
    )

    assert snapshot.invested_capital is None
    assert snapshot.change_in_working_capital == 475
    assert snapshot.fcff == pytest.approx(7_981.4)


def test_aapl_financing_identity_remains_complete_when_opening_intangibles_are_missing(
    aapl_corpus: LocalSecCorpus,
) -> None:
    facts, spec = accounting.promote_local_sec_accounting_evidence(
        aapl_corpus,
        CompanyIdentity("AAPL", None, None, None, None, None, "0000320193", None),
    )

    snapshot = accounting.normalize_accounting_snapshot(facts, spec=spec, tax_rate=None)

    assert snapshot.invested_capital is not None
    assert snapshot.invested_capital.opening.top_down.value == pytest.approx(34_542_000_000)
    assert snapshot.invested_capital.closing.top_down.value == pytest.approx(45_347_000_000)
    assert snapshot.invested_capital.average == pytest.approx(39_944_500_000)
    assert snapshot.invested_capital.opening.bottom_up is not None
    assert snapshot.invested_capital.opening.bottom_up.components["net_intangibles"].value is None
