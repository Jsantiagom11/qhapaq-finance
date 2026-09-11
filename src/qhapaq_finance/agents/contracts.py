"""Strict, provider-independent contracts for the agent research layer."""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class Confidence(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class EvidenceKind(str, Enum):
    DETERMINISTIC_ARTIFACT = "DETERMINISTIC_ARTIFACT"
    INTERPRETATION_SIGNAL = "INTERPRETATION_SIGNAL"


class NumericUnit(str, Enum):
    USD_PER_SHARE = "USD_PER_SHARE"
    RATIO = "RATIO"
    PERCENTAGE_POINT = "PERCENTAGE_POINT"


# These names define the qualitative portions of the provider-independent contracts.
# Providers may derive output constraints from them, but contract validation remains final.
RESEARCH_SYNTHESIS_QUALITATIVE_TEXT_FIELDS = ("assessment", "thesis")
RESEARCH_SYNTHESIS_QUALITATIVE_ITEMS_FIELDS = (
    "positive_evidence",
    "negative_evidence",
    "critical_assumptions",
    "invalidation_conditions",
    "open_questions",
)
THESIS_CHALLENGE_QUALITATIVE_ITEMS_FIELDS = (
    "challenges",
    "fragile_assumptions",
    "missing_evidence",
    "potential_confirmation_bias",
)


@dataclass(frozen=True)
class EvidenceRef:
    """A stable path into a deterministic input or interpretation signal."""

    path: str
    kind: EvidenceKind

    def __post_init__(self) -> None:
        _text(self.path, "evidence_ref.path")
        if not isinstance(self.kind, EvidenceKind):
            raise ValueError("evidence_ref.kind must be an EvidenceKind")


@dataclass(frozen=True)
class NumericClaim:
    """A number an agent intends to present, separately from qualitative prose."""

    label: str
    value: float
    unit: NumericUnit
    evidence_ref: EvidenceRef

    def __post_init__(self) -> None:
        _text(self.label, "numeric_claim.label")
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise ValueError("numeric_claim.value must be numeric")
        if not math.isfinite(float(self.value)):
            raise ValueError("numeric_claim.value must be finite")
        if not isinstance(self.unit, NumericUnit):
            raise ValueError("numeric_claim.unit must be a NumericUnit")
        if not isinstance(self.evidence_ref, EvidenceRef):
            raise ValueError("numeric_claim.evidence_ref must be an EvidenceRef")


def _text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _items(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    if not isinstance(values, tuple) or not values:
        raise ValueError(f"{field} must be a non-empty tuple")
    checked = tuple(_text(item, field) for item in values)
    if any(re.search(r"\d", item) for item in checked):
        raise ValueError(f"{field} must put numerical claims in numeric_claims")
    return checked


def _qualitative(value: str, field: str) -> str:
    checked = _text(value, field)
    if re.search(r"\d", checked):
        raise ValueError(f"{field} must put numerical claims in numeric_claims")
    return checked


@dataclass(frozen=True)
class ResearchSynthesis:
    ticker: str
    assessment: str
    confidence: Confidence
    thesis: str
    positive_evidence: tuple[str, ...]
    negative_evidence: tuple[str, ...]
    critical_assumptions: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    open_questions: tuple[str, ...]
    evidence_refs: tuple[EvidenceRef, ...]
    numeric_claims: tuple[NumericClaim, ...] = ()

    def __post_init__(self) -> None:
        _text(self.ticker, "ticker")
        if not isinstance(self.confidence, Confidence):
            raise ValueError("confidence must be a Confidence")
        for field in RESEARCH_SYNTHESIS_QUALITATIVE_TEXT_FIELDS:
            _qualitative(getattr(self, field), field)
        for field in RESEARCH_SYNTHESIS_QUALITATIVE_ITEMS_FIELDS:
            _items(getattr(self, field), field)
        _evidence_refs(self.evidence_refs)
        _numeric_claims(self.numeric_claims)


@dataclass(frozen=True)
class ThesisChallenge:
    challenges: tuple[str, ...]
    fragile_assumptions: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    potential_confirmation_bias: tuple[str, ...]
    evidence_refs: tuple[EvidenceRef, ...]
    numeric_claims: tuple[NumericClaim, ...] = ()

    def __post_init__(self) -> None:
        for field in THESIS_CHALLENGE_QUALITATIVE_ITEMS_FIELDS:
            _items(getattr(self, field), field)
        _evidence_refs(self.evidence_refs)
        _numeric_claims(self.numeric_claims)


def _evidence_refs(values: tuple[EvidenceRef, ...]) -> None:
    if not isinstance(values, tuple) or not values:
        raise ValueError("evidence_refs must be a non-empty tuple")
    if any(not isinstance(item, EvidenceRef) for item in values):
        raise ValueError("evidence_refs must contain EvidenceRef values")


def _numeric_claims(values: tuple[NumericClaim, ...]) -> None:
    if not isinstance(values, tuple) or any(not isinstance(item, NumericClaim) for item in values):
        raise ValueError("numeric_claims must be a tuple of NumericClaim values")


def contract_dict(value: ResearchSynthesis | ThesisChallenge) -> dict[str, Any]:
    """Return JSON-native data while retaining dataclass contracts in the domain."""
    return asdict(value)
