"""Deterministic numerical-claim firewall for provider-produced contracts."""
# ruff: noqa: E501

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contracts import (
    EvidenceKind,
    NumericUnit,
    ResearchSynthesis,
    ThesisChallenge,
)
from .interpretation import DeterministicInterpretation


@dataclass(frozen=True)
class ValidationFailure:
    label: str
    reason: str
    evidence_path: str


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    failures: tuple[ValidationFailure, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "failures": [
                {"label": item.label, "reason": item.reason, "evidence_path": item.evidence_path}
                for item in self.failures
            ],
        }


class NumericalClaimValidator:
    """Allow only explicitly referenced deterministic numbers and compatible units.

    Ratios are decimal values (0.10 means ten percent); percentage points are whole
    points (10.0 means ten percentage points). This prevents silent unit mixing.
    """

    price_tolerance: float = 0.01
    ratio_tolerance: float = 1e-9

    def validate(
        self,
        content: ResearchSynthesis | ThesisChallenge,
        artifact: dict[str, Any],
        interpretation: DeterministicInterpretation,
    ) -> ValidationResult:
        allowed = self._allowed(artifact, interpretation)
        failures: list[ValidationFailure] = []
        for evidence_ref in content.evidence_refs:
            if (evidence_ref.kind, evidence_ref.path) not in allowed:
                failures.append(
                    ValidationFailure(
                        "evidence reference",
                        "unknown evidence reference",
                        evidence_ref.path,
                    )
                )
        for claim in content.numeric_claims:
            key = (claim.evidence_ref.kind, claim.evidence_ref.path)
            expected = allowed.get(key)
            if expected is None:
                failures.append(
                    ValidationFailure(
                        claim.label, "unknown evidence reference", claim.evidence_ref.path
                    )
                )
                continue
            expected_value, expected_unit, expected_label = expected
            if claim.unit != expected_unit:
                failures.append(
                    ValidationFailure(
                        claim.label, "unit does not match referenced value", claim.evidence_ref.path
                    )
                )
                continue
            if claim.label != expected_label:
                failures.append(
                    ValidationFailure(
                        claim.label,
                        "label does not match referenced metric",
                        claim.evidence_ref.path,
                    )
                )
                continue
            tolerance = (
                self.price_tolerance
                if claim.unit == NumericUnit.USD_PER_SHARE
                else self.ratio_tolerance
            )
            if abs(claim.value - expected_value) > tolerance:
                failures.append(
                    ValidationFailure(
                        claim.label,
                        "value does not match deterministic evidence",
                        claim.evidence_ref.path,
                    )
                )
        return ValidationResult(valid=not failures, failures=tuple(failures))

    def _allowed(
        self, artifact: dict[str, Any], interpretation: DeterministicInterpretation
    ) -> dict[tuple[EvidenceKind, str], tuple[float, NumericUnit, str]]:
        deterministic = EvidenceKind.DETERMINISTIC_ARTIFACT
        signal = EvidenceKind.INTERPRETATION_SIGNAL
        return {
            (deterministic, "market.price"): (
                float(artifact["market"]["price"]),
                NumericUnit.USD_PER_SHARE,
                "Market price",
            ),
            (deterministic, "valuation.scenarios.base.intrinsic_value"): (
                float(artifact["valuation"]["scenarios"]["base"]["intrinsic_value"]),
                NumericUnit.USD_PER_SHARE,
                "Base intrinsic value",
            ),
            (deterministic, "valuation.scenarios.base.margin_of_safety"): (
                float(artifact["valuation"]["scenarios"]["base"]["margin_of_safety"]),
                NumericUnit.RATIO,
                "Base margin of safety",
            ),
            (deterministic, "valuation.scenarios.base.terminal_value_share"): (
                float(artifact["valuation"]["scenarios"]["base"]["terminal_value_share"]),
                NumericUnit.RATIO,
                "Base terminal value share",
            ),
            (deterministic, "economics.roic_minus_wacc"): (
                float(artifact["economics"]["roic_minus_wacc"]),
                NumericUnit.RATIO,
                "ROIC minus WACC",
            ),
            (deterministic, "valuation.expectations.growth_difference_pp"): (
                float(artifact["valuation"]["expectations"]["growth_difference_pp"]) * 100,
                NumericUnit.PERCENTAGE_POINT,
                "Growth difference",
            ),
            (signal, "price_fair_value_distance"): (
                interpretation.price_fair_value_distance,
                NumericUnit.RATIO,
                "Price-to-fair-value distance",
            ),
            (signal, "market_implied_growth_gap_pp"): (
                interpretation.market_implied_growth_gap_pp * 100,
                NumericUnit.PERCENTAGE_POINT,
                "Market-implied growth gap",
            ),
            (signal, "roic_wacc_spread"): (
                interpretation.roic_wacc_spread,
                NumericUnit.RATIO,
                "ROIC-WACC spread",
            ),
        }
