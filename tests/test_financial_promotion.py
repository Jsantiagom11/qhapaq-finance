from dataclasses import fields, replace
from datetime import date
from pathlib import Path

import pytest

from qhapaq_finance import financial_promotion
from qhapaq_finance.accounting import AccountingEvidenceSpec
from qhapaq_finance.evidence import EvidenceKind, FilingRef, FinancialFact
from qhapaq_finance.evidence import PeriodKind as EvidencePeriodKind
from qhapaq_finance.financial_canonicalization import PeriodKind, RawFact, extract_company_facts
from qhapaq_finance.financial_promotion import (
    FinancialPromotionError,
    MetricPromotionPolicy,
    MultiPeriodFinancialPromoter,
    PromotionStrategy,
    accounting_evidence_policies,
)


def _instant(**changes: object) -> RawFact:
    base = RawFact(
        "cash",
        "us-gaap",
        "CashAndCashEquivalentsAtCarryingValue",
        10,
        "USD",
        PeriodKind.INSTANT,
        None,
        date(2025, 12, 31),
        2025,
        "FY",
        "10-K",
        "0000000000-25-000001",
        date(2026, 1, 1),
        "sha",
    )
    from dataclasses import replace

    return replace(base, **changes)


def _fact(value: float, start: date, end: date, fp: str, *, unit: str = "USD") -> RawFact:
    return RawFact(
        "id" + fp + end.isoformat(),
        "us-gaap",
        "OperatingIncomeLoss",
        value,
        unit,
        PeriodKind.DURATION,
        start,
        end,
        2025,
        fp,
        "10-Q" if fp != "FY" else "10-K",
        "0000000000-25-000001",
        date(2026, 1, 1),
        "sha",
    )


def _canonical_instant(
    identifier: str, end: date, *, unit: str = "USD", method: str = "canonical SEC company facts"
) -> FinancialFact:
    return FinancialFact(
        identifier,
        "net_working_capital",
        10,
        unit,
        EvidenceKind.FACT,
        EvidencePeriodKind.INSTANT,
        None,
        end,
        2026,
        "Q3",
        FilingRef("0000000000-26-000001", "10-Q", date(2026, 7, 1), Path("."), "sha"),
        identifier,
        method,
        (identifier,),
        ("0000000000-26-000001",),
    )


def test_promoter_selects_only_comparable_fy_and_ytd_contexts() -> None:
    facts = (
        _fact(100, date(2022, 1, 1), date(2022, 12, 31), "FY"),
        _fact(70, date(2022, 1, 1), date(2022, 9, 30), "Q3"),
        _fact(90, date(2023, 1, 1), date(2023, 9, 30), "Q3"),
    )
    result = MultiPeriodFinancialPromoter().promote_ttm(facts, concept="OperatingIncomeLoss")
    assert result.value == 120


def test_promoter_rejects_incompatible_ytd_windows() -> None:
    facts = (
        _fact(100, date(2024, 1, 1), date(2024, 12, 31), "FY"),
        _fact(70, date(2024, 1, 1), date(2024, 6, 30), "Q2"),
        _fact(90, date(2025, 1, 1), date(2025, 9, 30), "Q3"),
    )
    with pytest.raises(FinancialPromotionError):
        MultiPeriodFinancialPromoter().promote_ttm(facts, concept="OperatingIncomeLoss")


def test_promoter_uses_the_annual_period_preceding_the_latest_comparable_ytd_pair() -> None:
    facts = (
        replace(_fact(80, date(2020, 1, 1), date(2020, 12, 31), "FY"), fiscal_year=2020),
        replace(_fact(100, date(2021, 1, 1), date(2021, 12, 31), "FY"), fiscal_year=2021),
        replace(_fact(70, date(2021, 1, 1), date(2021, 9, 30), "Q3"), fiscal_year=2021),
        replace(_fact(90, date(2022, 1, 1), date(2022, 9, 30), "Q3"), fiscal_year=2022),
    )

    result = MultiPeriodFinancialPromoter().promote_ttm(facts, concept="OperatingIncomeLoss")

    assert result.value == 120


