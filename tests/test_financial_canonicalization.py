from __future__ import annotations

from dataclasses import replace
from datetime import date

from qhapaq_finance.financial_canonicalization import (
    CanonicalPeriodContext,
    ExtensionMapping,
    FactContext,
    FinancialCanonicalizer,
    MetricSpec,
    PeriodKind,
    ProfileKind,
    RawFact,
    ResolutionMethod,
    ResolutionStatus,
    SemanticEvidence,
    XbrlCalculationArc,
    XbrlConcept,
    XbrlPresentationArc,
    XbrlRelationshipSet,
    classify_issuer,
    derive_q4,
)


def _fact(**changes: object) -> RawFact:
    base = RawFact(
        "revenue-1",
        "us-gaap",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        100.0,
        "USD",
        PeriodKind.DURATION,
        date(2025, 1, 1),
        date(2025, 12, 31),
        2025,
        "FY",
        "10-K",
        "0000000000-25-000001",
        date(2026, 2, 1),
        "fixture:standard",
    )
    return replace(base, **changes)


SPEC = MetricSpec(
    "revenue",
    "us-gaap",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    ("SalesRevenueNet", "Revenues"),
    "USD",
    PeriodKind.DURATION,
)
CONTEXT = FactContext(date(2025, 12, 31), fiscal_year=2025, fiscal_period="FY")


def _canonical_period(
    *, start: date = date(2025, 1, 1), end: date = date(2025, 12, 31)
) -> CanonicalPeriodContext:
    return CanonicalPeriodContext(
        "0000000000-25-000001",
        "10-K",
        date(2026, 2, 1),
        end,
        2025,
        start,
        end,
        end,
    )


def _period_context(period: CanonicalPeriodContext) -> FactContext:
    return FactContext(
        period.report_date,
        fiscal_year=period.fiscal_year,
        fiscal_period="FY",
        canonical_period=period,
    )


def test_standard_fact_preserves_exact_method_and_provenance() -> None:
    metric = FinancialCanonicalizer().resolve(classify_issuer(sic=3570), CONTEXT, SPEC, (_fact(),))
    assert metric.normalized_value == 100
    assert metric.decision.status is ResolutionStatus.RESOLVED
    assert metric.decision.method is ResolutionMethod.STANDARD_CONCEPT
    assert metric.raw_fact is not None and metric.raw_fact.accession == "0000000000-25-000001"
    assert metric.decision.candidates[0].reasons == ()


def test_extension_requires_explicit_semantic_mapping_and_segment_is_rejected() -> None:
    extension = _fact(taxonomy="acme", concept="RevenueExtension", label="Revenue")
    without = FinancialCanonicalizer().resolve(
        classify_issuer(sic=3570), CONTEXT, SPEC, (extension,)
    )
    assert without.decision.status is ResolutionStatus.MISSING
    context = FactContext(
        CONTEXT.target_end,
        fiscal_year=2025,
        fiscal_period="FY",
        extension_mappings={
            ("acme", "RevenueExtension"): ExtensionMapping(
                "revenue", "calculation-child", ("presentation",)
            )
        },
    )
    resolved = FinancialCanonicalizer().resolve(
        classify_issuer(sic=3570), context, SPEC, (extension,)
    )
    assert resolved.decision.method is ResolutionMethod.ISSUER_EXTENSION
    segment = replace(extension, fact_id="segment", dimensions=("ProductAxis",))
    rejected = FinancialCanonicalizer().resolve(
        classify_issuer(sic=3570), context, SPEC, (segment,)
    )
    assert rejected.decision.status is ResolutionStatus.MISSING
    assert rejected.decision.candidates[0].reasons == ("non-consolidated or dimensional fact",)


def test_amendment_wins_over_original_but_equal_rank_conflict_fails_closed() -> None:
    original = _fact(value=100)
    amended = replace(
        original,
        fact_id="amended",
        value=101,
        filing_form="10-K/A",
        amendment=True,
        filing_date=date(2026, 3, 1),
    )
    metric = FinancialCanonicalizer().resolve(
        classify_issuer(sic=3570), CONTEXT, SPEC, (original, amended)
    )
    assert metric.normalized_value == 101
    conflict = replace(amended, fact_id="restated", value=102, restatement=True)
    second = replace(conflict, fact_id="restated-two", value=103)
    bad = FinancialCanonicalizer().resolve(
        classify_issuer(sic=3570), CONTEXT, SPEC, (conflict, second)
    )
    assert bad.decision.status is ResolutionStatus.CONFLICT


