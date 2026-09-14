"""Fail-closed, auditable resolution of raw filing facts into financial metrics.

This module is deliberately independent of acquisition, frozen evidence, and
valuation.  Callers must promote only decisions they have separately approved.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import Enum


class ProfileKind(str, Enum):
    OPERATING_COMPANY = "OPERATING_COMPANY"
    BANK = "BANK"
    INSURER = "INSURER"
    REIT = "REIT"
    UTILITY = "UTILITY"
    FOREIGN_PRIVATE_ISSUER = "FOREIGN_PRIVATE_ISSUER"
    INVESTMENT_COMPANY = "INVESTMENT_COMPANY"
    UNSUPPORTED = "UNSUPPORTED"
    FINANCIAL_INSTITUTION = "FINANCIAL_INSTITUTION"
    OTHER = "OTHER"


class ResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    MISSING = "MISSING"
    AMBIGUOUS = "AMBIGUOUS"
    CONFLICT = "CONFLICT"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INVALID = "INVALID"


class ResolutionMethod(str, Enum):
    STANDARD_CONCEPT = "STANDARD_CONCEPT"
    STANDARD_ALIAS = "STANDARD_ALIAS"
    TAXONOMY_RELATIONSHIP = "TAXONOMY_RELATIONSHIP"
    ISSUER_EXTENSION = "ISSUER_EXTENSION"
    DERIVED = "DERIVED"
    UNRESOLVED = "UNRESOLVED"
    EXTENSION_STRUCTURAL = "EXTENSION_STRUCTURAL"


class PeriodKind(str, Enum):
    INSTANT = "INSTANT"
    DURATION = "DURATION"


@dataclass(frozen=True)
class IssuerProfile:
    kind: ProfileKind
    reason: str


def classify_issuer(
    *,
    sic: int | None = None,
    foreign_private_issuer: bool = False,
    investment_company: bool = False,
    is_reit: bool = False,
) -> IssuerProfile:
    """Use only explicit filing classifications; unknowns remain unsupported."""
    if foreign_private_issuer:
        return IssuerProfile(ProfileKind.FOREIGN_PRIVATE_ISSUER, "foreign private issuer flag")
    if investment_company:
        return IssuerProfile(ProfileKind.INVESTMENT_COMPANY, "investment company flag")
    if is_reit:
        return IssuerProfile(ProfileKind.REIT, "REIT classification flag")
    if sic is None:
        return IssuerProfile(ProfileKind.UNSUPPORTED, "no issuer classification")
    if 6000 <= sic <= 6199:
        return IssuerProfile(ProfileKind.BANK, f"SIC {sic}")
    if 6300 <= sic <= 6499:
        return IssuerProfile(ProfileKind.INSURER, f"SIC {sic}")
    if 4900 <= sic <= 4999:
        return IssuerProfile(ProfileKind.UTILITY, f"SIC {sic}")
    return IssuerProfile(ProfileKind.OPERATING_COMPANY, f"SIC {sic}")


@dataclass(frozen=True)
class RawFact:
    """Untouched filing fact plus context and source identity."""

    fact_id: str
    taxonomy: str
    concept: str
    value: float
    unit: str
    period_kind: PeriodKind
    start: date | None
    end: date
    fiscal_year: int
    fiscal_period: str
    filing_form: str
    accession: str
    filing_date: date
    source_identity: str
    dimensions: tuple[str, ...] = ()
    consolidated: bool = True
    amendment: bool = False
    restatement: bool = False
    label: str | None = None
    data_type: str | None = None
    balance: str | None = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.value) or not self.unit.strip():
            raise ValueError("raw fact value and unit must be finite and present")
        if self.period_kind is PeriodKind.DURATION and self.start is None:
            raise ValueError("duration raw facts require a start date")
        if self.period_kind is PeriodKind.INSTANT and self.start is not None:
            raise ValueError("instant raw facts cannot have a start date")


@dataclass(frozen=True)
class ExtensionMapping:
    """Pre-validated taxonomy/presentation/calculation evidence for an extension."""

    target_metric: str
    relationship: str
    semantic_evidence: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return bool(self.relationship and self.semantic_evidence)


@dataclass(frozen=True)
class CanonicalPeriodContext:
    """The selected original filing period, never inferred from candidate recency."""

    target_accession: str
    target_form: str
    filing_date: date
    report_date: date
    fiscal_year: int
    duration_start: date | None
    duration_end: date
    instant_date: date


@dataclass(frozen=True)
class FactContext:
    target_end: date
    fiscal_year: int | None = None
    fiscal_period: str | None = None
    extension_mappings: Mapping[tuple[str, str], ExtensionMapping] | None = None
    semantic_extensions: Mapping[tuple[str, str], SemanticEvidence] | None = None
    canonical_period: CanonicalPeriodContext | None = None


@dataclass(frozen=True)
class XbrlConcept:
    qname: str
    namespace: str
    data_type: str | None
    period_type: PeriodKind
    balance: str | None
    substitution_group: str | None


@dataclass(frozen=True)
class XbrlLabel:
    role: str
    text: str


@dataclass(frozen=True)
class XbrlPresentationArc:
    parent: str
    child: str
    role: str
    order: float
    preferred_label: str | None


@dataclass(frozen=True)
class XbrlCalculationArc:
    parent: str
    child: str
    weight: float
    role: str
    period_compatible: bool


@dataclass(frozen=True)
class XbrlRelationshipSet:
    presentations: tuple[XbrlPresentationArc, ...]
    calculations: tuple[XbrlCalculationArc, ...]


@dataclass(frozen=True)
class SemanticEvidence:
    concept: XbrlConcept
    labels: tuple[XbrlLabel, ...]
    relationships: XbrlRelationshipSet
    target_metric: str
    source_artifact_checksum: str
    contradictory: tuple[str, ...] = ()

    def supports(self, spec: MetricSpec) -> tuple[bool, tuple[str, ...]]:
        reasons: list[str] = []
        if self.target_metric != spec.metric or self.concept.period_type is not spec.period_kind:
            reasons.append("metric or period type incompatible")
        presentation = any(
            arc.child == self.concept.qname for arc in self.relationships.presentations
        )
        calculation = any(
            arc.child == self.concept.qname and arc.period_compatible
            for arc in self.relationships.calculations
        )
        if not presentation:
            reasons.append("presentation evidence absent")
        if not calculation:
            reasons.append("calculation evidence absent")
        reasons.extend(self.contradictory)
        return not reasons, tuple(reasons)


SemanticCandidate = SemanticEvidence
SemanticResolution = SemanticEvidence


@dataclass(frozen=True)
class MetricSpec:
    metric: str
    standard_taxonomy: str
    standard_concept: str
    approved_aliases: tuple[str, ...]
    unit: str
    period_kind: PeriodKind
    applicable_profiles: tuple[ProfileKind] = (ProfileKind.OPERATING_COMPANY,)


@dataclass(frozen=True)
class FactCandidate:
    fact: RawFact
    method: ResolutionMethod | None
    accepted: bool
    reasons: tuple[str, ...]
    rank: tuple[int, int, int]
    semantic_evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolutionDecision:
    status: ResolutionStatus
    method: ResolutionMethod
    selected_fact_id: str | None
    candidates: tuple[FactCandidate, ...]
    validation_results: tuple[str, ...]


@dataclass(frozen=True)
class CanonicalMetric:
    spec: MetricSpec
    decision: ResolutionDecision
    raw_fact: RawFact | None
    normalized_value: float | None
    normalized_unit: str | None


@dataclass(frozen=True)
class CanonicalFinancials:
    profile: IssuerProfile
    metrics: Mapping[str, CanonicalMetric]
    reconciliation_results: tuple[str, ...]
    reconciliation_blocked: bool


class FinancialCanonicalizer:
    """Resolve explicit metric specs only; no labels or magnitudes authorize facts."""

    def resolve(
        self,
        profile: IssuerProfile,
        context: FactContext,
        spec: MetricSpec,
        facts: tuple[RawFact, ...],
    ) -> CanonicalMetric:
        if profile.kind not in spec.applicable_profiles:
            return CanonicalMetric(
                spec,
                ResolutionDecision(
                    ResolutionStatus.NOT_APPLICABLE,
                    ResolutionMethod.UNRESOLVED,
                    None,
                    (),
                    (profile.reason,),
                ),
                None,
                None,
                None,
            )
        candidates = tuple(self._candidate(fact, context, spec) for fact in facts)
        accepted = [item for item in candidates if item.accepted]
        if not accepted:
            return self._unresolved(
                spec, ResolutionStatus.MISSING, candidates, "no valid candidate"
            )
        accepted.sort(key=lambda item: item.rank, reverse=True)
        best_rank = accepted[0].rank
        best = [item for item in accepted if item.rank == best_rank]
        values = {item.fact.value for item in best}
        if len(values) != 1:
            return self._unresolved(
                spec, ResolutionStatus.CONFLICT, candidates, "top-ranked values conflict"
            )
        concepts = {(item.fact.taxonomy, item.fact.concept) for item in best}
        if len(concepts) != 1:
            return self._unresolved(
                spec, ResolutionStatus.AMBIGUOUS, candidates, "top-ranked concepts differ"
            )
        if any(
            item.method is ResolutionMethod.EXTENSION_STRUCTURAL and item.fact.value not in values
            for item in accepted
        ):
            return self._unresolved(
                spec,
                ResolutionStatus.CONFLICT,
                candidates,
                "standard and extension values conflict",
            )
        selected = max(best, key=lambda item: (item.fact.filing_date, item.fact.accession))
        assert selected.method is not None
        return CanonicalMetric(
            spec,
            ResolutionDecision(
                ResolutionStatus.RESOLVED,
                selected.method,
                selected.fact.fact_id,
                candidates,
                ("unit validated", "period validated", "consolidation validated"),
            ),
            selected.fact,
            selected.fact.value,
            spec.unit,
        )

    def financials(
        self,
        profile: IssuerProfile,
        context: FactContext,
        specs: tuple[MetricSpec, ...],
        facts: tuple[RawFact, ...],
    ) -> CanonicalFinancials:
        metrics = {spec.metric: self.resolve(profile, context, spec, facts) for spec in specs}
        reconciliations = self._reconcile(metrics)
        return CanonicalFinancials(
            profile,
            metrics,
            reconciliations,
            any(result.endswith("failed") for result in reconciliations),
        )

    def _candidate(self, fact: RawFact, context: FactContext, spec: MetricSpec) -> FactCandidate:
        reasons: list[str] = []
        method = self._method(fact, context, spec)
        if method is None:
            reasons.append("concept is not authorized by explicit taxonomy rules")
        if fact.unit != spec.unit:
            reasons.append("unit mismatch")
        if fact.period_kind is not spec.period_kind or fact.end != context.target_end:
            reasons.append("period kind or end date mismatch")
        if context.fiscal_year is not None and fact.fiscal_year != context.fiscal_year:
            reasons.append("fiscal year mismatch")
        if context.fiscal_period is not None and fact.fiscal_period != context.fiscal_period:
            reasons.append("fiscal period mismatch")
        if context.canonical_period is not None:
            reasons.extend(self._period_reasons(fact, context.canonical_period, spec))
        if not fact.consolidated or fact.dimensions:
            reasons.append("non-consolidated or dimensional fact")
        rank = (
            self._method_rank(method),
            int(fact.restatement) * 2 + int(fact.amendment),
            fact.filing_date.toordinal(),
        )
        semantic = (context.semantic_extensions or {}).get((fact.taxonomy, fact.concept))
        if semantic is not None:
            supported, semantic_reasons = semantic.supports(spec)
            if method is ResolutionMethod.EXTENSION_STRUCTURAL and not supported:
                reasons.extend(semantic_reasons)
        return FactCandidate(
            fact,
            method,
            not reasons,
            tuple(reasons),
            rank,
            semantic_reasons if semantic is not None else (),
        )

    @staticmethod
    def _period_reasons(
        fact: RawFact, period: CanonicalPeriodContext, spec: MetricSpec
    ) -> list[str]:
        """Apply selected-filing identity and exact fiscal-period compatibility."""
        reasons: list[str] = []
        if fact.accession != period.target_accession:
            reasons.append("accession mismatch")
        if fact.filing_form != period.target_form:
            reasons.append("filing form mismatch")
        if fact.filing_date != period.filing_date:
            reasons.append("filing date mismatch")
        if fact.fiscal_year != period.fiscal_year:
            reasons.append("canonical fiscal year mismatch")
        if spec.period_kind is PeriodKind.INSTANT:
            if fact.end != period.instant_date:
                reasons.append("instant date mismatch")
        else:
            if fact.fiscal_period != "FY":
                reasons.append("not fiscal-year duration")
            if fact.end != period.duration_end:
                reasons.append("duration end date mismatch")
            if period.duration_start is None or fact.start != period.duration_start:
                reasons.append("duration start date mismatch")
        return reasons

    @staticmethod
    def _method(fact: RawFact, context: FactContext, spec: MetricSpec) -> ResolutionMethod | None:
        if fact.taxonomy == spec.standard_taxonomy and fact.concept == spec.standard_concept:
            return ResolutionMethod.STANDARD_CONCEPT
        if fact.taxonomy == spec.standard_taxonomy and fact.concept in spec.approved_aliases:
            return ResolutionMethod.STANDARD_ALIAS
        mapping = (context.extension_mappings or {}).get((fact.taxonomy, fact.concept))
        if mapping and mapping.target_metric == spec.metric and mapping.valid:
            return (
                ResolutionMethod.TAXONOMY_RELATIONSHIP
                if fact.taxonomy == spec.standard_taxonomy
                else ResolutionMethod.ISSUER_EXTENSION
            )
        semantic = (context.semantic_extensions or {}).get((fact.taxonomy, fact.concept))
        if semantic is not None and semantic.target_metric == spec.metric:
            return ResolutionMethod.EXTENSION_STRUCTURAL
        return None

    @staticmethod
    def _method_rank(method: ResolutionMethod | None) -> int:
        if method is None:
            return 0
        return {
            ResolutionMethod.STANDARD_CONCEPT: 4,
            ResolutionMethod.STANDARD_ALIAS: 3,
            ResolutionMethod.TAXONOMY_RELATIONSHIP: 2,
            ResolutionMethod.ISSUER_EXTENSION: 1,
            ResolutionMethod.EXTENSION_STRUCTURAL: 1,
        }[method]

    @staticmethod
    def _unresolved(
        spec: MetricSpec,
        status: ResolutionStatus,
        candidates: tuple[FactCandidate, ...],
        message: str,
    ) -> CanonicalMetric:
        return CanonicalMetric(
            spec,
            ResolutionDecision(status, ResolutionMethod.UNRESOLVED, None, candidates, (message,)),
            None,
            None,
            None,
        )

    @staticmethod
    def _reconcile(metrics: Mapping[str, CanonicalMetric]) -> tuple[str, ...]:
        assets, liabilities, equity = (
            metrics.get(name) for name in ("assets", "liabilities", "equity")
        )
        if any(
            item is None or item.normalized_value is None for item in (assets, liabilities, equity)
        ):
            return ("balance-sheet identity not evaluated",)
        assert assets and liabilities and equity
        assert assets.normalized_value is not None
        assert liabilities.normalized_value is not None
        assert equity.normalized_value is not None
        tolerance = max(1.0, abs(assets.normalized_value) * 0.0001)
        difference = (
            assets.normalized_value - liabilities.normalized_value - equity.normalized_value
        )
        return (
            ("balance-sheet identity passed",)
            if abs(difference) <= tolerance
            else ("balance-sheet identity failed",)
        )


def derive_q4(
    annual: CanonicalMetric, prior_ytd: CanonicalMetric, current_ytd: CanonicalMetric
) -> CanonicalMetric:
    """Derive Q4 only from compatible resolved duration metrics; otherwise fail closed."""
    items = (annual, prior_ytd, current_ytd)
    spec = annual.spec
    if any(
        item.decision.status is not ResolutionStatus.RESOLVED or item.raw_fact is None
        for item in items
    ):
        return FinancialCanonicalizer._unresolved(
            spec, ResolutionStatus.MISSING, (), "Q4 inputs unresolved"
        )
    annual_raw, prior_raw, current_raw = annual.raw_fact, prior_ytd.raw_fact, current_ytd.raw_fact
    assert annual_raw is not None and prior_raw is not None and current_raw is not None
    raw = (annual_raw, prior_raw, current_raw)
    compatible = (
        annual_raw.unit == prior_raw.unit == current_raw.unit
        and annual_raw.period_kind
        is prior_raw.period_kind
        is current_raw.period_kind
        is PeriodKind.DURATION
        and annual_raw.taxonomy == prior_raw.taxonomy == current_raw.taxonomy
        and annual_raw.concept == prior_raw.concept == current_raw.concept
        and not any(item.dimensions or not item.consolidated for item in raw)
    )
    if not compatible:
        return FinancialCanonicalizer._unresolved(
            spec, ResolutionStatus.CONFLICT, (), "Q4 inputs incompatible"
        )
    value = annual_raw.value - current_raw.value
    synthetic = RawFact(
        "derived-q4",
        annual_raw.taxonomy,
        annual_raw.concept,
        value,
        annual_raw.unit,
        PeriodKind.DURATION,
        current_raw.end,
        annual_raw.end,
        annual_raw.fiscal_year,
        "Q4",
        annual_raw.filing_form,
        annual_raw.accession,
        annual_raw.filing_date,
        annual_raw.source_identity,
    )
    decision = ResolutionDecision(
        ResolutionStatus.RESOLVED,
        ResolutionMethod.DERIVED,
        synthetic.fact_id,
        (),
        ("FY minus comparable YTD",),
    )
    return CanonicalMetric(spec, decision, synthetic, value, spec.unit)


INITIAL_METRIC_SPECS = (
    MetricSpec(
        "revenue",
        "us-gaap",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        # Revenues is the US-GAAP, duration monetary total-revenue concept.  Its
        # taxonomy documentation covers revenue from goods, services, premiums,
        # and other earning activities; it is not a company-specific subtotal.
        ("SalesRevenueNet", "Revenues"),
        "USD",
        PeriodKind.DURATION,
    ),
    MetricSpec(
        "operating_income", "us-gaap", "OperatingIncomeLoss", (), "USD", PeriodKind.DURATION
    ),
    MetricSpec("net_income", "us-gaap", "NetIncomeLoss", (), "USD", PeriodKind.DURATION),
    MetricSpec(
        "cash_and_equivalents",
        "us-gaap",
        "CashAndCashEquivalentsAtCarryingValue",
        (),
        "USD",
        PeriodKind.INSTANT,
    ),
    MetricSpec(
        "total_debt",
        "us-gaap",
        "LongTermDebtAndFinanceLeaseObligationsCurrent",
        ("LongTermDebtCurrent",),
        "USD",
        PeriodKind.INSTANT,
    ),
    MetricSpec("total_assets", "us-gaap", "Assets", (), "USD", PeriodKind.INSTANT),
    MetricSpec("total_liabilities", "us-gaap", "Liabilities", (), "USD", PeriodKind.INSTANT),
    MetricSpec(
        "shareholders_equity",
        "us-gaap",
        "StockholdersEquity",
        ("StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",),
        "USD",
        PeriodKind.INSTANT,
    ),
    MetricSpec(
        "diluted_shares",
        "us-gaap",
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        (),
        "shares",
        PeriodKind.DURATION,
    ),
)


def extract_company_facts(
    payload: Mapping[str, object], *, source_identity: str
) -> tuple[RawFact, ...]:
    """Parse every SEC company-facts observation without collapsing competitors."""
    facts = payload.get("facts")
    if not isinstance(facts, Mapping):
        raise ValueError("company facts payload has no facts object")
    result: list[RawFact] = []
    for taxonomy, concepts in facts.items():
        if not isinstance(taxonomy, str) or not isinstance(concepts, Mapping):
            raise ValueError("invalid company facts taxonomy")
        for concept, detail in concepts.items():
            if not isinstance(concept, str) or not isinstance(detail, Mapping):
                raise ValueError("invalid company facts concept")
            units = detail.get("units")
            if not isinstance(units, Mapping):
                raise ValueError("company facts concept has no units")
            for unit, observations in units.items():
                if not isinstance(unit, str) or not isinstance(observations, list):
                    raise ValueError("invalid company facts unit")
                for index, observation in enumerate(observations):
                    if not isinstance(observation, Mapping):
                        raise ValueError("invalid company facts observation")
                    try:
                        end = date.fromisoformat(str(observation["end"]))
                        start_value = observation.get("start")
                        start = date.fromisoformat(str(start_value)) if start_value else None
                        kind = PeriodKind.DURATION if start else PeriodKind.INSTANT
                        value = float(observation["val"])
                        filed = date.fromisoformat(str(observation["filed"]))
                        accession = str(observation["accn"])
                        form = str(observation["form"])
                    except (KeyError, TypeError, ValueError) as exc:
                        raise ValueError("malformed company facts observation") from exc
                    result.append(
                        RawFact(
                            f"{taxonomy}:{concept}:{unit}:{index}",
                            taxonomy,
                            concept,
                            value,
                            unit,
                            kind,
                            start,
                            end,
                            int(observation.get("fy") or 0),
                            str(observation.get("fp") or ""),
                            form,
                            accession,
                            filed,
                            source_identity,
                            (),
                            True,
                            form.endswith("/A"),
                            False,
                            str(detail.get("label") or "") or None,
                            None,
                            None,
                        )
                    )
    return tuple(result)


class CanonicalizationEngine:
    """Resolve company facts only against an explicitly selected filing period."""

    def canonicalize(
        self,
        company: object,
        staged_evidence: Mapping[str, object],
        *,
        profile: IssuerProfile,
        source_identity: str,
    ) -> CanonicalFinancials:
        del company
        try:
            companyfacts, selected_filing = self._staged_companyfacts_and_filing(staged_evidence)
            facts = extract_company_facts(companyfacts, source_identity=source_identity)
            period = self._period_context(selected_filing, facts)
        except ValueError:
            invalid_metrics = {
                spec.metric: FinancialCanonicalizer._unresolved(
                    spec, ResolutionStatus.INVALID, (), "malformed staged company facts"
                )
                for spec in INITIAL_METRIC_SPECS
            }
            return CanonicalFinancials(profile, invalid_metrics, ("source payload invalid",), True)
        resolver = FinancialCanonicalizer()
        metrics: dict[str, CanonicalMetric] = {}
        for spec in INITIAL_METRIC_SPECS:
            candidates = tuple(fact for fact in facts if fact.period_kind is spec.period_kind)
            context = FactContext(
                period.report_date,
                fiscal_year=period.fiscal_year,
                fiscal_period="FY" if spec.period_kind is PeriodKind.DURATION else None,
                canonical_period=period,
            )
            metrics[spec.metric] = resolver.resolve(profile, context, spec, candidates)
        return (
            resolver.financials(profile, FactContext(date.min), (), ())
            if False
            else CanonicalFinancials(
                profile,
                metrics,
                resolver._reconcile(metrics),
                any(item.endswith("failed") for item in resolver._reconcile(metrics)),
            )
        )

    @staticmethod
    def _staged_companyfacts_and_filing(
        staged_evidence: Mapping[str, object],
    ) -> tuple[Mapping[str, object], Mapping[str, object]]:
        """Require explicit selected-10-K metadata rather than candidate-derived dates."""
        companyfacts = staged_evidence.get("companyfacts")
        selected = staged_evidence.get("selected_filing")
        if not isinstance(companyfacts, Mapping) or not isinstance(selected, Mapping):
            raise ValueError("staged evidence requires companyfacts and selected_filing")
        return companyfacts, selected

    @staticmethod
    def _period_context(
        selected_filing: Mapping[str, object], facts: tuple[RawFact, ...]
    ) -> CanonicalPeriodContext:
        """Derive the actual FY duration from observations in the designated filing."""
        try:
            accession = str(selected_filing["accession"])
            form = str(selected_filing["form"])
            filing_date = date.fromisoformat(str(selected_filing["filing_date"]))
            report_date = date.fromisoformat(str(selected_filing["report_date"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid selected filing metadata") from exc
        if form != "10-K":
            raise ValueError("canonical period requires selected original 10-K")
        annual = tuple(
            fact
            for fact in facts
            if fact.accession == accession
            and fact.filing_form == form
            and fact.filing_date == filing_date
            and fact.period_kind is PeriodKind.DURATION
            and fact.end == report_date
            and fact.fiscal_period == "FY"
        )
        starts = {fact.start for fact in annual}
        years = {fact.fiscal_year for fact in annual if fact.fiscal_year}
        if not starts or None in starts or len(years) != 1:
            raise ValueError("selected filing does not establish one annual fiscal duration")
        # A 10-K can tag a short, year-to-date observation as FY (for example,
        # a dividend declaration).  The filing's fiscal-year duration is the
        # earliest start among its FY observations ending on the report date;
        # this works for 52/53-week calendars without a day-count assumption.
        duration_start = min(item for item in starts if item is not None)
        return CanonicalPeriodContext(
            accession,
            form,
            filing_date,
            report_date,
            years.pop(),
            duration_start,
            report_date,
            report_date,
        )