def test_declarative_policy_promotes_the_authorized_concept_only() -> None:
    policy = MetricPromotionPolicy(
        "ebit", ("OperatingIncomeLoss",), "USD", PromotionStrategy.TTM_DURATION
    )
    facts = (
        _fact(100, date(2022, 1, 1), date(2022, 12, 31), "FY"),
        _fact(70, date(2022, 1, 1), date(2022, 9, 30), "Q3"),
        _fact(90, date(2023, 1, 1), date(2023, 9, 30), "Q3"),
    )
    assert MultiPeriodFinancialPromoter().promote(facts, policy=policy).value == 120


@pytest.mark.parametrize(
    ("metric_id", "concept"),
    (
        ("income_tax_expense", "IncomeTaxExpenseBenefit"),
        (
            "pretax_income",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        ),
    ),
)
def test_tax_duration_policies_promote_only_their_authorized_concept(
    metric_id: str, concept: str
) -> None:
    policy = MetricPromotionPolicy(metric_id, (concept,), "USD", PromotionStrategy.TTM_DURATION)
    facts = tuple(
        replace(item, concept=concept)
        for item in (
            _fact(100, date(2022, 1, 1), date(2022, 12, 31), "FY"),
            _fact(70, date(2022, 1, 1), date(2022, 9, 30), "Q3"),
            _fact(90, date(2023, 1, 1), date(2023, 9, 30), "Q3"),
        )
    )

    assert MultiPeriodFinancialPromoter().promote(facts, policy=policy).value == 120


@pytest.mark.parametrize(
    "changes",
    (
        {"unit": "EUR"},
        {"dimensions": ("segment",)},
    ),
)
def test_tax_duration_policy_rejects_wrong_unit_or_dimensional_evidence(
    changes: dict[str, object],
) -> None:
    policy = MetricPromotionPolicy(
        "income_tax_expense", ("IncomeTaxExpenseBenefit",), "USD", PromotionStrategy.TTM_DURATION
    )
    facts = tuple(
        replace(item, concept="IncomeTaxExpenseBenefit", **changes)
        for item in (
            _fact(100, date(2022, 1, 1), date(2022, 12, 31), "FY"),
            _fact(70, date(2022, 1, 1), date(2022, 9, 30), "Q3"),
            _fact(90, date(2023, 1, 1), date(2023, 9, 30), "Q3"),
        )
    )

    with pytest.raises(FinancialPromotionError):
        MultiPeriodFinancialPromoter().promote(facts, policy=policy)


@pytest.mark.parametrize(
    "changes",
    ({"unit": "EUR"}, {"dimensions": ("axis",)}, {"consolidated": False}, {"filing_form": "8-K"}),
)
def test_direct_instant_rejects_incompatible_facts(changes: dict[str, object]) -> None:
    policy = MetricPromotionPolicy(
        "cash", ("CashAndCashEquivalentsAtCarryingValue",), "USD", PromotionStrategy.DIRECT_INSTANT
    )
    with pytest.raises(FinancialPromotionError):
        MultiPeriodFinancialPromoter().promote((_instant(**changes),), policy=policy)


def test_direct_instant_promotes_one_unique_lineaged_fact() -> None:
    policy = MetricPromotionPolicy(
        "cash", ("CashAndCashEquivalentsAtCarryingValue",), "USD", PromotionStrategy.DIRECT_INSTANT
    )
    result = MultiPeriodFinancialPromoter().promote((_instant(),), policy=policy)
    assert result.value == 10 and result.filing.accession_number == "0000000000-25-000001"


def test_composite_instant_promotes_aapl_total_debt_with_each_source_lineage(
    aapl_companyfacts: dict[str, object],
) -> None:
    facts = extract_company_facts(aapl_companyfacts, source_identity="aapl-companyfacts")
    policy = MetricPromotionPolicy(
        "total_debt",
        ("LongTermDebtCurrent", "LongTermDebtNoncurrent"),
        "USD",
        PromotionStrategy.COMPOSITE_INSTANT,
        ("long-term-current", "long-term-noncurrent"),
    )

    result = MultiPeriodFinancialPromoter().promote(facts, policy=policy)

    assert result.value == 82_347_000_000
    assert result.period_end == date(2026, 6, 27)
    assert result.source_fact_ids == (
        "us-gaap:LongTermDebtCurrent:USD:89",
        "us-gaap:LongTermDebtNoncurrent:USD:89",
    )
    assert result.source_accessions == ("0000320193-26-000020", "0000320193-26-000020")


