"""Typed SEC-only gate for the existing canonical accounting boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
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
from .financial_canonicalization import RawFact, SemanticEvidence
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

    if _has_source_conflict(
        raw_facts,
        semantic_extensions=semantic_extensions,
    ):
        return SecCanonicalGateResult(
            SecCanonicalGateState.BLOCKED,
            SecCanonicalReason.CANONICAL_CONFLICT,
            None,
        )
    try:
        promoted, spec = promote_sec_accounting_evidence(
            raw_facts,
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


def _has_source_conflict(
    raw_facts: tuple[RawFact, ...],
    *,
    semantic_extensions: Mapping[tuple[str, str], SemanticEvidence] | None = None,
) -> bool:
    authorized_concepts, authorized_metrics = _accounting_policy_surface()
    values: dict[tuple[object, ...], set[float]] = {}

    for fact in raw_facts:
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
        values.setdefault(key, set()).add(fact.value)

    return any(len(observations) > 1 for observations in values.values())
