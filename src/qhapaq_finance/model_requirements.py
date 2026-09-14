"""Declarative model completeness checks, separate from evidence quality and valuation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .evidence import DerivedFact, FinancialFact, PeriodKind, reconstruct_ttm
from .evidence_quality import QualityReport, canonical_json
from .market_evidence import MarketQualityReport


class ModelProfileError(ValueError):
    """A model profile is malformed or unsupported."""


class RequirementStatus(str, Enum):
    SATISFIED = "SATISFIED"
    MISSING = "MISSING"
    INVALID = "INVALID"
    QUALITY_BLOCKED = "QUALITY_BLOCKED"
    OPTIONAL_UNAVAILABLE = "OPTIONAL_UNAVAILABLE"


@dataclass(frozen=True)
class ModelRequirement:
    identifier: str
    metric_id: str
    accepted_concepts: tuple[str, ...]
    unit: str
    period_kind: PeriodKind
    period: str
    mandatory: bool
    stage: str
    allowed_derivations: tuple[str, ...]


@dataclass(frozen=True)
class ModelProfile:
    schema_version: str
    profile_id: str
    version: str
    requirements: tuple[ModelRequirement, ...]
    market_requirements: tuple[MarketRequirement, ...] = ()
    capital_cost_requirement: CapitalCostRequirement | None = None


@dataclass(frozen=True)
class MarketRequirement:
    identifier: str
    metric_id: str
    unit: str
    currency: str
    stage: str
    mandatory: bool


@dataclass(frozen=True)
class CapitalCostRequirement:
    stage: str
    methodology_id: str
    risk_free_tenor: str
    erp_methodology: str
    beta_methodologies: tuple[str, ...]
    debt_semantics: tuple[str, ...]
    tax_semantics: tuple[str, ...]
    max_age_days: int


@dataclass(frozen=True)
class RequirementResult:
    requirement_id: str
    metric_id: str
    status: RequirementStatus
    fact_id: str | None = None
    derivation_id: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class ModelReadinessReport:
    schema_version: str
    profile_id: str
    profile_version: str
    quality_ready: bool
    requirements: tuple[RequirementResult, ...]
    mandatory_requirement_ids: frozenset[str]
    content_identity: str

    @property
    def model_ready(self) -> bool:
        return not any(
            item.status is not RequirementStatus.SATISFIED
            and item.requirement_id in self.mandatory_requirement_ids
            for item in self.requirements
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "quality_ready": self.quality_ready,
            "requirements": [
                {
                    "requirement_id": item.requirement_id,
                    "metric_id": item.metric_id,
                    "status": item.status.value,
                    "fact_id": item.fact_id,
                    "derivation_id": item.derivation_id,
                    "detail": item.detail,
                }
                for item in self.requirements
            ],
            "satisfied_requirements": [
                item.requirement_id
                for item in self.requirements
                if item.status is RequirementStatus.SATISFIED
            ],
            "missing_requirements": [
                item.requirement_id
                for item in self.requirements
                if item.status is RequirementStatus.MISSING
            ],
            "invalid_requirements": [
                item.requirement_id
                for item in self.requirements
                if item.status is RequirementStatus.INVALID
            ],
            "quality_blocked_requirements": [
                item.requirement_id
                for item in self.requirements
                if item.status is RequirementStatus.QUALITY_BLOCKED
            ],
            "derived_requirements": [
                item.requirement_id for item in self.requirements if item.derivation_id
            ],
            "optional_unavailable_requirements": [
                item.requirement_id
                for item in self.requirements
                if item.status is RequirementStatus.OPTIONAL_UNAVAILABLE
            ],
            "model_ready": self.model_ready,
            "content_identity": self.content_identity,
        }


@dataclass(frozen=True)
class MarketStageReadiness:
    stage: str
    requirements: tuple[RequirementResult, ...]

    @property
    def ready(self) -> bool:
        return all(item.status is RequirementStatus.SATISFIED for item in self.requirements)


def load_model_profile(path: str | Path) -> ModelProfile:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if raw.get("schema_version") != "financial-model-profile-v1":
            raise ModelProfileError("unsupported model profile schema")
        profile_id, version = raw["profile_id"], raw["version"]
        if (
            not isinstance(profile_id, str)
            or not profile_id
            or not isinstance(version, str)
            or not version
        ):
            raise ModelProfileError("model profile requires id and version")
        requirements: list[ModelRequirement] = []
        for item in raw["requirements"]:
            if not isinstance(item, dict):
                raise ModelProfileError("invalid model requirement")
            allowed = item.get("allowed_derivations", [])
            concepts = item["accepted_concepts"]
            if not isinstance(concepts, list) or not isinstance(allowed, list):
                raise ModelProfileError("invalid model requirement")
            if item["period"] not in {"TTM", "LATEST_INSTANT", "LATEST_ANNUAL"}:
                raise ModelProfileError("unsupported requirement period")
            requirement = ModelRequirement(
                item["id"],
                item["metric_id"],
                tuple(concepts),
                item["unit"],
                PeriodKind(item["period_kind"]),
                item["period"],
                item["mandatory"],
                item["stage"],
                tuple(allowed),
            )
            if (
                not isinstance(requirement.identifier, str)
                or not requirement.identifier
                or not isinstance(requirement.metric_id, str)
                or not requirement.metric_id
                or not isinstance(requirement.unit, str)
                or not requirement.unit
                or not isinstance(requirement.stage, str)
                or not requirement.stage
                or not requirement.accepted_concepts
                or not all(isinstance(x, str) and x for x in requirement.accepted_concepts)
                or not isinstance(requirement.mandatory, bool)
                or any(x != "ttm_reconstruction" for x in allowed)
            ):
                raise ModelProfileError("invalid model requirement")
            requirements.append(requirement)
        market_requirements: list[MarketRequirement] = []
        for market_item in raw.get("market_requirements", []):
            if not isinstance(market_item, dict):
                raise ModelProfileError("invalid market requirement")
            market_requirement = MarketRequirement(
                market_item["id"],
                market_item["metric_id"],
                market_item["unit"],
                market_item["currency"],
                market_item["stage"],
                market_item["mandatory"],
            )
            if not all(
                isinstance(value, str) and value
                for value in (
                    market_requirement.identifier,
                    market_requirement.metric_id,
                    market_requirement.unit,
                    market_requirement.currency,
                    market_requirement.stage,
                )
            ) or not isinstance(market_requirement.mandatory, bool):
                raise ModelProfileError("invalid market requirement")
            market_requirements.append(market_requirement)
        capital_cost_requirement = None
        capital_raw = raw.get("capital_cost_requirement")
        if capital_raw is not None:
            if not isinstance(capital_raw, dict):
                raise ModelProfileError("invalid capital-cost requirement")
            capital_cost_requirement = CapitalCostRequirement(
                capital_raw["stage"],
                capital_raw["methodology_id"],
                capital_raw["risk_free_tenor"],
                capital_raw["erp_methodology"],
                tuple(capital_raw["beta_methodologies"]),
                tuple(capital_raw["debt_semantics"]),
                tuple(capital_raw["tax_semantics"]),
                capital_raw["max_age_days"],
            )
            if (
                not all(
                    isinstance(value, str) and value
                    for value in (
                        capital_cost_requirement.stage,
                        capital_cost_requirement.methodology_id,
                        capital_cost_requirement.risk_free_tenor,
                        capital_cost_requirement.erp_methodology,
                    )
                )
                or not isinstance(capital_cost_requirement.max_age_days, int)
                or capital_cost_requirement.max_age_days < 0
                or not all(capital_cost_requirement.beta_methodologies)
                or not all(capital_cost_requirement.debt_semantics)
                or not all(capital_cost_requirement.tax_semantics)
            ):
                raise ModelProfileError("invalid capital-cost requirement")
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ModelProfileError):
            raise
        raise ModelProfileError("invalid model profile") from exc
    if not requirements or len({item.identifier for item in requirements}) != len(requirements):
        raise ModelProfileError("duplicate or missing model requirement id")
    return ModelProfile(
        "financial-model-profile-v1",
        profile_id,
        version,
        tuple(requirements),
        tuple(market_requirements),
        capital_cost_requirement,
    )


def evaluate_capital_cost_stage_readiness(
    model_profile: ModelProfile, capital_provenance: object | None
) -> MarketStageReadiness:
    """Evaluate the profile's valuation dependency without blocking FCFF stages."""
    requirement = model_profile.capital_cost_requirement
    if requirement is None:
        return MarketStageReadiness("valuation", ())
    source_mode = getattr(capital_provenance, "source_mode", None)
    methodology = getattr(capital_provenance, "methodology_id", None)
    gates = getattr(capital_provenance, "gates", ())
    valid = (
        source_mode == "canonical"
        and methodology == requirement.methodology_id
        and bool(gates)
        and all(getattr(getattr(gate, "status", None), "value", None) == "PASS" for gate in gates)
    )
    return MarketStageReadiness(
        requirement.stage,
        (
            RequirementResult(
                "validated_wacc",
                "wacc",
                RequirementStatus.SATISFIED if valid else RequirementStatus.MISSING,
                detail=None if valid else "validated canonical capital cost is unavailable",
            ),
        ),
    )


