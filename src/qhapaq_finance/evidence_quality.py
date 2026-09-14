"""Deterministic, offline evidence-quality contract.

This module is deliberately independent of valuation cases.  It validates source
provenance and fact semantics before a case (or an agent) may treat evidence as
research-ready.  It never acquires data and never changes a source artifact.
"""

# ruff: noqa: E501
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any

from .evidence import FinancialFact, PeriodKind, load_facts, reconstruct_ttm


class EvidenceQualityError(ValueError):
    """A versioned evidence or quality contract is invalid."""


class GateStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class ExtractedFact:
    """A parser result, still in the source's own scale and vocabulary."""

    id: str
    issuer_id: str
    metric_label: str
    source_concept: str | None
    raw_value: float
    unit: str
    currency: str | None
    period_kind: PeriodKind
    period_start: date | None
    period_end: date
    fiscal_year: int | None
    fiscal_period: str | None
    source_id: str
    context_id: str | None
    provenance_ref: str


@dataclass(frozen=True)
class NormalizedFact:
    """A deterministic vocabulary/scale mapping, not yet an accepted value."""

    extracted: ExtractedFact
    metric_id: str
    normalized_value: float
    normalized_unit: str
    transformation_id: str


@dataclass(frozen=True)
class CanonicalFinancialFact:
    """An accepted fact with full backwards lineage; values are never agent-written."""

    id: str
    normalized: NormalizedFact
    canonical_source_id: str
    accepted_by: str
    data_domain: str = "regulatory_financial_statement"


def normalize_scale(
    fact: ExtractedFact, *, multiplier: float, normalized_unit: str, transformation_id: str
) -> NormalizedFact:
    if (
        not math.isfinite(multiplier)
        or multiplier <= 0
        or not normalized_unit
        or not transformation_id
    ):
        raise EvidenceQualityError("QUALITY_UNIT_AMBIGUOUS")
    if not math.isfinite(fact.raw_value):
        raise EvidenceQualityError("QUALITY_UNIT_AMBIGUOUS")
    return NormalizedFact(
        fact,
        fact.source_concept or fact.metric_label,
        fact.raw_value * multiplier,
        normalized_unit,
        transformation_id,
    )


def resolve_authoritative_fact(
    candidates: tuple[CanonicalFinancialFact, ...],
    *,
    data_domain: str,
    authority_policy: dict[str, dict[str, int]],
) -> CanonicalFinancialFact:
    """Resolve facts under a declared domain policy, never a universal source ranking."""
    if not candidates:
        raise EvidenceQualityError("QUALITY_REQUIRED_FACT_MISSING")
    if data_domain not in authority_policy:
        raise EvidenceQualityError("QUALITY_AUTHORITY_POLICY_MISSING")
    if any(item.data_domain != data_domain for item in candidates):
        raise EvidenceQualityError("QUALITY_DOMAIN_MISMATCH")
    ranks = authority_policy[data_domain]
    ranked = sorted(
        candidates,
        key=lambda item: (ranks.get(item.canonical_source_id, -1), item.id),
        reverse=True,
    )
    highest = ranks.get(ranked[0].canonical_source_id, -1)
    winners = [item for item in ranked if ranks.get(item.canonical_source_id, -1) == highest]
    values = {item.normalized.normalized_value for item in winners}
    if len(values) != 1:
        raise EvidenceQualityError("QUALITY_SOURCE_CONFLICT")
    return winners[0]


@dataclass(frozen=True)
class SourceManifest:
    schema_version: str
    issuer_id: str
    source_id: str
    source_type: str
    authority: str
    document_type: str | None
    accession_number: str | None
    publication_date: date | None
    raw_artifact: Path
    raw_artifact_sha256: str
    parser_version: str | None
    supersedes: str | None
    provenance_status: str


@dataclass(frozen=True)
class Gate:
    identifier: str
    status: GateStatus
    blocking: bool
    failures: tuple[str, ...] = ()
    references: tuple[str, ...] = ()