def test_derived_instant_promotes_aapl_operating_nwc_with_dependency_lineage(
    aapl_companyfacts: dict[str, object],
) -> None:
    facts = extract_company_facts(aapl_companyfacts, source_identity="aapl-companyfacts")
    operating_assets = MetricPromotionPolicy(
        "operating_current_assets",
        ("AccountsReceivableNetCurrent", "InventoryNet"),
        "USD",
        PromotionStrategy.COMPOSITE_INSTANT,
        ("trade-receivables", "inventory"),
    )
    operating_liabilities = MetricPromotionPolicy(
        "operating_current_liabilities",
        ("AccountsPayableCurrent",),
        "USD",
        PromotionStrategy.DIRECT_INSTANT,
    )
    policy = MetricPromotionPolicy(
        "net_working_capital",
        (),
        "USD",
        PromotionStrategy.DERIVED_INSTANT,
        dependencies=(operating_assets, operating_liabilities),
        derivation="net_working_capital",
    )

    result = MultiPeriodFinancialPromoter().promote(facts, policy=policy)

    assert result.value == -22_035_000_000
    assert result.period_end == date(2026, 6, 27)
    assert result.source_fact_ids == (
        "us-gaap:AccountsReceivableNetCurrent:USD:143",
        "us-gaap:InventoryNet:USD:143",
        "us-gaap:AccountsPayableCurrent:USD:141",
    )
    assert result.source_accessions == ("0000320193-26-000020",) * 3


def test_instant_context_pair_selects_one_compatible_opening_and_closing_fact() -> None:
    opening = _canonical_instant("opening", date(2025, 6, 28))
    closing = _canonical_instant("closing", date(2026, 6, 27))

    result = financial_promotion.select_instant_context_pair(
        (opening, closing),
        metric_id="net_working_capital",
        unit="USD",
        opening_end=opening.period_end,
        closing_end=closing.period_end,
    )

    assert result.opening.source_fact_ids == ("opening",)
    assert result.closing.source_fact_ids == ("closing",)


@pytest.mark.parametrize(
    "facts, opening_end, closing_end",
    (
        ((_canonical_instant("closing", date(2026, 6, 27)),), date(2025, 6, 28), date(2026, 6, 27)),
        ((_canonical_instant("opening", date(2025, 6, 28)),), date(2025, 6, 28), date(2026, 6, 27)),
        (
            (
                _canonical_instant("opening", date(2026, 6, 27)),
                _canonical_instant("closing", date(2025, 6, 28)),
            ),
            date(2026, 6, 27),
            date(2025, 6, 28),
        ),
        (
            (
                _canonical_instant("opening", date(2026, 6, 27)),
                _canonical_instant("closing", date(2026, 6, 27)),
            ),
            date(2026, 6, 27),
            date(2026, 6, 27),
        ),
    ),
)
def test_instant_context_pair_rejects_missing_or_nonascending_endpoints(
    facts: tuple[FinancialFact, ...], opening_end: date, closing_end: date
) -> None:
    with pytest.raises(FinancialPromotionError):
        financial_promotion.select_instant_context_pair(
            facts,
            metric_id="net_working_capital",
            unit="USD",
            opening_end=opening_end,
            closing_end=closing_end,
        )


@pytest.mark.parametrize("endpoint", ("opening", "closing"))
def test_instant_context_pair_rejects_ambiguous_endpoint(endpoint: str) -> None:
    opening = _canonical_instant("opening", date(2025, 6, 28))
    closing = _canonical_instant("closing", date(2026, 6, 27))
    duplicate = replace(opening if endpoint == "opening" else closing, id="duplicate")

    with pytest.raises(FinancialPromotionError):
        financial_promotion.select_instant_context_pair(
            (opening, closing, duplicate),
            metric_id="net_working_capital",
            unit="USD",
            opening_end=opening.period_end,
            closing_end=closing.period_end,
        )