def evaluate_market_stage_readiness(
    model_profile: ModelProfile, market_report: MarketQualityReport | None, *, stage: str
) -> MarketStageReadiness:
    """Evaluate only the requested stage; intrinsic FCFF is not blocked by a quote."""
    requirements = [item for item in model_profile.market_requirements if item.stage == stage]
    facts = () if market_report is None else market_report.canonical_facts
    results: list[RequirementResult] = []
    for requirement in requirements:
        if market_report is None or not market_report.ready:
            status = (
                RequirementStatus.QUALITY_BLOCKED
                if requirement.mandatory
                else RequirementStatus.OPTIONAL_UNAVAILABLE
            )
            results.append(
                RequirementResult(
                    requirement.identifier,
                    requirement.metric_id,
                    status,
                    detail="market quality is blocking",
                )
            )
            continue
        match = next(
            (
                item
                for item in facts
                if item.normalized.metric_id == requirement.metric_id
                and item.normalized.unit == requirement.unit
                and item.normalized.currency == requirement.currency
            ),
            None,
        )
        if match:
            results.append(
                RequirementResult(
                    requirement.identifier,
                    requirement.metric_id,
                    RequirementStatus.SATISFIED,
                    fact_id=match.identifier,
                )
            )
        else:
            status = (
                RequirementStatus.MISSING
                if requirement.mandatory
                else RequirementStatus.OPTIONAL_UNAVAILABLE
            )
            results.append(RequirementResult(requirement.identifier, requirement.metric_id, status))
    return MarketStageReadiness(stage, tuple(results))