def test_irregular_53_week_period_is_accepted_by_actual_dates_and_q4_requires_compatibility() -> (
    None
):
    annual = _fact(end=date(2026, 1, 3), value=130, fiscal_year=2025)
    ytd = replace(annual, fact_id="ytd", end=date(2025, 10, 4), value=90, fiscal_period="9M")
    q4 = derive_q4(
        annual=annual_metric(annual), prior_ytd=annual_metric(ytd), current_ytd=annual_metric(ytd)
    )
    assert q4.normalized_value == 40
    incompatible = derive_q4(
        annual_metric(annual), annual_metric(replace(ytd, unit="EUR")), annual_metric(ytd)
    )
    assert incompatible.decision.status is ResolutionStatus.MISSING


def annual_metric(fact: RawFact):
    return FinancialCanonicalizer().resolve(
        classify_issuer(sic=3570),
        FactContext(fact.end, fiscal_year=fact.fiscal_year, fiscal_period=fact.fiscal_period),
        SPEC,
        (fact,),
    )


def test_missing_ifrs_and_bank_profiles_are_explicitly_unresolved_or_not_applicable() -> None:
    engine = FinancialCanonicalizer()
    assert (
        engine.resolve(classify_issuer(sic=3570), CONTEXT, SPEC, ()).decision.status
        is ResolutionStatus.MISSING
    )
    ifrs = _fact(taxonomy="ifrs-full", concept="Revenue")
    assert (
        engine.resolve(classify_issuer(sic=3570), CONTEXT, SPEC, (ifrs,)).decision.status
        is ResolutionStatus.MISSING
    )
    bank = engine.resolve(classify_issuer(sic=6021), CONTEXT, SPEC, (_fact(),))
    assert bank.decision.status is ResolutionStatus.NOT_APPLICABLE
    assert classify_issuer(foreign_private_issuer=True).kind is ProfileKind.FOREIGN_PRIVATE_ISSUER


def _semantic(
    *, period: PeriodKind = PeriodKind.DURATION, calculation: bool = True
) -> SemanticEvidence:
    relationships = XbrlRelationshipSet(
        (
            XbrlPresentationArc(
                "us-gaap:IncomeStatement", "acme:CustomRevenue", "statement", 1.0, None
            ),
        ),
        (XbrlCalculationArc("us-gaap:Revenue", "acme:CustomRevenue", 1.0, "statement", True),)
        if calculation
        else (),
    )
    return SemanticEvidence(
        XbrlConcept("acme:CustomRevenue", "http://acme.example", "monetary", period, None, None),
        (),
        relationships,
        "revenue",
        "fixture-sha",
    )


def test_extension_requires_structural_evidence_and_preserves_provenance() -> None:
    extension = _fact(taxonomy="acme", concept="CustomRevenue", value=101)
    context = FactContext(
        CONTEXT.target_end,
        fiscal_year=2025,
        fiscal_period="FY",
        semantic_extensions={("acme", "CustomRevenue"): _semantic()},
    )
    metric = FinancialCanonicalizer().resolve(
        classify_issuer(sic=3570), context, SPEC, (extension,)
    )
    assert metric.normalized_value == 101
    assert metric.decision.method is ResolutionMethod.EXTENSION_STRUCTURAL
    assert metric.raw_fact is not None and metric.raw_fact.accession == "0000000000-25-000001"
    assert metric.decision.candidates[0].semantic_evidence == ()


def test_extension_rejects_presentation_only_wrong_period_dimensions_and_conflicts() -> None:
    extension = _fact(taxonomy="acme", concept="CustomRevenue")
    engine = FinancialCanonicalizer()
    for evidence in (_semantic(calculation=False), _semantic(period=PeriodKind.INSTANT)):
        context = FactContext(
            CONTEXT.target_end,
            fiscal_year=2025,
            fiscal_period="FY",
            semantic_extensions={("acme", "CustomRevenue"): evidence},
        )
        assert (
            engine.resolve(classify_issuer(sic=3570), context, SPEC, (extension,)).decision.status
            is ResolutionStatus.MISSING
        )
    dimensional = replace(extension, dimensions=("ProductAxis",))
    context = FactContext(
        CONTEXT.target_end,
        fiscal_year=2025,
        fiscal_period="FY",
        semantic_extensions={("acme", "CustomRevenue"): _semantic()},
    )
    assert (
        engine.resolve(classify_issuer(sic=3570), context, SPEC, (dimensional,)).decision.status
        is ResolutionStatus.MISSING
    )
    standard = _fact(value=100)
    conflicting = replace(extension, value=101)
    assert (
        engine.resolve(
            classify_issuer(sic=3570), context, SPEC, (standard, conflicting)
        ).decision.status
        is ResolutionStatus.CONFLICT
    )


