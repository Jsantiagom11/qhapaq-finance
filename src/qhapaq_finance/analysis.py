"""Generic, offline orchestration for a single-company Qhapaq analysis."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .company_resolver import CompanyResolver, SymbolResolver
from .evidence_orchestration import EvidencePlan, EvidencePlanner
from .research_result import (
    CanonicalResearchResult,
    ResearchResultError,
    build_canonical_research_result,
)
from .universe import DomainRegistry, UniverseError


class AnalysisStatus(str, Enum):
    """Terminal or executable state for an analysis request."""

    READY = "READY"
    COMPLETED = "COMPLETED"
    UNSUPPORTED_TICKER = "UNSUPPORTED_TICKER"
    EVIDENCE_REQUIRED = "EVIDENCE_REQUIRED"
    BLOCKED = "BLOCKED"


class AnalysisStageState(str, Enum):
    """State of an intentionally separate analysis boundary."""

    NOT_REQUESTED = "NOT_REQUESTED"
    READY = "READY"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class CompanyIdentity:
    """Resolved company/security identity, or an explicit unresolved ticker."""

    ticker: str
    security_id: str | None
    issuer_id: str | None
    display_name: str | None
    exchange: str | None
    share_class: str | None
    cik: str | None
    source: dict[str, str | int | None] | None

    def to_dict(self) -> dict[str, object]:
        return {
            "ticker": self.ticker,
            "security_id": self.security_id,
            "issuer_id": self.issuer_id,
            "display_name": self.display_name,
            "exchange": self.exchange,
            "share_class": self.share_class,
            "cik": self.cik,
            "source": self.source,
        }


@dataclass(frozen=True)
class AnalysisStage:
    """One boundary in the explicit analysis lifecycle."""

    state: AnalysisStageState
    reason: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {"state": self.state.value, "reason": self.reason}


@dataclass(frozen=True)
class AnalysisPlan:
    """Pre-execution plan; it never performs acquisition or publishing."""

    schema_version: str
    status: AnalysisStatus
    identity: CompanyIdentity
    acquisition: AnalysisStage
    evidence: AnalysisStage
    research: AnalysisStage
    valuation: AnalysisStage
    publishing: AnalysisStage
    evidence_plan: EvidencePlan | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "status": self.status.value,
            "identity": self.identity.to_dict(),
            "stages": {
                "acquisition": self.acquisition.to_dict(),
                "evidence": self.evidence.to_dict(),
                "research": self.research.to_dict(),
                "valuation": self.valuation.to_dict(),
                "publishing": self.publishing.to_dict(),
            },
            "evidence_plan": self.evidence_plan.to_dict() if self.evidence_plan else None,
        }


@dataclass(frozen=True)
class AnalysisResult:
    """Structured outcome with a canonical result only when execution succeeds."""

    schema_version: str
    status: AnalysisStatus
    plan: AnalysisPlan
    canonical_result: CanonicalResearchResult | None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "status": self.status.value,
            "plan": self.plan.to_dict(),
            "canonical_result": (
                self.canonical_result.to_dict() if self.canonical_result is not None else None
            ),
        }


class AnalysisOrchestrator:
    """Coordinate existing offline research boundaries for one requested ticker."""

    def __init__(
        self,
        repository_root: str | Path = ".",
        *,
        resolver: SymbolResolver | None = None,
        evidence_planner: EvidencePlanner | None = None,
    ) -> None:
        self.root = Path(repository_root)
        self.registry = DomainRegistry(self.root)
        self.resolver = resolver or CompanyResolver(self.root)
        self.evidence_planner = evidence_planner or EvidencePlanner(self.root)

    def plan(self, ticker: str) -> AnalysisPlan:
        """Resolve identity and readiness without acquiring, valuing, or publishing."""
        normalized = ticker.strip().upper()
        resolved = self.resolver.resolve(normalized)
        if resolved is None:
            return self._blocked_plan(
                AnalysisStatus.UNSUPPORTED_TICKER,
                CompanyIdentity(normalized, None, None, None, None, None, None, None),
                "ticker cannot be resolved from the cached SEC company reference",
            )
        try:
            security = self.registry.security(normalized)
        except UniverseError:
            identity = CompanyIdentity(
                resolved.ticker,
                None,
                None,
                resolved.company_name,
                resolved.exchange,
                None,
                resolved.cik,
                resolved.provenance.to_dict(),
            )
            return self._blocked_plan(
                AnalysisStatus.EVIDENCE_REQUIRED,
                identity,
                "checksum-verified canonical evidence is not available",
                self.evidence_planner.plan(identity),
            )

        issuer = self.registry.issuer_for(security.ticker)
        identity = CompanyIdentity(
            resolved.ticker,
            security.security_id,
            security.issuer_id,
            resolved.company_name,
            resolved.exchange,
            None,
            resolved.cik,
            resolved.provenance.to_dict(),
        )
        research = self.registry.research(issuer.id)
        capability = self.registry.capability(security.ticker)
        evidence_plan = self.evidence_planner.plan(
            identity,
            trusted_path=research.get("evidence_manifest")
            if research.get("kind") == "evidence-backed"
            else None,
        )
        if research.get("kind") != "evidence-backed":
            return self._blocked_plan(
                AnalysisStatus.EVIDENCE_REQUIRED,
                identity,
                "checksum-verified canonical evidence is not available",
                evidence_plan,
            )
        if not capability.deterministic_research_ready:
            return self._blocked_plan(
                AnalysisStatus.EVIDENCE_REQUIRED,
                identity,
                "validated evidence and model requirements are not ready",
                evidence_plan,
            )
        ready = AnalysisStage(AnalysisStageState.READY)
        return AnalysisPlan(
            "analysis-plan-v1",
            AnalysisStatus.READY,
            identity,
            AnalysisStage(AnalysisStageState.NOT_REQUESTED, "automatic acquisition is disabled"),
            ready,
            ready,
            ready,
            AnalysisStage(AnalysisStageState.NOT_REQUESTED, "publishing is not requested"),
            evidence_plan,
        )

    def analyze(self, ticker: str) -> AnalysisResult:
        """Run deterministic research only when the offline plan is ready."""
        plan = self.plan(ticker)
        if plan.status is not AnalysisStatus.READY:
            return AnalysisResult("analysis-result-v1", plan.status, plan, None)
        try:
            canonical = build_canonical_research_result(plan.identity.ticker, self.root)
        except (ResearchResultError, UniverseError, ValueError, OSError):
            blocked = self._blocked_plan(
                AnalysisStatus.BLOCKED,
                plan.identity,
                "validated analysis execution could not complete",
            )
            return AnalysisResult("analysis-result-v1", AnalysisStatus.BLOCKED, blocked, None)
        completed = AnalysisPlan(
            plan.schema_version,
            AnalysisStatus.COMPLETED,
            plan.identity,
            plan.acquisition,
            AnalysisStage(AnalysisStageState.COMPLETED),
            AnalysisStage(AnalysisStageState.COMPLETED),
            AnalysisStage(AnalysisStageState.COMPLETED),
            plan.publishing,
            plan.evidence_plan,
        )
        return AnalysisResult("analysis-result-v1", AnalysisStatus.COMPLETED, completed, canonical)

    @staticmethod
    def _blocked_plan(
        status: AnalysisStatus,
        identity: CompanyIdentity,
        reason: str,
        evidence_plan: EvidencePlan | None = None,
    ) -> AnalysisPlan:
        blocked = AnalysisStage(AnalysisStageState.BLOCKED, reason)
        return AnalysisPlan(
            "analysis-plan-v1",
            status,
            identity,
            AnalysisStage(AnalysisStageState.NOT_REQUESTED, "automatic acquisition is disabled"),
            blocked,
            blocked,
            blocked,
            AnalysisStage(AnalysisStageState.NOT_REQUESTED, "publishing is not requested"),
            evidence_plan,
        )
