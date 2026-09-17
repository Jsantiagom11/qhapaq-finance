"""Pure, deterministic policy over canonical valuation and research evidence."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import TypeGuard

from .research_result import CanonicalResearchResult
from .valuation_result import ValuationResult


class DecisionStatus(StrEnum):
    """A review status, never an investment instruction."""

    ELIGIBLE = "ELIGIBLE"
    WATCH = "WATCH"
    REJECT = "REJECT"


@dataclass(frozen=True)
class DecisionPolicy:
    """Versioned policy thresholds over already-calculated evidence."""

    name: str = "qhapaq_core"
    version: str = "0.1"
    eligibility_threshold: float = 0.75
    valuation_weight: float = 1 / 3
    quality_weight: float = 1 / 3
    expectations_weight: float = 1 / 3
    strong_margin_of_safety: float = 0.20
    neutral_margin_of_safety: float = 0.00
    strong_roic_wacc_spread: float = 0.05
    neutral_roic_wacc_spread: float = 0.00
    favorable_expectation_growth_gap: float = 0.00
    neutral_expectation_growth_gap: float = 0.03

    def __post_init__(self) -> None:
        values = tuple(asdict(self).values())
        numeric = tuple(value for value in values if isinstance(value, (int, float)))
        if not self.name or not self.version or not all(math.isfinite(value) for value in numeric):
            raise ValueError("DECISION_POLICY_INVALID")
        weights = self.valuation_weight + self.quality_weight + self.expectations_weight
        if (
            not 0 <= self.eligibility_threshold <= 1
            or min(self.valuation_weight, self.quality_weight, self.expectations_weight) < 0
            or not math.isclose(weights, 1.0, abs_tol=1e-12)
            or self.strong_margin_of_safety < self.neutral_margin_of_safety
            or self.strong_roic_wacc_spread < self.neutral_roic_wacc_spread
            or self.favorable_expectation_growth_gap > self.neutral_expectation_growth_gap
        ):
            raise ValueError("DECISION_POLICY_INVALID")


@dataclass(frozen=True)
class DecisionInput:
    """Precomputed evidence required to make a policy classification."""

    valuation_result: ValuationResult | None
    canonical_research: CanonicalResearchResult | None


@dataclass(frozen=True)
class HardGateResult:
    name: str
    passed: bool
    reason: str
    evidence_name: str
    missing_evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "passed": self.passed,
            "reason": self.reason,
            "evidence_name": self.evidence_name,
            "missing_evidence": list(self.missing_evidence),
        }


@dataclass(frozen=True)
class DimensionScore:
    name: str
    score: float
    evidence_name: str
    evidence_value: float

    def to_dict(self) -> dict[str, float | str]:
        return asdict(self)


@dataclass(frozen=True)
class DecisionResult:
    status: DecisionStatus
    policy_name: str
    policy_version: str
    hard_gates: tuple[HardGateResult, ...]
    total_score: float | None
    dimension_scores: tuple[DimensionScore, ...]
    reasons: tuple[str, ...]
    missing_evidence: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "policy": {"name": self.policy_name, "version": self.policy_version},
            "hard_gates": [gate.to_dict() for gate in self.hard_gates],
            "score": {
                "total": self.total_score,
                "dimensions": [item.to_dict() for item in self.dimension_scores],
            },
            "reasons": list(self.reasons),
            "missing_evidence": list(self.missing_evidence),
        }


def _is_finite(value: object) -> TypeGuard[int | float]:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _input_validity(valuation: ValuationResult | None) -> HardGateResult:
    if valuation is None:
        return HardGateResult(
            "input_validity",
            False,
            "valuation result is required",
            "valuation_result",
            ("valuation_result",),
        )
    values = (
        valuation.deterministic.enterprise_value,
        valuation.deterministic.equity_value,
        valuation.deterministic.per_share_value,
        valuation.deterministic.explicit_growth,
        valuation.deterministic.terminal_growth,
        valuation.deterministic.wacc,
        valuation.reverse_dcf.implied_growth,
        valuation.reverse_dcf.target_enterprise_value,
        valuation.monte_carlo.mean_enterprise_value,
        valuation.monte_carlo.standard_deviation_enterprise_value,
        valuation.monte_carlo.p05_enterprise_value,
        valuation.monte_carlo.p50_enterprise_value,
        valuation.monte_carlo.p95_enterprise_value,
    )
    passed = all(_is_finite(value) for value in values)
    return HardGateResult(
        "input_validity",
        passed,
        "valuation evidence is finite"
        if passed
        else "valuation evidence contains non-finite values",
        "valuation_result",
    )


def _basis_validity(valuation: ValuationResult | None) -> HardGateResult:
    expected = ("FCFF", "enterprise_value", "WACC")
    actual = (
        None
        if valuation is None
        else (
            valuation.basis.cash_flow,
            valuation.basis.market_value,
            valuation.basis.discount_rate,
        )
    )
    passed = actual == expected
    return HardGateResult(
        "valuation_basis",
        passed,
        "FCFF/enterprise_value/WACC basis is required"
        if not passed
        else "FCFF/enterprise_value/WACC basis is valid",
        "valuation_result.basis",
    )


def _canonical_evidence(research: CanonicalResearchResult | None) -> HardGateResult:
    if research is None:
        return HardGateResult(
            "canonical_evidence",
            False,
            "canonical research evidence is required",
            "canonical_research",
            ("canonical_research",),
        )
    readiness = _mapping(research.readiness)
    quality = _mapping(readiness.get("financial_evidence_quality"))
    missing: list[str] = []
    if readiness.get("deterministic_research_ready") is not True:
        missing.append("deterministic_research_ready")
    if readiness.get("valuation_ready") is not True:
        missing.append("valuation_ready")
    if quality and (
        quality.get("research_ready") is not True
        or bool(quality.get("blocking_failures"))
    ):
        missing.append("financial_evidence_quality")
    passed = not missing
    return HardGateResult(
        "canonical_evidence",
        passed,
        "canonical evidence is ready" if passed else "canonical evidence is incomplete",
        "canonical_research.readiness",
        tuple(missing),
    )


def _reproducibility(valuation: ValuationResult | None) -> HardGateResult:
    if valuation is None:
        return HardGateResult(
            "valuation_reproducibility",
            False,
            "valuation result is required",
            "valuation_result",
            ("valuation_result",),
        )
    complete = valuation.monte_carlo.accepted_simulations == valuation.monte_carlo.simulations
    passed = complete
    missing = () if passed else ("monte_carlo_reproducibility",)
    return HardGateResult(
        "valuation_reproducibility",
        passed,
        "deterministic, reverse, and complete scenario valuation evidence is available"
        if passed
        else "valuation evidence is incomplete",
        "valuation_result.monte_carlo",
        missing,
    )


def _model_semantics(valuation: ValuationResult | None) -> HardGateResult:
    passed = (
        valuation is not None
        and valuation.monte_carlo.distribution_semantics == "model_scenario_distribution"
    )
    return HardGateResult(
        "model_semantics",
        passed,
        "Monte Carlo evidence is a model scenario distribution"
        if passed
        else "Monte Carlo evidence must not be presented as empirical probability",
        "valuation_result.monte_carlo.distribution_semantics",
    )


def _number(mapping: Mapping[str, object], key: str) -> float | None:
    value = mapping.get(key)
    return float(value) if _is_finite(value) else None


def _score_evidence(
    research: CanonicalResearchResult | None, policy: DecisionPolicy
) -> tuple[tuple[DimensionScore, ...], tuple[str, ...]]:
    if research is None:
        return (), ("canonical_research",)
    valuation = _mapping(research.valuation)
    scenarios = _mapping(valuation.get("scenarios"))
    base = _mapping(scenarios.get("base"))
    reverse = _mapping(research.reverse_valuation)
    margin = _number(base, "margin_of_safety")
    spread = _number(valuation, "roic_minus_wacc")
    expectation_gap = _number(reverse, "expectation_growth_gap")
    scores: list[DimensionScore] = []
    missing: list[str] = []
    if margin is None:
        missing.append("margin_of_safety")
    else:
        scores.append(
            DimensionScore(
                "margin_of_safety",
                1.0
                if margin >= policy.strong_margin_of_safety
                else 0.5
                if margin >= policy.neutral_margin_of_safety
                else 0.0,
                "canonical_research.valuation.scenarios.base.margin_of_safety",
                margin,
            )
        )
    if spread is None:
        missing.append("roic_minus_wacc")
    else:
        scores.append(
            DimensionScore(
                "roic_minus_wacc",
                1.0
                if spread >= policy.strong_roic_wacc_spread
                else 0.5
                if spread >= policy.neutral_roic_wacc_spread
                else 0.0,
                "canonical_research.valuation.roic_minus_wacc",
                spread,
            )
        )
    if expectation_gap is None:
        missing.append("expectation_growth_gap")
    else:
        scores.append(
            DimensionScore(
                "expectation_growth_gap",
                1.0
                if expectation_gap <= policy.favorable_expectation_growth_gap
                else 0.5
                if expectation_gap <= policy.neutral_expectation_growth_gap
                else 0.0,
                "canonical_research.reverse_valuation.expectation_growth_gap",
                expectation_gap,
            )
        )
    return tuple(scores), tuple(missing)


def _total_score(scores: tuple[DimensionScore, ...], policy: DecisionPolicy) -> float:
    by_name = {item.name: item.score for item in scores}
    return (
        by_name["margin_of_safety"] * policy.valuation_weight
        + by_name["roic_minus_wacc"] * policy.quality_weight
        + by_name["expectation_growth_gap"] * policy.expectations_weight
    )


def evaluate_decision(
    decision_input: DecisionInput, policy: DecisionPolicy | None = None
) -> DecisionResult:
    """Classify supplied evidence; this function never recalculates financial outputs."""
    policy = policy or DecisionPolicy()
    gates = (
        _input_validity(decision_input.valuation_result),
        _basis_validity(decision_input.valuation_result),
        _canonical_evidence(decision_input.canonical_research),
        _reproducibility(decision_input.valuation_result),
        _model_semantics(decision_input.valuation_result),
    )
    missing = tuple(item for gate in gates for item in gate.missing_evidence)
    if not all(gate.passed for gate in gates):
        return DecisionResult(
            DecisionStatus.REJECT,
            policy.name,
            policy.version,
            gates,
            None,
            (),
            ("one or more hard gates failed",),
            missing,
        )
    scores, soft_missing = _score_evidence(decision_input.canonical_research, policy)
    if soft_missing:
        return DecisionResult(
            DecisionStatus.WATCH,
            policy.name,
            policy.version,
            gates,
            None,
            scores,
            ("all hard gates passed", "soft evidence is incomplete"),
            soft_missing,
        )
    total = _total_score(scores, policy)
    status = (
        DecisionStatus.ELIGIBLE
        if total >= policy.eligibility_threshold
        else DecisionStatus.WATCH
    )
    reason = (
        "all hard gates passed and eligibility threshold was met"
        if status is DecisionStatus.ELIGIBLE
        else "all hard gates passed but eligibility threshold was not met"
    )
    return DecisionResult(
        status,
        policy.name,
        policy.version,
        gates,
        total,
        scores,
        ("all hard gates passed", reason),
        (),
    )