def test_selected_annual_period_rejects_prior_fy_and_nine_month_ytd() -> None:
    period = _canonical_period()
    target = _fact()
    prior = replace(
        target,
        fact_id="prior",
        start=date(2024, 1, 1),
        end=date(2024, 12, 31),
        fiscal_year=2024,
        value=90,
    )
    ytd = replace(
        target,
        fact_id="ytd",
        start=date(2025, 1, 1),
        end=date(2025, 9, 30),
        fiscal_period="9M",
        value=75,
    )
    result = FinancialCanonicalizer().resolve(
        classify_issuer(sic=3570), _period_context(period), SPEC, (target, prior, ytd)
    )
    assert result.decision.status is ResolutionStatus.RESOLVED
    assert result.normalized_value == 100
    assert "accession mismatch" not in result.decision.candidates[1].reasons
    assert "canonical fiscal year mismatch" in result.decision.candidates[1].reasons
    assert "not fiscal-year duration" in result.decision.candidates[2].reasons


def test_selected_53_week_duration_uses_actual_start_and_end_dates() -> None:
    period = _canonical_period(start=date(2025, 1, 27), end=date(2026, 1, 25))
    annual = _fact(start=period.duration_start, end=period.duration_end, fiscal_year=2025)
    nine_months = replace(annual, fact_id="9m", end=date(2025, 10, 26), fiscal_period="9M")
    result = FinancialCanonicalizer().resolve(
        classify_issuer(sic=3570), _period_context(period), SPEC, (annual, nine_months)
    )
    assert result.decision.status is ResolutionStatus.RESOLVED
    assert result.raw_fact is annual


def test_selected_instant_rejects_comparative_prior_year_instant() -> None:
    period = _canonical_period()
    instant_spec = MetricSpec("total_assets", "us-gaap", "Assets", (), "USD", PeriodKind.INSTANT)
    target = _fact(
        concept="Assets", period_kind=PeriodKind.INSTANT, start=None, end=period.instant_date
    )
    comparative = replace(target, fact_id="comparative", end=date(2024, 12, 31), value=99)
    result = FinancialCanonicalizer().resolve(
        classify_issuer(sic=3570), _period_context(period), instant_spec, (target, comparative)
    )
    assert result.decision.status is ResolutionStatus.RESOLVED
    assert result.raw_fact is target
    assert "instant date mismatch" in result.decision.candidates[1].reasons


def test_same_period_identical_companyfacts_and_inline_xbrl_are_corroborating() -> None:
    period = _canonical_period()
    companyfacts = _fact(source_identity="companyfacts-sha")
    inline_xbrl = replace(companyfacts, fact_id="inline-xbrl", source_identity="filing-sha")
    result = FinancialCanonicalizer().resolve(
        classify_issuer(sic=3570), _period_context(period), SPEC, (companyfacts, inline_xbrl)
    )
    assert result.decision.status is ResolutionStatus.RESOLVED
    assert result.normalized_value == 100
    assert len([item for item in result.decision.candidates if item.accepted]) == 2


def test_same_period_different_values_remain_a_genuine_conflict() -> None:
    period = _canonical_period()
    first = _fact()
    second = replace(first, fact_id="different", value=101, source_identity="filing-sha")
    result = FinancialCanonicalizer().resolve(
        classify_issuer(sic=3570), _period_context(period), SPEC, (first, second)
    )
    assert result.decision.status is ResolutionStatus.CONFLICT


def test_selected_accession_cannot_override_incompatible_period() -> None:
    period = _canonical_period()
    valid = _fact()
    incompatible = replace(
        valid, fact_id="same-accession-prior-period", end=date(2024, 12, 31), value=99
    )
    result = FinancialCanonicalizer().resolve(
        classify_issuer(sic=3570), _period_context(period), SPEC, (valid, incompatible)
    )
    assert result.decision.status is ResolutionStatus.RESOLVED
    assert "duration end date mismatch" in result.decision.candidates[1].reasons


def test_generic_us_gaap_revenues_alias_requires_valid_annual_entity_context() -> None:
    """US-GAAP Revenues is a generic total-revenue alias, never a ticker rule."""
    period = _canonical_period()
    revenues = _fact(concept="Revenues")
    context = _period_context(period)
    resolver = FinancialCanonicalizer()

    resolved = resolver.resolve(classify_issuer(sic=3570), context, SPEC, (revenues,))
    assert resolved.decision.status is ResolutionStatus.RESOLVED
    assert resolved.decision.method is ResolutionMethod.STANDARD_ALIAS

    wrong_period = replace(revenues, fact_id="quarter", end=date(2025, 9, 30), fiscal_period="Q3")
    dimensional = replace(revenues, fact_id="segment", dimensions=("ProductAxis",))
    assert (
        resolver.resolve(classify_issuer(sic=3570), context, SPEC, (wrong_period,)).decision.status
        is ResolutionStatus.MISSING
    )
    assert (
        resolver.resolve(classify_issuer(sic=3570), context, SPEC, (dimensional,)).decision.status
        is ResolutionStatus.MISSING
    )

    conflicting_standard = replace(revenues, fact_id="other-revenues", value=101)
    assert (
        resolver.resolve(
            classify_issuer(sic=3570), context, SPEC, (revenues, conflicting_standard)
        ).decision.status
        is ResolutionStatus.CONFLICT
    )
