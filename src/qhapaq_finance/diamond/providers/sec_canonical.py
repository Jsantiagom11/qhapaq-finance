"""Canonical issuer-level SEC snapshot cache."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date

from qhapaq_finance.diamond.cache import DiamondCache, DiamondCacheError
from qhapaq_finance.diamond.canonical_json import sha256_canonical_json
from qhapaq_finance.diamond.contracts import (
    FiscalSlot,
    FundamentalObservation,
    FundamentalPeriodType,
    PeriodKind,
    UnitKind,
)
from qhapaq_finance.evidence import DerivedFact, FinancialFact
from qhapaq_finance.financial_canonicalization import (
    PeriodKind as CanonicalPeriodKind,
)
from qhapaq_finance.financial_canonicalization import RawFact
from qhapaq_finance.financial_promotion import (
    FinancialPromotionError,
    FinancialPromotionFailureKind,
    MultiPeriodFinancialPromoter,
    accounting_evidence_policies,
)

CANONICAL_SCHEMA_VERSION = "diamond-canonical-issuer-v1"
SEC_CANONICALIZER_VERSION = "sec-canonicalizer-v2"


class SecCanonicalError(RuntimeError):
    """Canonical SEC issuer data cannot be trusted."""


@dataclass(frozen=True, slots=True)
class CanonicalIssuerSnapshot:
    schema_version: str
    canonicalizer_version: str
    issuer_id: str
    cik: str
    as_of: date
    history_years: int
    evidence_revision_sha256: str
    fundamental_period_type: FundamentalPeriodType
    fundamental_period_end: date
    fiscal_year_end: str | None
    observations: tuple[FundamentalObservation, ...]


_FISCAL_SLOTS = (
    FiscalSlot.FY1,
    FiscalSlot.FY2,
    FiscalSlot.FY3,
    FiscalSlot.FY4,
    FiscalSlot.FY5,
)

_DURATION_CONCEPTS: dict[str, tuple[tuple[str, str], ...]] = {
    "revenue": (
        ("RevenueFromContractWithCustomerExcludingAssessedTax", "USD"),
        ("Revenues", "USD"),
        ("SalesRevenueNet", "USD"),
    ),
    "operating_income": (("OperatingIncomeLoss", "USD"),),
    "operating_cash_flow": (
        ("NetCashProvidedByUsedInOperatingActivities", "USD"),
        ("NetCashProvidedByUsedInOperatingActivitiesContinuingOperations", "USD"),
    ),
    "capital_expenditures": (
        ("PaymentsToAcquirePropertyPlantAndEquipment", "USD"),
        ("PaymentsForAdditionsToPropertyPlantAndEquipment", "USD"),
    ),
    "pretax_income": (
        (
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxes"
            "ExtraordinaryItemsNoncontrollingInterest",
            "USD",
        ),
        (
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxes"
            "MinorityInterestAndIncomeLossFromEquityMethodInvestments",
            "USD",
        ),
    ),
    "income_tax_expense": (("IncomeTaxExpenseBenefit", "USD"),),
    "diluted_shares": (("WeightedAverageNumberOfDilutedSharesOutstanding", "shares"),),
}


def _promotion_form(form: str) -> str:
    if form == "10-K/A":
        return "10-K"
    if form == "10-Q/A":
        return "10-Q"
    return form


def _promote_ttm(
    facts: tuple[RawFact, ...],
    concepts: tuple[tuple[str, str], ...],
) -> FinancialFact | DerivedFact | None:
    promoter = MultiPeriodFinancialPromoter()
    for concept, unit in concepts:
        candidates = tuple(
            fact
            for fact in facts
            if fact.taxonomy == "us-gaap" and fact.concept == concept and fact.unit == unit
        )
        try:
            return promoter.promote_ttm(candidates, concept=concept)
        except FinancialPromotionError as exc:
            if exc.kind is FinancialPromotionFailureKind.AMBIGUOUS_CONTEXT:
                raise SecCanonicalError("SEC_TTM_FACT_AMBIGUOUS") from exc
    return None


def _annual_fact(
    facts: tuple[RawFact, ...],
    *,
    concepts: tuple[tuple[str, str], ...],
    period_end: date,
) -> RawFact | None:
    for concept, unit in concepts:
        candidates = tuple(
            fact
            for fact in facts
            if fact.taxonomy == "us-gaap"
            and fact.concept == concept
            and fact.unit == unit
            and fact.period_kind is CanonicalPeriodKind.DURATION
            and fact.filing_form in {"10-K", "10-K/A"}
            and fact.fiscal_period == "FY"
            and fact.start is not None
            and 250 <= (fact.end - fact.start).days <= 450
            and fact.end == period_end
        )
        if not candidates:
            continue
        rank = max((fact.filing_date, fact.accession) for fact in candidates)
        winners = tuple(fact for fact in candidates if (fact.filing_date, fact.accession) == rank)
        if len({fact.value for fact in winners}) != 1:
            raise SecCanonicalError("SEC_ANNUAL_FACT_AMBIGUOUS")
        return winners[0]
    return None


def _annual_ends(facts: tuple[RawFact, ...]) -> tuple[date, ...]:
    for concept, unit in _DURATION_CONCEPTS["revenue"]:
        ends = {
            fact.end
            for fact in facts
            if fact.taxonomy == "us-gaap"
            and fact.concept == concept
            and fact.unit == unit
            and fact.period_kind is CanonicalPeriodKind.DURATION
            and fact.filing_form in {"10-K", "10-K/A"}
            and fact.fiscal_period == "FY"
            and fact.start is not None
            and 250 <= (fact.end - fact.start).days <= 450
        }
        if ends:
            return tuple(sorted(ends, reverse=True)[: len(_FISCAL_SLOTS)])
    return ()


def _instant_fact(
    facts: tuple[RawFact, ...],
    *,
    taxonomy: str,
    concept: str,
    unit: str,
    period_end: date,
) -> RawFact | None:
    candidates = tuple(
        fact
        for fact in facts
        if fact.taxonomy == taxonomy
        and fact.concept == concept
        and fact.unit == unit
        and fact.period_kind is CanonicalPeriodKind.INSTANT
        and fact.end == period_end
    )
    if not candidates:
        return None
    rank = max((fact.filing_date, fact.accession) for fact in candidates)
    winners = tuple(fact for fact in candidates if (fact.filing_date, fact.accession) == rank)
    if len({fact.value for fact in winners}) != 1:
        raise SecCanonicalError("SEC_INSTANT_FACT_AMBIGUOUS")
    return winners[0]


def _latest_balance_end(facts: tuple[RawFact, ...]) -> date | None:
    ends = (
        fact.end
        for fact in facts
        if fact.period_kind is CanonicalPeriodKind.INSTANT
        and fact.unit == "USD"
        and fact.taxonomy == "us-gaap"
    )
    return max(ends, default=None)


def _latest_instant_fact(
    facts: tuple[RawFact, ...],
    *,
    taxonomy: str,
    concept: str,
    unit: str,
) -> RawFact | None:
    ends = tuple(
        fact.end
        for fact in facts
        if fact.taxonomy == taxonomy
        and fact.concept == concept
        and fact.unit == unit
        and fact.period_kind is CanonicalPeriodKind.INSTANT
    )
    if not ends:
        return None
    return _instant_fact(
        facts,
        taxonomy=taxonomy,
        concept=concept,
        unit=unit,
        period_end=max(ends),
    )


def _promoted_instants(
    facts: tuple[RawFact, ...],
    target_end: date,
) -> dict[str, FinancialFact | DerivedFact]:
    policies = {
        policy.metric_id: policy for policy in accounting_evidence_policies(closing_end=target_end)
    }
    promoter = MultiPeriodFinancialPromoter()
    selected: dict[str, FinancialFact | DerivedFact] = {}
    for source_name, metric_id in (
        ("cash", "cash_and_equivalents"),
        ("marketable_securities", "marketable_securities"),
        ("total_debt", "total_debt"),
        ("common_equity", "total_equity"),
    ):
        try:
            selected[metric_id] = promoter.promote(facts, policy=policies[source_name])
        except FinancialPromotionError as exc:
            if exc.kind is FinancialPromotionFailureKind.AMBIGUOUS_CONTEXT:
                raise SecCanonicalError("SEC_INSTANT_FACT_AMBIGUOUS") from exc
    return selected


def canonicalize_issuer(
    *,
    issuer_id: str,
    cik: str,
    as_of: date,
    history_years: int,
    evidence_revision_sha256: str,
    facts: tuple[RawFact, ...],
) -> CanonicalIssuerSnapshot | None:
    """Build immutable SEC accounting observations for one issuer evidence revision."""
    if history_years < 1:
        raise ValueError("history_years must be positive")
    if not facts:
        return None

    promotion_facts = tuple(
        replace(item, filing_form=_promotion_form(item.filing_form)) for item in facts
    )
    annual_ends = _annual_ends(facts)[:history_years]
    revenue_ttm = _promote_ttm(promotion_facts, _DURATION_CONCEPTS["revenue"])
    fundamental_end = (
        revenue_ttm.period_end if revenue_ttm is not None else _latest_balance_end(facts)
    )
    if fundamental_end is None:
        return None

    source_identity = f"sec-evidence:{evidence_revision_sha256}"
    observations: list[FundamentalObservation] = []

    def add(
        metric_id: str,
        slot: FiscalSlot,
        raw_value: float | None,
        *,
        period_start: date | None,
        period_end: date,
        period_kind: PeriodKind,
        unit_kind: UnitKind,
        share_class_id: str | None = None,
        adjustment_basis_id: str | None = None,
    ) -> None:
        if raw_value is None:
            return
        canonical_value = abs(raw_value) if metric_id == "capital_expenditures" else raw_value
        observations.append(
            FundamentalObservation(
                metric_id=metric_id,
                fiscal_slot=slot,
                value=canonical_value,
                period_start=period_start,
                period_end=period_end,
                period_kind=period_kind,
                unit_kind=unit_kind,
                source_provider="sec",
                source_identity=source_identity,
                share_class_id=share_class_id,
                adjustment_basis_id=adjustment_basis_id,
            )
        )

    for metric_id, concepts in _DURATION_CONCEPTS.items():
        promoted = (
            revenue_ttm if metric_id == "revenue" else _promote_ttm(promotion_facts, concepts)
        )
        if promoted is None or promoted.period_end != fundamental_end:
            continue
        add(
            metric_id,
            FiscalSlot.TTM,
            promoted.value,
            period_start=promoted.period_start,
            period_end=promoted.period_end,
            period_kind=PeriodKind.DURATION,
            unit_kind=(UnitKind.SHARES if metric_id == "diluted_shares" else UnitKind.CURRENCY),
            adjustment_basis_id=(
                "SEC_REPORTED_DILUTED_V1" if metric_id == "diluted_shares" else None
            ),
            share_class_id=("CONSOLIDATED_COMMON" if metric_id == "diluted_shares" else None),
        )

    for slot, annual_end in zip(_FISCAL_SLOTS, annual_ends, strict=False):
        for metric_id, concepts in _DURATION_CONCEPTS.items():
            fact = _annual_fact(facts, concepts=concepts, period_end=annual_end)
            if fact is None:
                continue
            add(
                metric_id,
                slot,
                fact.value,
                period_start=fact.start,
                period_end=fact.end,
                period_kind=PeriodKind.DURATION,
                unit_kind=(UnitKind.SHARES if metric_id == "diluted_shares" else UnitKind.CURRENCY),
                adjustment_basis_id=(
                    "SEC_REPORTED_DILUTED_V1" if metric_id == "diluted_shares" else None
                ),
                share_class_id=("CONSOLIDATED_COMMON" if metric_id == "diluted_shares" else None),
            )
        for metric_id, promoted in _promoted_instants(promotion_facts, annual_end).items():
            add(
                metric_id,
                slot,
                promoted.value,
                period_start=None,
                period_end=promoted.period_end,
                period_kind=PeriodKind.INSTANT,
                unit_kind=UnitKind.CURRENCY,
            )

    latest_end = _latest_balance_end(facts)
    if latest_end is not None:
        for metric_id, promoted in _promoted_instants(promotion_facts, latest_end).items():
            add(
                metric_id,
                FiscalSlot.LATEST,
                promoted.value,
                period_start=None,
                period_end=promoted.period_end,
                period_kind=PeriodKind.INSTANT,
                unit_kind=UnitKind.CURRENCY,
            )
        latest_shares = _latest_instant_fact(
            facts,
            taxonomy="dei",
            concept="EntityCommonStockSharesOutstanding",
            unit="shares",
        )
        if latest_shares is not None:
            add(
                "shares_outstanding_latest",
                FiscalSlot.LATEST,
                latest_shares.value,
                period_start=None,
                period_end=latest_shares.end,
                period_kind=PeriodKind.INSTANT,
                unit_kind=UnitKind.SHARES,
                share_class_id="CONSOLIDATED_COMMON",
                adjustment_basis_id="SEC_REPORTED_COMMON_V1",
            )

    if annual_ends:
        annual_shares = _instant_fact(
            facts,
            taxonomy="dei",
            concept="EntityCommonStockSharesOutstanding",
            unit="shares",
            period_end=annual_ends[0],
        )
        if annual_shares is not None:
            add(
                "shares_outstanding_fy1_end",
                FiscalSlot.FY1,
                annual_shares.value,
                period_start=None,
                period_end=annual_shares.end,
                period_kind=PeriodKind.INSTANT,
                unit_kind=UnitKind.SHARES,
                share_class_id="CONSOLIDATED_COMMON",
                adjustment_basis_id="SEC_REPORTED_COMMON_V1",
            )

    return CanonicalIssuerSnapshot(
        schema_version=CANONICAL_SCHEMA_VERSION,
        canonicalizer_version=SEC_CANONICALIZER_VERSION,
        issuer_id=issuer_id,
        cik=cik,
        as_of=as_of,
        history_years=history_years,
        evidence_revision_sha256=evidence_revision_sha256,
        fundamental_period_type=FundamentalPeriodType.TTM,
        fundamental_period_end=fundamental_end,
        fiscal_year_end=(annual_ends[0].isoformat()[5:] if annual_ends else None),
        observations=tuple(observations),
    )


def _identity_payload(
    *,
    schema_version: str,
    canonicalizer_version: str,
    issuer_id: str,
    as_of: date,
    history_years: int,
    evidence_revision_sha256: str,
) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "canonicalizer_version": canonicalizer_version,
        "issuer_id": issuer_id,
        "as_of": as_of.isoformat(),
        "history_years": history_years,
        "evidence_revision_sha256": evidence_revision_sha256,
    }


def _observation_payload(observation: FundamentalObservation) -> dict[str, object]:
    return {
        "metric_id": observation.metric_id,
        "fiscal_slot": observation.fiscal_slot.value,
        "value": observation.value,
        "period_start": (
            observation.period_start.isoformat() if observation.period_start is not None else None
        ),
        "period_end": observation.period_end.isoformat(),
        "period_kind": observation.period_kind.value,
        "unit_kind": observation.unit_kind.value,
        "source_provider": observation.source_provider,
        "source_identity": observation.source_identity,
        "share_class_id": observation.share_class_id,
        "adjustment_basis_id": observation.adjustment_basis_id,
    }


def _snapshot_payload(snapshot: CanonicalIssuerSnapshot) -> dict[str, object]:
    return {
        "schema_version": snapshot.schema_version,
        "canonicalizer_version": snapshot.canonicalizer_version,
        "issuer_id": snapshot.issuer_id,
        "cik": snapshot.cik,
        "as_of": snapshot.as_of.isoformat(),
        "history_years": snapshot.history_years,
        "evidence_revision_sha256": snapshot.evidence_revision_sha256,
        "fundamental_period_type": snapshot.fundamental_period_type.value,
        "fundamental_period_end": snapshot.fundamental_period_end.isoformat(),
        "fiscal_year_end": snapshot.fiscal_year_end,
        "observations": [
            _observation_payload(observation) for observation in snapshot.observations
        ],
    }


def _required_text(
    payload: Mapping[str, object],
    field: str,
) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise SecCanonicalError("CANONICAL_CACHE_PAYLOAD_INVALID")
    return value


def _decode_observation(raw: object) -> FundamentalObservation:
    if not isinstance(raw, Mapping):
        raise SecCanonicalError("CANONICAL_CACHE_PAYLOAD_INVALID")

    try:
        period_start_raw = raw.get("period_start")
        source_identity_raw = raw.get("source_identity")
        share_class_raw = raw.get("share_class_id")
        adjustment_basis_raw = raw.get("adjustment_basis_id")
        value_raw = raw["value"]

        if isinstance(value_raw, bool) or not isinstance(value_raw, (int, float)):
            raise SecCanonicalError("CANONICAL_CACHE_PAYLOAD_INVALID")

        if period_start_raw is not None and not isinstance(period_start_raw, str):
            raise SecCanonicalError("CANONICAL_CACHE_PAYLOAD_INVALID")
        if source_identity_raw is not None and not isinstance(source_identity_raw, str):
            raise SecCanonicalError("CANONICAL_CACHE_PAYLOAD_INVALID")
        if share_class_raw is not None and not isinstance(share_class_raw, str):
            raise SecCanonicalError("CANONICAL_CACHE_PAYLOAD_INVALID")
        if adjustment_basis_raw is not None and not isinstance(
            adjustment_basis_raw,
            str,
        ):
            raise SecCanonicalError("CANONICAL_CACHE_PAYLOAD_INVALID")

        return FundamentalObservation(
            metric_id=_required_text(raw, "metric_id"),
            fiscal_slot=FiscalSlot(_required_text(raw, "fiscal_slot")),
            value=float(value_raw),
            period_start=(
                date.fromisoformat(period_start_raw) if period_start_raw is not None else None
            ),
            period_end=date.fromisoformat(_required_text(raw, "period_end")),
            period_kind=PeriodKind(_required_text(raw, "period_kind")),
            unit_kind=UnitKind(_required_text(raw, "unit_kind")),
            source_provider=_required_text(raw, "source_provider"),
            source_identity=source_identity_raw,
            share_class_id=share_class_raw,
            adjustment_basis_id=adjustment_basis_raw,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SecCanonicalError("CANONICAL_CACHE_PAYLOAD_INVALID") from exc


def _decode_snapshot(payload: Mapping[str, object]) -> CanonicalIssuerSnapshot:
    observations_raw = payload.get("observations")
    history_years_raw = payload.get("history_years")
    fiscal_year_end_raw = payload.get("fiscal_year_end")

    if not isinstance(observations_raw, list):
        raise SecCanonicalError("CANONICAL_CACHE_PAYLOAD_INVALID")

    if (
        isinstance(history_years_raw, bool)
        or not isinstance(history_years_raw, int)
        or history_years_raw < 1
    ):
        raise SecCanonicalError("CANONICAL_CACHE_PAYLOAD_INVALID")

    if fiscal_year_end_raw is not None and not isinstance(fiscal_year_end_raw, str):
        raise SecCanonicalError("CANONICAL_CACHE_PAYLOAD_INVALID")

    try:
        return CanonicalIssuerSnapshot(
            schema_version=_required_text(payload, "schema_version"),
            canonicalizer_version=_required_text(
                payload,
                "canonicalizer_version",
            ),
            issuer_id=_required_text(payload, "issuer_id"),
            cik=_required_text(payload, "cik"),
            as_of=date.fromisoformat(_required_text(payload, "as_of")),
            history_years=history_years_raw,
            evidence_revision_sha256=_required_text(
                payload,
                "evidence_revision_sha256",
            ),
            fundamental_period_type=FundamentalPeriodType(
                _required_text(payload, "fundamental_period_type")
            ),
            fundamental_period_end=date.fromisoformat(
                _required_text(payload, "fundamental_period_end")
            ),
            fiscal_year_end=fiscal_year_end_raw,
            observations=tuple(_decode_observation(raw) for raw in observations_raw),
        )
    except (TypeError, ValueError) as exc:
        raise SecCanonicalError("CANONICAL_CACHE_PAYLOAD_INVALID") from exc


class CanonicalIssuerCache:
    PROVIDER = "sec-canonical-issuer"

    def __init__(self, cache: DiamondCache) -> None:
        self._cache = cache
        self.cache_hits = 0
        self.cache_misses = 0

    @staticmethod
    def _identity(
        *,
        schema_version: str,
        canonicalizer_version: str,
        issuer_id: str,
        as_of: date,
        history_years: int,
        evidence_revision_sha256: str,
    ) -> str:
        digest = sha256_canonical_json(
            _identity_payload(
                schema_version=schema_version,
                canonicalizer_version=canonicalizer_version,
                issuer_id=issuer_id,
                as_of=as_of,
                history_years=history_years,
                evidence_revision_sha256=evidence_revision_sha256,
            )
        )
        return f"sec-canonical:{digest}"

    @classmethod
    def request_identity(
        cls,
        *,
        issuer_id: str,
        as_of: date,
        history_years: int,
        evidence_revision_sha256: str,
    ) -> str:
        return cls._identity(
            schema_version=CANONICAL_SCHEMA_VERSION,
            canonicalizer_version=SEC_CANONICALIZER_VERSION,
            issuer_id=issuer_id,
            as_of=as_of,
            history_years=history_years,
            evidence_revision_sha256=evidence_revision_sha256,
        )

    def store(
        self,
        snapshot: CanonicalIssuerSnapshot,
    ) -> CanonicalIssuerSnapshot:
        if snapshot.schema_version != CANONICAL_SCHEMA_VERSION:
            raise SecCanonicalError("CANONICAL_CACHE_SCHEMA_MISMATCH")

        identity = self._identity(
            schema_version=snapshot.schema_version,
            canonicalizer_version=snapshot.canonicalizer_version,
            issuer_id=snapshot.issuer_id,
            as_of=snapshot.as_of,
            history_years=snapshot.history_years,
            evidence_revision_sha256=snapshot.evidence_revision_sha256,
        )

        try:
            self._cache.store(
                identity,
                provider=self.PROVIDER,
                data_as_of=snapshot.as_of,
                payload=_snapshot_payload(snapshot),
            )
        except DiamondCacheError as exc:
            raise SecCanonicalError("CANONICAL_CACHE_WRITE_FAILED") from exc

        return snapshot

    def load(
        self,
        *,
        issuer_id: str,
        as_of: date,
        history_years: int,
        evidence_revision_sha256: str,
    ) -> CanonicalIssuerSnapshot | None:
        identity = self.request_identity(
            issuer_id=issuer_id,
            as_of=as_of,
            history_years=history_years,
            evidence_revision_sha256=evidence_revision_sha256,
        )

        try:
            cached = self._cache.load(identity)
        except DiamondCacheError as exc:
            raise SecCanonicalError("CANONICAL_CACHE_INVALID") from exc

        if cached is None:
            self.cache_misses += 1
            return None

        if cached.provider != self.PROVIDER:
            raise SecCanonicalError("CANONICAL_CACHE_PROVIDER_MISMATCH")
        if cached.data_as_of != as_of:
            raise SecCanonicalError("CANONICAL_CACHE_AS_OF_MISMATCH")
        if not isinstance(cached.payload, Mapping):
            raise SecCanonicalError("CANONICAL_CACHE_PAYLOAD_INVALID")

        payload = cached.payload

        if payload.get("schema_version") != CANONICAL_SCHEMA_VERSION:
            raise SecCanonicalError("CANONICAL_CACHE_SCHEMA_MISMATCH")
        if payload.get("canonicalizer_version") != SEC_CANONICALIZER_VERSION:
            raise SecCanonicalError("CANONICAL_CACHE_CANONICALIZER_MISMATCH")
        if payload.get("issuer_id") != issuer_id:
            raise SecCanonicalError("CANONICAL_CACHE_ISSUER_MISMATCH")
        if payload.get("as_of") != as_of.isoformat():
            raise SecCanonicalError("CANONICAL_CACHE_AS_OF_MISMATCH")
        if payload.get("history_years") != history_years:
            raise SecCanonicalError("CANONICAL_CACHE_HISTORY_MISMATCH")
        if payload.get("evidence_revision_sha256") != evidence_revision_sha256:
            raise SecCanonicalError("CANONICAL_CACHE_REVISION_MISMATCH")

        snapshot = _decode_snapshot(payload)

        self.cache_hits += 1
        return snapshot