@pytest.mark.parametrize(
    "closing",
    (
        _canonical_instant("closing", date(2026, 6, 27), unit="EUR"),
        _canonical_instant("closing", date(2026, 6, 27), method="sum of other components"),
    ),
)
def test_instant_context_pair_rejects_incompatible_unit_or_semantic_basis(
    closing: FinancialFact,
) -> None:
    opening = _canonical_instant("opening", date(2025, 6, 28))

    with pytest.raises(FinancialPromotionError):
        financial_promotion.select_instant_context_pair(
            (opening, closing),
            metric_id="net_working_capital",
            unit="USD",
            opening_end=opening.period_end,
            closing_end=closing.period_end,
        )


def _aapl_nwc_policy(end: date) -> MetricPromotionPolicy:
    operating_assets = MetricPromotionPolicy(
        "operating_current_assets",
        ("AccountsReceivableNetCurrent", "InventoryNet"),
        "USD",
        PromotionStrategy.COMPOSITE_INSTANT,
        ("trade-receivables", "inventory"),
        target_end=end,
    )
    operating_liabilities = MetricPromotionPolicy(
        "operating_current_liabilities",
        ("AccountsPayableCurrent",),
        "USD",
        PromotionStrategy.DIRECT_INSTANT,
        target_end=end,
    )
    return MetricPromotionPolicy(
        "net_working_capital",
        (),
        "USD",
        PromotionStrategy.DERIVED_INSTANT,
        dependencies=(operating_assets, operating_liabilities),
        derivation="net_working_capital",
        target_end=end,
    )


def _aapl_debt_policy(end: date) -> MetricPromotionPolicy:
    return MetricPromotionPolicy(
        "total_debt",
        ("LongTermDebtCurrent", "LongTermDebtNoncurrent"),
        "USD",
        PromotionStrategy.COMPOSITE_INSTANT,
        ("long-term-current", "long-term-noncurrent"),
        target_end=end,
    )


def test_instant_context_pair_promotes_real_aapl_nwc_and_debt_endpoints(
    aapl_companyfacts: dict[str, object],
) -> None:
    facts = extract_company_facts(aapl_companyfacts, source_identity="aapl-companyfacts")
    opening_end, closing_end = date(2025, 9, 27), date(2026, 6, 27)
    promoter = MultiPeriodFinancialPromoter()

    nwc = financial_promotion.select_instant_context_pair(
        (
            promoter.promote(facts, policy=_aapl_nwc_policy(opening_end)),
            promoter.promote(facts, policy=_aapl_nwc_policy(closing_end)),
        ),
        metric_id="net_working_capital",
        unit="USD",
        opening_end=opening_end,
        closing_end=closing_end,
    )
    debt = financial_promotion.select_instant_context_pair(
        (
            promoter.promote(facts, policy=_aapl_debt_policy(opening_end)),
            promoter.promote(facts, policy=_aapl_debt_policy(closing_end)),
        ),
        metric_id="total_debt",
        unit="USD",
        opening_end=opening_end,
        closing_end=closing_end,
    )

    assert (nwc.opening.value, nwc.closing.value) == (-24_365_000_000, -22_035_000_000)
    assert (debt.opening.value, debt.closing.value) == (90_678_000_000, 82_347_000_000)
    assert nwc.opening.source_accessions == ("0000320193-26-000020",) * 3
    assert debt.closing.source_accessions == ("0000320193-26-000020",) * 2


def test_accounting_evidence_policy_registry_covers_each_sec_derived_field_once() -> None:
    policies = financial_promotion.accounting_evidence_policies()
    expected_fields = {
        item.name for item in fields(AccountingEvidenceSpec)
    } - financial_promotion.ACCOUNTING_EVIDENCE_EXTERNAL_FIELDS

    coverage = financial_promotion.validate_accounting_evidence_policy_coverage(policies)

    assert set(coverage) == expected_fields
    assert len({policy.metric_id for policy in policies}) == len(policies)
    assert all(isinstance(policy.strategy, PromotionStrategy) for policy in policies)