def _direct(
    requirement: ModelRequirement, facts: tuple[FinancialFact, ...]
) -> FinancialFact | None:
    candidates = [
        item
        for item in facts
        if item.concept in requirement.accepted_concepts
        and item.unit == requirement.unit
        and item.period_kind is requirement.period_kind
    ]
    if requirement.period == "LATEST_INSTANT":
        return max(candidates, key=lambda item: (item.period_end, item.id), default=None)
    if requirement.period == "LATEST_ANNUAL":
        candidates = [item for item in candidates if item.fiscal_period == "FY"]
        return max(candidates, key=lambda item: (item.period_end, item.id), default=None)
    return max(
        (item for item in candidates if item.fiscal_period == "TTM"),
        key=lambda item: (item.period_end, item.id),
        default=None,
    )


def _ttm(requirement: ModelRequirement, facts: tuple[FinancialFact, ...]) -> DerivedFact | None:
    if "ttm_reconstruction" not in requirement.allowed_derivations:
        return None
    candidates = [
        item
        for item in facts
        if item.concept in requirement.accepted_concepts
        and item.unit == requirement.unit
        and item.period_kind is PeriodKind.DURATION
    ]
    derived: list[DerivedFact] = []
    for annual in candidates:
        if annual.fiscal_period != "FY":
            continue
        for prior in candidates:
            for current in candidates:
                if (
                    prior.id == current.id
                    or prior.fiscal_period != current.fiscal_period
                    or current.period_end <= prior.period_end
                ):
                    continue
                try:
                    derived.append(
                        reconstruct_ttm(
                            annual=annual,
                            prior_ytd=prior,
                            current_ytd=current,
                            identifier=f"ttm:{requirement.identifier}:{annual.id}:{prior.id}:{current.id}",
                        )
                    )
                except ValueError:
                    continue
    return max(derived, key=lambda item: (item.period_end, item.id), default=None)


