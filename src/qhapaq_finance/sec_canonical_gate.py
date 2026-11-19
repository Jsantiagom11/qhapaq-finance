"""Typed SEC-only gate for the existing canonical accounting boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, DecimalException, localcontext
from enum import Enum

from .accounting import (
    AccountingError,
    AccountingEvidenceFailure,
    AccountingEvidenceFailureKind,
    AccountingEvidenceGap,
    AccountingEvidenceGapKind,
    AccountingSnapshot,
    normalize_accounting_snapshot,
    promote_sec_accounting_evidence,
)
from .financial_canonicalization import RawFact, SemanticEvidence, XbrlDecimals
from .financial_promotion import MetricPromotionPolicy, accounting_evidence_policies


class SecCanonicalGateState(str, Enum):
    READY = "READY"
    GAP = "GAP"
    BLOCKED = "BLOCKED"


class SecCanonicalReason(str, Enum):
    MISSING_STANDARD_CONCEPT = "MISSING_STANDARD_CONCEPT"
    STANDARD_CONCEPT_COVERAGE_GAP = "STANDARD_CONCEPT_COVERAGE_GAP"
    REQUIRED_COMPONENT_MISSING = "REQUIRED_COMPONENT_MISSING"
    PERIOD_COVERAGE_GAP = "PERIOD_COVERAGE_GAP"
    AMBIGUOUS_CONTEXT = "AMBIGUOUS_CONTEXT"
    EXTENSION_DISCOVERY_REQUIRED = "EXTENSION_DISCOVERY_REQUIRED"
    FILING_CONTEXT_REQUIRED = "FILING_CONTEXT_REQUIRED"
    MALFORMED_EVIDENCE = "MALFORMED_EVIDENCE"
    CANONICAL_CONFLICT = "CANONICAL_CONFLICT"
    CANONICAL_INVARIANT = "CANONICAL_INVARIANT"


SecCanonicalGapReason = SecCanonicalReason


@dataclass(frozen=True)
class SecCanonicalGateResult:
    state: SecCanonicalGateState
    reason: SecCanonicalReason | None
    snapshot: AccountingSnapshot | None


def evaluate_sec_canonical_gate(
    raw_facts: tuple[RawFact, ...],
    *,
    semantic_extensions: Mapping[tuple[str, str], SemanticEvidence] | None = None,
) -> SecCanonicalGateResult:
    """Evaluate SEC accounting evidence without valuation, market data, or HTTP."""

    reconciled_facts = _reconcile_source_observations(
        raw_facts,
        semantic_extensions=semantic_extensions,
    )
    if reconciled_facts is None:
        return SecCanonicalGateResult(
            SecCanonicalGateState.BLOCKED,
            SecCanonicalReason.CANONICAL_CONFLICT,
            None,
        )
    try:
        promoted, spec = promote_sec_accounting_evidence(
            reconciled_facts,
            semantic_extensions=semantic_extensions,
        )
        snapshot = normalize_accounting_snapshot(promoted, spec=spec, tax_rate=None)
    except AccountingEvidenceGap as exc:
        reason = {
            AccountingEvidenceGapKind.MISSING_STANDARD_CONCEPT: (
                SecCanonicalReason.MISSING_STANDARD_CONCEPT
            ),
            AccountingEvidenceGapKind.STANDARD_CONCEPT_COVERAGE_GAP: (
                SecCanonicalReason.STANDARD_CONCEPT_COVERAGE_GAP
            ),
            AccountingEvidenceGapKind.REQUIRED_COMPONENT_MISSING: (
                SecCanonicalReason.REQUIRED_COMPONENT_MISSING
            ),
            AccountingEvidenceGapKind.PERIOD_COVERAGE_GAP: SecCanonicalReason.PERIOD_COVERAGE_GAP,
        }[exc.kind]
        return SecCanonicalGateResult(SecCanonicalGateState.GAP, reason, None)
    except AccountingEvidenceFailure as exc:
        reason = {
            AccountingEvidenceFailureKind.AMBIGUOUS_CONTEXT: SecCanonicalReason.AMBIGUOUS_CONTEXT,
            AccountingEvidenceFailureKind.CANONICAL_INVARIANT: (
                SecCanonicalReason.CANONICAL_INVARIANT
            ),
        }[exc.kind]
        return SecCanonicalGateResult(SecCanonicalGateState.BLOCKED, reason, None)
    except (AccountingError, TypeError, ValueError):
        return SecCanonicalGateResult(
            SecCanonicalGateState.BLOCKED,
            SecCanonicalReason.CANONICAL_INVARIANT,
            None,
        )
    return SecCanonicalGateResult(SecCanonicalGateState.READY, None, snapshot)


def _accounting_policy_surface() -> tuple[
    frozenset[tuple[str, str]],
    frozenset[str],
]:
    concepts: set[tuple[str, str]] = set()
    metrics: set[str] = set()

    def visit(policy: MetricPromotionPolicy) -> None:
        metrics.add(policy.metric_id)
        concepts.update((policy.taxonomy, concept) for concept in policy.concepts)
        for nested in policy.dependencies + policy.alternatives:
            visit(nested)

    for policy in accounting_evidence_policies():
        visit(policy)

    return frozenset(concepts), frozenset(metrics)


def _reconcile_source_observations(
    raw_facts: tuple[RawFact, ...],
    *,
    semantic_extensions: Mapping[tuple[str, str], SemanticEvidence] | None = None,
) -> tuple[RawFact, ...] | None:
    authorized_concepts, authorized_metrics = _accounting_policy_surface()
    groups: dict[tuple[object, ...], list[int]] = {}

    for index, fact in enumerate(raw_facts):
        authorized = (fact.taxonomy, fact.concept) in authorized_concepts

        if not authorized and semantic_extensions is not None:
            semantic = semantic_extensions.get((fact.taxonomy, fact.concept))
            authorized = semantic is not None and semantic.target_metric in authorized_metrics

        if not authorized:
            continue

        key = (
            fact.taxonomy,
            fact.concept,
            fact.unit,
            fact.period_kind,
            fact.start,
            fact.end,
            fact.fiscal_year,
            fact.fiscal_period,
            fact.filing_form,
            fact.accession,
            fact.filing_date,
            fact.dimensions,
            fact.consolidated,
        )
        groups.setdefault(key, []).append(index)

    discarded: set[int] = set()
    for indexes in groups.values():
        if len(indexes) == 1:
            continue
        observations = tuple(
            (
                fact.xbrl_value if fact.xbrl_value is not None else Decimal(str(fact.value)),
                fact.xbrl_decimals,
            )
            for fact in (raw_facts[index] for index in indexes)
        )
        if len({value for value, _ in observations}) == 1:
            continue
        best = _compatible_reported_amount(observations)
        if best is None:
            return None
        discarded.update(
            index for index, (value, _) in zip(indexes, observations, strict=True) if value != best
        )
    if not discarded:
        return raw_facts
    return tuple(fact for index, fact in enumerate(raw_facts) if index not in discarded)


def _compatible_reported_amount(
    observations: tuple[tuple[Decimal, XbrlDecimals | None], ...],
) -> Decimal | None:
    """Keep the most precise reported value when all observations support that point."""
    declared: dict[XbrlDecimals, Decimal] = {}
    for value, decimals in observations:
        if decimals is None:
            continue
        if declared.setdefault(decimals, value) != value:
            return None
        if isinstance(decimals, int):
            digits = value.as_tuple()
            excess_offset = int(digits.exponent) + decimals
            if excess_offset < 0 and any(digits.digits[excess_offset:]):
                return None
    if not declared:
        return None

    finest = max(
        declared,
        key=lambda decimals: (decimals == "INF", int(decimals) if decimals != "INF" else 0),
    )
    best = declared[finest]
    for value, decimals in observations:
        if value == best:
            continue
        if not isinstance(decimals, int) or not _rounding_interval_contains(value, decimals, best):
            return None
    return best


def _rounding_interval_contains(value: Decimal, decimals: int, candidate: Decimal) -> bool:
    try:
        radius = Decimal((0, (5,), -decimals - 1))
        minimum_exponent = min(int(value.as_tuple().exponent), int(candidate.as_tuple().exponent))
        with localcontext() as context:
            context.prec = max(
                context.prec, max(value.adjusted(), candidate.adjusted()) - minimum_exponent + 2
            )
            return abs(value - candidate) <= radius
    except (DecimalException, OverflowError, ValueError):
        return False