def test_accounting_evidence_policy_registry_rejects_duplicate_or_unknown_dependencies() -> None:
    policies = financial_promotion.accounting_evidence_policies()

    duplicate = replace(
        policies[-1],
        metric_id=policies[0].metric_id,
    )
    with pytest.raises(
        FinancialPromotionError,
        match="duplicate accounting evidence policy",
    ):
        financial_promotion.validate_accounting_evidence_policy_coverage(
            policies[:-1] + (duplicate,)
        )

    unknown_dependency = MetricPromotionPolicy(
        "auxiliary_nwc",
        (),
        "USD",
        PromotionStrategy.DERIVED_INSTANT,
        dependencies=(
            MetricPromotionPolicy(
                "missing",
                ("MissingConcept",),
                "USD",
                PromotionStrategy.DIRECT_INSTANT,
            ),
        ),
        derivation="net_working_capital",
    )

    with pytest.raises(
        FinancialPromotionError,
        match="policy dependency has no declared canonical metric",
    ):
        financial_promotion.validate_accounting_evidence_policy_coverage(
            policies + (unknown_dependency,)
        )


def test_accounting_evidence_policy_registry_promotes_aapl_nwc_components_at_both_endpoints(
    aapl_companyfacts: dict[str, object],
) -> None:
    facts = extract_company_facts(
        aapl_companyfacts,
        source_identity="aapl-companyfacts",
    )

    opening_end = date(2025, 9, 27)
    closing_end = date(2026, 6, 27)

    policies = financial_promotion.accounting_evidence_policies(
        opening_end=opening_end,
        closing_end=closing_end,
    )
    by_metric = {policy.metric_id: policy for policy in policies}
    promoter = MultiPeriodFinancialPromoter()

    opening_assets = promoter.promote(
        facts,
        policy=by_metric["operating_current_assets_opening"],
    )
    opening_liabilities = promoter.promote(
        facts,
        policy=by_metric["operating_current_liabilities_opening"],
    )
    closing_assets = promoter.promote(
        facts,
        policy=by_metric["operating_current_assets_closing"],
    )
    closing_liabilities = promoter.promote(
        facts,
        policy=by_metric["operating_current_liabilities_closing"],
    )

    assert opening_assets.period_end == opening_end
    assert opening_liabilities.period_end == opening_end
    assert closing_assets.period_end == closing_end
    assert closing_liabilities.period_end == closing_end


def test_capital_cost_interest_policy_is_separate_from_accounting_registry() -> None:
    (policy,) = financial_promotion.capital_cost_evidence_policies()

    assert policy.metric_id == "interest_expense"
    assert policy.concepts == ("InterestExpense",)
    assert policy.unit == "USD"
    assert policy.strategy is PromotionStrategy.TTM_DURATION
    assert all(
        item.metric_id != "interest_expense"
        for item in financial_promotion.accounting_evidence_policies()
    )


def test_capital_cost_interest_policy_promotes_ttm_interest_expense() -> None:
    (policy,) = financial_promotion.capital_cost_evidence_policies()
    facts = tuple(
        replace(item, concept="InterestExpense")
        for item in (
            _fact(100, date(2022, 1, 1), date(2022, 12, 31), "FY"),
            _fact(70, date(2022, 1, 1), date(2022, 9, 30), "Q3"),
            _fact(90, date(2023, 1, 1), date(2023, 9, 30), "Q3"),
        )
    )

    result = MultiPeriodFinancialPromoter().promote(facts, policy=policy)

    assert result.value == 120


def test_ttm_duration_policy_rejects_result_that_misses_target_end() -> None:
    policy = MetricPromotionPolicy(
        "interest_expense",
        ("InterestExpense",),
        "USD",
        PromotionStrategy.TTM_DURATION,
        target_end=date(2023, 12, 31),
    )
    facts = tuple(
        replace(item, concept="InterestExpense")
        for item in (
            _fact(100, date(2022, 1, 1), date(2022, 12, 31), "FY"),
            _fact(70, date(2022, 1, 1), date(2022, 9, 30), "Q3"),
            _fact(90, date(2023, 1, 1), date(2023, 9, 30), "Q3"),
        )
    )

    with pytest.raises(FinancialPromotionError, match="duration target end mismatch"):
        MultiPeriodFinancialPromoter().promote(facts, policy=policy)


def test_promoter_prefers_newer_full_fiscal_year_over_older_reconstructed_ttm() -> None:
    facts = (
        _fact(100, date(2024, 7, 1), date(2025, 6, 30), "FY"),
        _fact(70, date(2024, 7, 1), date(2025, 3, 31), "Q3"),
        _fact(90, date(2025, 7, 1), date(2026, 3, 31), "Q3"),
        _fact(130, date(2025, 7, 1), date(2026, 6, 30), "FY"),
    )

    result = MultiPeriodFinancialPromoter().promote_ttm(
        facts,
        concept="OperatingIncomeLoss",
    )

    assert result.value == 130
    assert result.period_start == date(2025, 7, 1)
    assert result.period_end == date(2026, 6, 30)