def evaluate_model_readiness(
    model_profile: ModelProfile,
    canonical_fact_set: Mapping[str, FinancialFact],
    quality_report: QualityReport,
) -> ModelReadinessReport:
    """Fail closed: quality-valid, semantically compatible canonical facts only."""
    facts = tuple(canonical_fact_set.values())
    results: list[RequirementResult] = []
    for requirement in model_profile.requirements:
        if not quality_report.research_ready:
            status = (
                RequirementStatus.QUALITY_BLOCKED
                if requirement.mandatory
                else RequirementStatus.OPTIONAL_UNAVAILABLE
            )
            results.append(
                RequirementResult(
                    requirement.identifier,
                    requirement.metric_id,
                    status,
                    detail="evidence quality is blocking",
                )
            )
            continue
        direct = _direct(requirement, facts)
        if direct:
            results.append(
                RequirementResult(
                    requirement.identifier,
                    requirement.metric_id,
                    RequirementStatus.SATISFIED,
                    fact_id=direct.id,
                )
            )
            continue
        derived = _ttm(requirement, facts) if requirement.period == "TTM" else None
        if derived:
            results.append(
                RequirementResult(
                    requirement.identifier,
                    requirement.metric_id,
                    RequirementStatus.SATISFIED,
                    fact_id=derived.id,
                    derivation_id="ttm_reconstruction",
                )
            )
            continue
        semantic = [item for item in facts if item.concept in requirement.accepted_concepts]
        if semantic:
            status = (
                RequirementStatus.INVALID
                if requirement.mandatory
                else RequirementStatus.OPTIONAL_UNAVAILABLE
            )
            results.append(
                RequirementResult(
                    requirement.identifier,
                    requirement.metric_id,
                    status,
                    detail="unit or period is incompatible",
                )
            )
        else:
            status = (
                RequirementStatus.MISSING
                if requirement.mandatory
                else RequirementStatus.OPTIONAL_UNAVAILABLE
            )
            results.append(RequirementResult(requirement.identifier, requirement.metric_id, status))
    # Optional results are excluded from readiness by retaining mandatory IDs.
    mandatory_failures = any(
        result.status is not RequirementStatus.SATISFIED and requirement.mandatory
        for result, requirement in zip(results, model_profile.requirements, strict=True)
    )
    identity_inputs = {
        "profile": {"id": model_profile.profile_id, "version": model_profile.version},
        "quality_identity": quality_report.content_identity,
        "facts": [
            {
                "id": item.id,
                "concept": item.concept,
                "value": item.value,
                "unit": item.unit,
                "period_kind": item.period_kind.value,
                "period_end": item.period_end.isoformat(),
            }
            for item in sorted(facts, key=lambda item: item.id)
        ],
        "results": [
            {
                "id": item.requirement_id,
                "status": item.status.value,
                "fact": item.fact_id,
                "derivation": item.derivation_id,
            }
            for item in results
        ],
        "mandatory_failures": mandatory_failures,
    }
    return ModelReadinessReport(
        "model-readiness-report-v1",
        model_profile.profile_id,
        model_profile.version,
        quality_report.research_ready,
        tuple(results),
        frozenset(item.identifier for item in model_profile.requirements if item.mandatory),
        hashlib.sha256(canonical_json(identity_inputs).encode()).hexdigest(),
    )