@dataclass(frozen=True)
class QualityReport:
    schema_version: str
    issuer_id: str
    evidence_set_id: str
    gates: tuple[Gate, ...]
    canonical_fact_count: int
    missing_required_facts: tuple[str, ...]
    content_identity: str = ""

    @property
    def blocking_failures(self) -> tuple[Gate, ...]:
        return tuple(
            gate for gate in self.gates if gate.blocking and gate.status is GateStatus.FAIL
        )

    @property
    def research_ready(self) -> bool:
        return not self.blocking_failures and not self.missing_required_facts

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "issuer_id": self.issuer_id,
            "evidence_set_id": self.evidence_set_id,
            "gates": [
                {
                    "id": item.identifier,
                    "status": item.status.value,
                    "blocking": item.blocking,
                    "failures": list(item.failures),
                    "references": list(item.references),
                }
                for item in self.gates
            ],
            "blocking_failures": [item.identifier for item in self.blocking_failures],
            "canonical_fact_count": self.canonical_fact_count,
            "missing_required_facts": list(self.missing_required_facts),
            "content_identity": self.content_identity,
            "research_ready": self.research_ready,
        }


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_identity(value: object) -> str:
    """Stable identity for deterministic inputs or canonical artifacts; no clock is involved."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _text(raw: Any, name: str, *, optional: bool = False) -> str | None:
    if raw is None and optional:
        return None
    if not isinstance(raw, str) or not raw.strip():
        raise EvidenceQualityError(f"manifest {name} must be a non-empty string")
    return raw.strip()


def load_source_manifest(path: str | Path, root: str | Path = ".") -> SourceManifest:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceQualityError("QUALITY_MANIFEST_INVALID") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != "source-manifest-v1":
        raise EvidenceQualityError("QUALITY_MANIFEST_INVALID")
    relative = _text(raw.get("raw_artifact"), "raw_artifact")
    assert relative is not None
    artifact = Path(root).resolve() / relative
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise EvidenceQualityError("QUALITY_MANIFEST_INVALID")
    publication = raw.get("publication_date")
    try:
        publication_date = date.fromisoformat(publication) if publication else None
    except (TypeError, ValueError) as exc:
        raise EvidenceQualityError("QUALITY_MANIFEST_INVALID") from exc
    return SourceManifest(
        "source-manifest-v1",
        _text(raw.get("issuer_id"), "issuer_id") or "",
        _text(raw.get("source_id"), "source_id") or "",
        _text(raw.get("source_type"), "source_type") or "",
        _text(raw.get("authority"), "authority") or "",
        _text(raw.get("document_type"), "document_type", optional=True),
        _text(raw.get("accession_number"), "accession_number", optional=True),
        publication_date,
        artifact,
        _text(raw.get("raw_artifact_sha256"), "raw_artifact_sha256") or "",
        _text(raw.get("parser_version"), "parser_version", optional=True),
        _text(raw.get("supersedes"), "supersedes", optional=True),
        _text(raw.get("provenance_status"), "provenance_status") or "",
    )


def verify_source_integrity(manifest: SourceManifest) -> None:
    if not manifest.raw_artifact.is_file():
        raise EvidenceQualityError("QUALITY_SOURCE_MISSING")
    observed = hashlib.sha256(manifest.raw_artifact.read_bytes()).hexdigest()
    if observed != manifest.raw_artifact_sha256:
        raise EvidenceQualityError("QUALITY_HASH_MISMATCH")


def _verified_source_ids(manifests: tuple[SourceManifest, ...]) -> tuple[str, ...]:
    for manifest in manifests:
        verify_source_integrity(manifest)
    return tuple(manifest.source_id for manifest in manifests)


def resolve_effective_sources(manifests: tuple[SourceManifest, ...]) -> tuple[SourceManifest, ...]:
    """Keep audit history, selecting only sources not superseded by another source."""
    ids = {item.source_id for item in manifests}
    if len(ids) != len(manifests) or any(
        item.supersedes and item.supersedes not in ids for item in manifests
    ):
        raise EvidenceQualityError("QUALITY_SUPERSESSION_INVALID")
    superseded = {item.supersedes for item in manifests if item.supersedes}
    return tuple(item for item in manifests if item.source_id not in superseded)


def _gate(identifier: str, fn: Any, *, blocking: bool = True) -> Gate:
    try:
        references = tuple(fn() or ())
        return Gate(identifier, GateStatus.PASS, blocking, references=references)
    except EvidenceQualityError as exc:
        return Gate(identifier, GateStatus.FAIL, blocking, (str(exc),))
    except (KeyError, ValueError, TypeError) as exc:
        return Gate(
            identifier, GateStatus.FAIL, blocking, (f"QUALITY_{identifier.upper()}_INVALID: {exc}",)
        )


def _period_check(facts: dict[str, FinancialFact]) -> tuple[str, ...]:
    for item in facts.values():
        if item.period_kind is PeriodKind.DURATION and item.period_start is None:
            raise EvidenceQualityError("QUALITY_PERIOD_MISMATCH")
        if item.period_kind is PeriodKind.INSTANT and item.period_start is not None:
            raise EvidenceQualityError("QUALITY_PERIOD_MISMATCH")
    return tuple(facts)


def _unit_check(facts: dict[str, FinancialFact]) -> tuple[str, ...]:
    for item in facts.values():
        if not item.unit or not math.isfinite(item.value):
            raise EvidenceQualityError("QUALITY_UNIT_AMBIGUOUS")
    return tuple(facts)


def _ttm_check(facts: dict[str, FinancialFact], contracts: list[dict[str, Any]]) -> tuple[str, ...]:
    checked: list[str] = []
    for item in contracts:
        try:
            annual, prior, current = (
                facts[item[key]] for key in ("annual", "prior_ytd", "current_ytd")
            )
            if len({annual.concept, prior.concept, current.concept}) != 1:
                raise EvidenceQualityError("QUALITY_TTM_CONCEPT_MISMATCH")
            reconstruct_ttm(
                annual=annual, prior_ytd=prior, current_ytd=current, identifier=item["id"]
            )
            checked.append(item["id"])
        except KeyError as exc:
            raise EvidenceQualityError(f"QUALITY_TTM_COMPONENT_MISSING: {exc.args[0]}") from exc
    return tuple(checked)


def _reconcile(facts: dict[str, FinancialFact], checks: list[dict[str, Any]]) -> tuple[str, ...]:
    checked: list[str] = []
    for check in checks:
        left = sum(facts[identifier].value for identifier in check["left"])
        right = sum(facts[identifier].value for identifier in check["right"])
        units = {facts[identifier].unit for identifier in check["left"] + check["right"]}
        if len(units) != 1:
            raise EvidenceQualityError("QUALITY_RECONCILIATION_UNIT_MISMATCH")
        tolerance = float(check.get("absolute_tolerance", 0.0))
        if abs(left - right) > tolerance:
            raise EvidenceQualityError(f"QUALITY_RECONCILIATION_FAILED: {check['id']}")
        checked.append(check["id"])
    return tuple(checked)


def _golden_check(facts: dict[str, FinancialFact], golden: list[dict[str, Any]]) -> tuple[str, ...]:
    """Regression assertions are data records, never issuer conditionals."""
    checked: list[str] = []
    for item in golden:
        fact = facts[item["fact_id"]]
        if (
            fact.concept != item["concept"]
            or fact.unit != item["unit"]
            or fact.period_end.isoformat() != item["period_end"]
        ):
            raise EvidenceQualityError(f"QUALITY_GOLDEN_FACT_MISMATCH: {item['fact_id']}")
        if fact.value != float(item["value"]):
            raise EvidenceQualityError(f"QUALITY_GOLDEN_FACT_MISMATCH: {item['fact_id']}")
        checked.append(item["fact_id"])
    return tuple(checked)


def evaluate_quality(profile_path: str | Path, root: str | Path = ".") -> QualityReport:
    """Evaluate declarative requirements; malformed or unavailable evidence fails closed."""
    base = Path(root).resolve()
    try:
        profile = json.loads(Path(profile_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceQualityError("QUALITY_PROFILE_INVALID") from exc
    if profile.get("schema_version") != "evidence-quality-profile-v1":
        raise EvidenceQualityError("QUALITY_PROFILE_INVALID")
    issuer_id = _text(profile.get("issuer_id"), "issuer_id") or ""
    source_paths = profile.get("source_manifests")
    if not isinstance(source_paths, list) or not source_paths:
        raise EvidenceQualityError("QUALITY_PROFILE_INVALID")
    manifests = tuple(load_source_manifest(base / value, base) for value in source_paths)
    if any(item.issuer_id != issuer_id for item in manifests):
        raise EvidenceQualityError("QUALITY_PROVENANCE_ISSUER_MISMATCH")
    evidence_path = base / (_text(profile.get("financial_evidence"), "financial_evidence") or "")
    as_of = date.fromisoformat(_text(profile.get("as_of"), "as_of") or "")
    facts: dict[str, FinancialFact] = {}
    loading_error: EvidenceQualityError | None = None
    try:
        facts = load_facts(evidence_path, base, as_of=as_of)
    except Exception as exc:  # legacy loader is the immutable raw-artifact gate
        loading_error = EvidenceQualityError(f"QUALITY_NORMALIZATION_INVALID: {exc}")
    required = tuple(profile.get("required_facts", []))
    missing = tuple(identifier for identifier in required if identifier not in facts)
    gates = [
        _gate("provenance", lambda: tuple(item.source_id for item in manifests)),
        _gate("source_integrity", lambda: _verified_source_ids(manifests)),
        _gate(
            "effective_source_selection",
            lambda: tuple(item.source_id for item in resolve_effective_sources(manifests)),
        ),
    ]
    if loading_error:
        gates.extend(
            Gate(name, GateStatus.FAIL, True, (str(loading_error),))
            for name in (
                "normalization",
                "period_semantics",
                "unit_semantics",
                "ttm_compatibility",
                "reconciliation",
            )
        )
    else:
        gates.extend(
            (
                Gate("normalization", GateStatus.PASS, True, references=tuple(facts)),
                _gate("period_semantics", lambda: _period_check(facts)),
                _gate("unit_semantics", lambda: _unit_check(facts)),
                _gate(
                    "ttm_compatibility", lambda: _ttm_check(facts, profile.get("ttm_contracts", []))
                ),
                (
                    _gate("reconciliation", lambda: _reconcile(facts, profile["reconciliations"]))
                    if profile.get("reconciliations")
                    else Gate("reconciliation", GateStatus.NOT_APPLICABLE, False)
                ),
                (
                    _gate("golden_facts", lambda: _golden_check(facts, profile["golden_facts"]))
                    if profile.get("golden_facts")
                    # Golden facts are optional, but a declared regression invariant blocks.
                    else Gate("golden_facts", GateStatus.NOT_APPLICABLE, False)
                ),
            )
        )
    reproducibility_inputs = {
        "quality_profile": profile,
        "source_manifests": [
            {
                "source_id": item.source_id,
                "raw_artifact_sha256": item.raw_artifact_sha256,
                "source_type": item.source_type,
                "parser_version": item.parser_version,
            }
            for item in manifests
        ],
        "canonical_facts": [
            {
                "id": item.id,
                "concept": item.concept,
                "value": item.value,
                "unit": item.unit,
                "period_kind": item.period_kind.value,
                "period_start": item.period_start.isoformat() if item.period_start else None,
                "period_end": item.period_end.isoformat(),
                "fiscal_period": item.fiscal_period,
                "filing_sha256": item.filing.sha256,
                "method": item.method,
            }
            for item in sorted(facts.values(), key=lambda item: item.id)
        ],
    }
    identity = content_identity(reproducibility_inputs)
    gates.append(
        Gate(
            "critical_fact_completeness",
            GateStatus.PASS if not missing else GateStatus.FAIL,
            True,
            ()
            if not missing
            else tuple(f"QUALITY_REQUIRED_FACT_MISSING: {item}" for item in missing),
            missing,
        )
    )
    gates.append(
        Gate(
            "reproducibility",
            GateStatus.PASS,
            True,
            references=(identity,),
        )
    )
    return QualityReport(
        "quality-report-v1",
        issuer_id,
        _text(profile.get("evidence_set_id"), "evidence_set_id") or "",
        tuple(gates),
        len(facts),
        missing,
        identity,
    )


def explain_fact(
    profile_path: str | Path, fact_id: str, root: str | Path = "."
) -> dict[str, object]:
    """Return machine-readable lineage from a normalized fact to its immutable artifact."""
    base = Path(root).resolve()
    profile = json.loads(Path(profile_path).read_text(encoding="utf-8"))
    facts = load_facts(
        base / profile["financial_evidence"], base, as_of=date.fromisoformat(profile["as_of"])
    )
    fact = facts[fact_id]
    return {
        "fact_id": fact.id,
        "metric": fact.concept,
        "value": fact.value,
        "unit": fact.unit,
        "period_kind": fact.period_kind.value,
        "period_start": str(fact.period_start) if fact.period_start else None,
        "period_end": str(fact.period_end),
        "source_id": fact.filing.accession_number,
        "source_context": fact.locator,
        "transformation": fact.method,
        "raw_artifact": str(fact.filing.local_path.relative_to(base)),
        "raw_artifact_sha256": fact.filing.sha256,
    }