def test_composite_duration_sums_complete_components_at_same_latest_endpoint() -> None:
    depreciation = (
        replace(
            _fact(100, date(2024, 7, 1), date(2025, 6, 30), "FY"),
            concept="Depreciation",
            fact_id="dep-fy25",
        ),
        replace(
            _fact(70, date(2024, 7, 1), date(2025, 3, 31), "Q3"),
            concept="Depreciation",
            fact_id="dep-q3-prior",
        ),
        replace(
            _fact(90, date(2025, 7, 1), date(2026, 3, 31), "Q3"),
            concept="Depreciation",
            fact_id="dep-q3-current",
        ),
        replace(
            _fact(130, date(2025, 7, 1), date(2026, 6, 30), "FY"),
            concept="Depreciation",
            fact_id="dep-fy26",
        ),
    )

    amortization = (
        replace(
            _fact(20, date(2024, 7, 1), date(2025, 6, 30), "FY"),
            concept="AmortizationOfIntangibleAssets",
            fact_id="amort-fy25",
        ),
        replace(
            _fact(15, date(2024, 7, 1), date(2025, 3, 31), "Q3"),
            concept="AmortizationOfIntangibleAssets",
            fact_id="amort-q3-prior",
        ),
        replace(
            _fact(18, date(2025, 7, 1), date(2026, 3, 31), "Q3"),
            concept="AmortizationOfIntangibleAssets",
            fact_id="amort-q3-current",
        ),
        replace(
            _fact(25, date(2025, 7, 1), date(2026, 6, 30), "FY"),
            concept="AmortizationOfIntangibleAssets",
            fact_id="amort-fy26",
        ),
    )

    policy = MetricPromotionPolicy(
        "depreciation_amortization",
        ("Depreciation", "AmortizationOfIntangibleAssets"),
        "USD",
        PromotionStrategy("COMPOSITE_DURATION"),
        component_coverages=("depreciation", "intangible_amortization"),
    )

    result = MultiPeriodFinancialPromoter().promote(
        depreciation + amortization,
        policy=policy,
    )

    assert result.value == 155
    assert result.period_start == date(2025, 7, 1)
    assert result.period_end == date(2026, 6, 30)
    assert set(result.inputs) == {"dep-fy26", "amort-fy26"}


def test_composite_duration_rejects_components_with_different_endpoints() -> None:
    depreciation = (
        replace(
            _fact(100, date(2024, 7, 1), date(2025, 6, 30), "FY"),
            concept="Depreciation",
            fact_id="dep-fy25",
        ),
        replace(
            _fact(70, date(2024, 7, 1), date(2025, 3, 31), "Q3"),
            concept="Depreciation",
            fact_id="dep-q3-prior",
        ),
        replace(
            _fact(90, date(2025, 7, 1), date(2026, 3, 31), "Q3"),
            concept="Depreciation",
            fact_id="dep-q3-current",
        ),
        replace(
            _fact(130, date(2025, 7, 1), date(2026, 6, 30), "FY"),
            concept="Depreciation",
            fact_id="dep-fy26",
        ),
    )

    amortization = (
        replace(
            _fact(20, date(2024, 7, 1), date(2025, 6, 30), "FY"),
            concept="AmortizationOfIntangibleAssets",
            fact_id="amort-fy25",
        ),
        replace(
            _fact(15, date(2024, 7, 1), date(2025, 3, 31), "Q3"),
            concept="AmortizationOfIntangibleAssets",
            fact_id="amort-q3-prior",
        ),
        replace(
            _fact(18, date(2025, 7, 1), date(2026, 3, 31), "Q3"),
            concept="AmortizationOfIntangibleAssets",
            fact_id="amort-q3-current",
        ),
    )

    policy = MetricPromotionPolicy(
        "depreciation_amortization",
        ("Depreciation", "AmortizationOfIntangibleAssets"),
        "USD",
        PromotionStrategy.COMPOSITE_DURATION,
        component_coverages=("depreciation", "intangible_amortization"),
    )

    with pytest.raises(
        FinancialPromotionError,
        match="incompatible composite duration periods",
    ):
        MultiPeriodFinancialPromoter().promote(
            depreciation + amortization,
            policy=policy,
        )


def test_accounting_registry_declares_ordered_alternatives_for_depreciation_amortization() -> None:
    policy = next(
        item
        for item in accounting_evidence_policies()
        if item.metric_id == "depreciation_amortization"
    )

    assert policy.strategy is PromotionStrategy.ALTERNATIVE
    assert len(policy.alternatives) == 2

    aggregate, composite = policy.alternatives

    assert aggregate.metric_id == "depreciation_amortization"
    assert aggregate.strategy is PromotionStrategy.TTM_DURATION
    assert aggregate.concepts == ("DepreciationDepletionAndAmortization",)

    assert composite.metric_id == "depreciation_amortization"
    assert composite.strategy is PromotionStrategy.COMPOSITE_DURATION
    assert composite.concepts == (
        "Depreciation",
        "AmortizationOfIntangibleAssets",
    )
    assert composite.component_coverages == (
        "depreciation",
        "intangible_amortization",
    )


def test_promoter_accepts_latest_full_fiscal_year_without_ytd_pair() -> None:
    facts = (
        _fact(100, date(2024, 7, 1), date(2025, 6, 30), "FY"),
        _fact(130, date(2025, 7, 1), date(2026, 6, 30), "FY"),
    )

    result = MultiPeriodFinancialPromoter().promote_ttm(
        facts,
        concept="OperatingIncomeLoss",
    )

    assert result.value == 130
    assert result.period_start == date(2025, 7, 1)
    assert result.period_end == date(2026, 6, 30)


def test_accounting_registry_distinguishes_ttm_opening_and_closing_instant_endpoints() -> None:
    opening_end = date(2025, 6, 30)
    closing_end = date(2026, 6, 30)

    policies = accounting_evidence_policies(
        opening_end=opening_end,
        closing_end=closing_end,
    )
    by_metric = {policy.metric_id: policy for policy in policies}

    assert by_metric["operating_current_assets_opening"].target_end == opening_end
    assert by_metric["operating_current_liabilities_opening"].target_end == opening_end
    assert by_metric["net_operating_assets_opening"].target_end == opening_end

    assert by_metric["operating_current_assets_closing"].target_end == closing_end
    assert by_metric["operating_current_liabilities_closing"].target_end == closing_end
    assert by_metric["net_operating_assets_closing"].target_end == closing_end

    assert by_metric["cash"].target_end == closing_end
    assert by_metric["marketable_securities"].target_end == closing_end
    assert by_metric["total_debt"].target_end == closing_end

    assert by_metric["valuation_shares"].target_end is None


def test_alternative_policy_falls_back_to_next_authorized_representation() -> None:
    depreciation = replace(
        _fact(130, date(2025, 7, 1), date(2026, 6, 30), "FY"),
        concept="Depreciation",
        fact_id="dep-fy26",
    )
    amortization = replace(
        _fact(25, date(2025, 7, 1), date(2026, 6, 30), "FY"),
        concept="AmortizationOfIntangibleAssets",
        fact_id="amort-fy26",
    )

    aggregate = MetricPromotionPolicy(
        "depreciation_amortization",
        ("DepreciationDepletionAndAmortization",),
        "USD",
        PromotionStrategy.TTM_DURATION,
    )
    composite = MetricPromotionPolicy(
        "depreciation_amortization",
        ("Depreciation", "AmortizationOfIntangibleAssets"),
        "USD",
        PromotionStrategy.COMPOSITE_DURATION,
        ("depreciation", "intangible_amortization"),
    )
    policy = MetricPromotionPolicy(
        "depreciation_amortization",
        (),
        "USD",
        PromotionStrategy("ALTERNATIVE"),
        alternatives=(aggregate, composite),
    )

    result = MultiPeriodFinancialPromoter().promote(
        (depreciation, amortization),
        policy=policy,
    )

    assert result.value == 155
    assert result.period_start == date(2025, 7, 1)
    assert result.period_end == date(2026, 6, 30)
    assert set(result.inputs) == {"dep-fy26", "amort-fy26"}
