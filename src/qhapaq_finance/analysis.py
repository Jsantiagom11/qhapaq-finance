"""Generic, offline orchestration for a single-company Qhapaq analysis."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path

from .accounting import AccountingSnapshot
from .capital_cost import CapitalCostResult
from .company_resolver import (
    CompanyResolver,
    RefreshableSymbolResolver,
    ResolvedCompany,
    SymbolResolver,
)
from .evidence_orchestration import EvidencePlan, EvidencePlanner, EvidenceState
from .financial_canonicalization import RawFact, extract_company_facts
from .market_inputs import MarketInput, MarketInputError, canonical_market_input
from .research_result import (
    CanonicalResearchResult,
    ResearchResultError,
    build_canonical_research_result,
)
from .sec_canonical_gate import (
    SecCanonicalGateState,
    SecCanonicalReason,
    evaluate_sec_canonical_gate,
)
from .sec_client import SecClient
from .sec_config import SecConfig
from .sec_corpus import export_sec_filing
from .sec_evidence_provider import (
    SecFilingDescriptor,
    SecSubmissionsBundle,
    StructuredSecProvider,
)
from .sec_filing_plan import FilingRequirementContext, plan_filing_fallback
from .sec_filing_xbrl import (
    FilingArtifact,
    VerifiedFilingArtifacts,
    parse_filing_native_evidence,
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


class AnalysisProgressKind(str, Enum):
    """Presentation-neutral milestones emitted by analysis orchestration."""

    RESOLUTION_STARTED = "RESOLUTION_STARTED"
    FAST_PATH_ACQUISITION_STARTED = "FAST_PATH_ACQUISITION_STARTED"
    FAST_PATH_ACQUISITION_COMPLETED = "FAST_PATH_ACQUISITION_COMPLETED"
    CANONICAL_GATE_READY = "CANONICAL_GATE_READY"
    CANONICAL_GATE_GAP = "CANONICAL_GATE_GAP"
    FILING_FALLBACK_STARTED = "FILING_FALLBACK_STARTED"
    FILING_FALLBACK_COMPLETED = "FILING_FALLBACK_COMPLETED"
    CANONICALIZATION_COMPLETED = "CANONICALIZATION_COMPLETED"


@dataclass(frozen=True)
class AnalysisProgressEvent:
    """One typed orchestration milestone with optional stable detail."""

    kind: AnalysisProgressKind
    detail: str | None = None


@dataclass(frozen=True)
class _SecRecoveryResult:
    status: AnalysisStatus
    snapshot: AccountingSnapshot | None
    reason: str


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
    market_input: MarketInput | None = None
    market_research_as_of: date | None = None

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
            "market_input": (
                self.market_input.provenance(self.market_research_as_of).to_dict()
                if self.market_input is not None and self.market_research_as_of is not None
                else None
            ),
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
        sec_client_factory: Callable[[], SecClient] | None = None,
        progress_observer: Callable[[AnalysisProgressEvent], None] | None = None,
    ) -> None:
        self.root = Path(repository_root)
        self.registry = DomainRegistry(self.root)
        self.resolver = resolver or CompanyResolver(self.root)
        self.evidence_planner = evidence_planner or EvidencePlanner(self.root)
        self.sec_client_factory = sec_client_factory or self._sec_client_from_env
        self.progress_observer = progress_observer

    def plan(self, ticker: str) -> AnalysisPlan:
        """Resolve identity and readiness without acquiring, valuing, or publishing."""
        normalized = ticker.strip().upper()
        resolved = self.resolver.resolve(normalized)
        if resolved is None:
            return self._blocked_plan(
                AnalysisStatus.BLOCKED,
                CompanyIdentity(normalized, None, None, None, None, None, None, None),
                "authoritative company resolution is required",
            )
        return self._plan_resolved(normalized, resolved)

    def _plan_resolved(
        self,
        normalized: str,
        resolved: ResolvedCompany,
        *,
        accounting_snapshot: AccountingSnapshot | None = None,
        acquisition: AnalysisStage | None = None,
    ) -> AnalysisPlan:
        """Plan from one already-resolved identity without repeating resolution."""
        acquisition_stage = acquisition or AnalysisStage(
            AnalysisStageState.NOT_REQUESTED, "automatic acquisition is disabled"
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
            evidence_plan = self.evidence_planner.plan(identity)
            snapshot = accounting_snapshot or self._generic_accounting_snapshot(identity)
            if snapshot is not None:
                market_blocked = AnalysisStage(
                    AnalysisStageState.BLOCKED, "canonical market evidence is not available"
                )
                return AnalysisPlan(
                    "analysis-plan-v1",
                    AnalysisStatus.EVIDENCE_REQUIRED,
                    identity,
                    acquisition_stage,
                    AnalysisStage(AnalysisStageState.COMPLETED),
                    market_blocked,
                    market_blocked,
                    AnalysisStage(AnalysisStageState.NOT_REQUESTED, "publishing is not requested"),
                    evidence_plan,
                )
            return self._blocked_plan(
                AnalysisStatus.EVIDENCE_REQUIRED,
                identity,
                "checksum-verified canonical evidence is not available",
                evidence_plan,
                acquisition=acquisition_stage,
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
            snapshot = accounting_snapshot or self._generic_accounting_snapshot(identity)
            if snapshot is not None:
                market_as_of = self._research_as_of(research)
                market_input = self._canonical_market_input(
                    ticker=security.ticker, evaluation_as_of=market_as_of, snapshot=snapshot
                )
                if market_input is None:
                    market_blocked = AnalysisStage(
                        AnalysisStageState.BLOCKED, "canonical market evidence is not available"
                    )
                    return AnalysisPlan(
                        "analysis-plan-v1",
                        AnalysisStatus.EVIDENCE_REQUIRED,
                        identity,
                        acquisition_stage,
                        AnalysisStage(AnalysisStageState.COMPLETED),
                        market_blocked,
                        market_blocked,
                        AnalysisStage(
                            AnalysisStageState.NOT_REQUESTED, "publishing is not requested"
                        ),
                        evidence_plan,
                    )
                capital_cost = self._generic_capital_cost(
                    identity=identity,
                    snapshot=snapshot,
                    market_input=market_input,
                    research_as_of=market_as_of,
                )
                if capital_cost is not None:
                    ready = AnalysisStage(AnalysisStageState.READY)
                    return AnalysisPlan(
                        "analysis-plan-v1",
                        AnalysisStatus.READY,
                        identity,
                        acquisition_stage,
                        ready,
                        ready,
                        ready,
                        AnalysisStage(
                            AnalysisStageState.NOT_REQUESTED,
                            "publishing is not requested",
                        ),
                        evidence_plan,
                        market_input=market_input,
                        market_research_as_of=market_as_of,
                    )

                return AnalysisPlan(
                    "analysis-plan-v1",
                    AnalysisStatus.EVIDENCE_REQUIRED,
                    identity,
                    acquisition_stage,
                    AnalysisStage(AnalysisStageState.COMPLETED),
                    AnalysisStage(AnalysisStageState.COMPLETED),
                    AnalysisStage(
                        AnalysisStageState.BLOCKED,
                        "BETA_REQUIRED,RISK_FREE_REQUIRED,ERP_REQUIRED,COST_OF_DEBT_REQUIRED",
                    ),
                    AnalysisStage(AnalysisStageState.NOT_REQUESTED, "publishing is not requested"),
                    evidence_plan,
                    market_input=market_input,
                    market_research_as_of=market_as_of,
                )
            return self._blocked_plan(
                AnalysisStatus.EVIDENCE_REQUIRED,
                identity,
                "checksum-verified canonical evidence is not available",
                evidence_plan,
                acquisition=acquisition_stage,
            )
        if not capability.deterministic_research_ready:
            return self._blocked_plan(
                AnalysisStatus.EVIDENCE_REQUIRED,
                identity,
                "validated evidence and model requirements are not ready",
                evidence_plan,
                acquisition=acquisition_stage,
            )
        ready = AnalysisStage(AnalysisStageState.READY)
        return AnalysisPlan(
            "analysis-plan-v1",
            AnalysisStatus.READY,
            identity,
            acquisition_stage,
            ready,
            ready,
            ready,
            AnalysisStage(AnalysisStageState.NOT_REQUESTED, "publishing is not requested"),
            evidence_plan,
        )

    def analyze(self, ticker: str) -> AnalysisResult:
        """Resolve offline-first, refreshing the authoritative reference at most once."""
        normalized = ticker.strip().upper()
        self._emit(AnalysisProgressKind.RESOLUTION_STARTED, normalized)
        try:
            resolved = self.resolver.resolve(normalized)
        except Exception:
            blocked = self._unresolved_plan(
                normalized,
                AnalysisStatus.BLOCKED,
                "local company resolution could not complete",
            )
            return AnalysisResult("analysis-result-v1", AnalysisStatus.BLOCKED, blocked, None)
        if resolved is None:
            try:
                if not isinstance(self.resolver, RefreshableSymbolResolver):
                    raise TypeError("resolver does not support authoritative refresh")
                self.resolver.refresh(self.sec_client_factory())
                resolved = self.resolver.resolve(normalized)
            except Exception:
                blocked = self._unresolved_plan(
                    normalized,
                    AnalysisStatus.BLOCKED,
                    "authoritative company resolution could not complete",
                )
                return AnalysisResult("analysis-result-v1", AnalysisStatus.BLOCKED, blocked, None)
            if resolved is None:
                unsupported = self._unresolved_plan(
                    normalized,
                    AnalysisStatus.UNSUPPORTED_TICKER,
                    "ticker is absent from the authoritative SEC company reference",
                )
                return AnalysisResult(
                    "analysis-result-v1",
                    AnalysisStatus.UNSUPPORTED_TICKER,
                    unsupported,
                    None,
                )

        plan = self._plan_resolved(normalized, resolved)
        acquired_snapshot: AccountingSnapshot | None = None
        if plan.status is not AnalysisStatus.READY:
            if not self._requires_sec_acquisition(plan):
                return AnalysisResult("analysis-result-v1", plan.status, plan, None)
            recovery = self._recover_sec_evidence(plan.identity)
            if recovery.status is not AnalysisStatus.READY or recovery.snapshot is None:
                terminal = self._post_acquisition_plan(
                    plan,
                    recovery.status,
                    recovery.reason,
                )
                return AnalysisResult("analysis-result-v1", recovery.status, terminal, None)
            acquired_snapshot = recovery.snapshot
            plan = self._plan_resolved(
                normalized,
                resolved,
                accounting_snapshot=acquired_snapshot,
                acquisition=AnalysisStage(AnalysisStageState.COMPLETED, recovery.reason),
            )
            if plan.status is not AnalysisStatus.READY:
                return AnalysisResult("analysis-result-v1", plan.status, plan, None)
        try:
            if plan.market_input is not None and plan.market_research_as_of is not None:
                canonical = self._generic_canonical_result(
                    plan,
                    accounting_snapshot=acquired_snapshot,
                )
            else:
                canonical = build_canonical_research_result(
                    plan.identity.ticker,
                    self.root,
                )
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

    def _requires_sec_acquisition(self, plan: AnalysisPlan) -> bool:
        """Return whether the offline plan exposes an acquisition-eligible SEC gap."""
        if (
            plan.status is not AnalysisStatus.EVIDENCE_REQUIRED
            or plan.evidence.state is not AnalysisStageState.BLOCKED
            or plan.evidence_plan is None
        ):
            return False
        return any(
            item.requirement.provider == "SEC"
            and item.requirement.critical
            and item.state in {EvidenceState.MISSING, EvidenceState.STALE}
            for item in plan.evidence_plan.items
        )

    def _recover_sec_evidence(self, identity: CompanyIdentity) -> _SecRecoveryResult:
        """Run one SEC fast path and at most one filing-native fallback phase."""
        self._emit(AnalysisProgressKind.FAST_PATH_ACQUISITION_STARTED)
        try:
            client = self.sec_client_factory()
            provider = StructuredSecProvider(client, self.root / "data/raw/sec")
            bundle = provider.acquire_fast_path(identity)
            self._emit(AnalysisProgressKind.FAST_PATH_ACQUISITION_COMPLETED)

            raw_facts = extract_company_facts(
                bundle.companyfacts,
                source_identity=bundle.companyfacts_staged.sha256,
            )
            gate = evaluate_sec_canonical_gate(raw_facts)
            if gate.state is SecCanonicalGateState.READY:
                if gate.snapshot is None:
                    raise ValueError("READY SEC gate has no accounting snapshot")
                self._emit(AnalysisProgressKind.CANONICAL_GATE_READY)
                self._emit(AnalysisProgressKind.CANONICALIZATION_COMPLETED)
                return _SecRecoveryResult(
                    AnalysisStatus.READY,
                    gate.snapshot,
                    "SEC fast path canonical evidence verified",
                )
            if gate.state is SecCanonicalGateState.BLOCKED:
                return self._blocked_sec_recovery(gate.reason)
            if gate.reason is None:
                raise ValueError("GAP SEC gate has no typed reason")

            self._emit(AnalysisProgressKind.CANONICAL_GATE_GAP, gate.reason.value)
            fallback = plan_filing_fallback(
                gate.reason,
                bundle.submissions,
                self._filing_requirement_context(bundle.submissions, raw_facts),
            )
            if fallback is None:
                return _SecRecoveryResult(
                    AnalysisStatus.EVIDENCE_REQUIRED,
                    None,
                    f"SEC canonical evidence gap: {gate.reason.value}",
                )
            if len({filing.accession for filing in fallback.filings}) != len(
                fallback.filings
            ) or any(
                filing.amendment or filing.form not in {"10-K", "10-Q"}
                for filing in fallback.filings
            ):
                raise ValueError("filing fallback plan violates original-filing invariant")

            self._emit(AnalysisProgressKind.FILING_FALLBACK_STARTED, gate.reason.value)
            issuer_root = self.root / "data/cache/sec_corpus_live" / identity.ticker
            verified = tuple(
                self._verified_filing_artifacts(
                    identity,
                    filing,
                    export_sec_filing(
                        client,
                        staging_root=self.root / "data/raw/sec",
                        issuer_root=issuer_root,
                        ticker=identity.ticker,
                        cik=identity.cik or "",
                        filing=filing,
                    ),
                    issuer_root,
                    raw_facts,
                )
                for filing in fallback.filings
            )
            filing_evidence = parse_filing_native_evidence(verified)
            self._emit(AnalysisProgressKind.FILING_FALLBACK_COMPLETED, gate.reason.value)
            post_fallback = evaluate_sec_canonical_gate(
                (*raw_facts, *filing_evidence.raw_facts),
                semantic_extensions=filing_evidence.semantic_extensions,
            )
            if post_fallback.state is SecCanonicalGateState.READY:
                if post_fallback.snapshot is None:
                    raise ValueError("READY SEC gate has no accounting snapshot")
                self._emit(AnalysisProgressKind.CANONICAL_GATE_READY)
                self._emit(AnalysisProgressKind.CANONICALIZATION_COMPLETED)
                return _SecRecoveryResult(
                    AnalysisStatus.READY,
                    post_fallback.snapshot,
                    f"SEC filing fallback canonical evidence verified: {gate.reason.value}",
                )
            if post_fallback.state is SecCanonicalGateState.GAP:
                reason = post_fallback.reason or gate.reason
                return _SecRecoveryResult(
                    AnalysisStatus.EVIDENCE_REQUIRED,
                    None,
                    f"SEC canonical evidence gap after fallback: {reason.value}",
                )
            return self._blocked_sec_recovery(post_fallback.reason)
        except Exception:
            return _SecRecoveryResult(
                AnalysisStatus.BLOCKED,
                None,
                "SEC acquisition or canonicalization could not complete",
            )

    @staticmethod
    def _blocked_sec_recovery(reason: SecCanonicalReason | None) -> _SecRecoveryResult:
        detail = reason.value if reason is not None else "UNKNOWN"
        return _SecRecoveryResult(
            AnalysisStatus.BLOCKED,
            None,
            f"SEC canonical evidence blocked: {detail}",
        )

    @staticmethod
    def _filing_requirement_context(
        submissions: SecSubmissionsBundle,
        raw_facts: tuple[RawFact, ...],
    ) -> FilingRequirementContext:
        originals = tuple(
            filing
            for filing in submissions.filings
            if not filing.amendment
            and filing.form in {"10-K", "10-Q"}
            and filing.report_date is not None
        )
        annual = next((filing for filing in originals if filing.form == "10-K"), None)
        quarters = tuple(filing for filing in originals if filing.form == "10-Q")
        current = quarters[0] if quarters else None
        prior: SecFilingDescriptor | None = None
        if current is not None:
            identities = AnalysisOrchestrator._filing_fact_identities(raw_facts)
            current_identity = identities.get(current.accession)
            if current_identity is not None:
                current_year, current_period = current_identity
                prior = next(
                    (
                        filing
                        for filing in quarters[1:]
                        if identities.get(filing.accession) == (current_year - 1, current_period)
                    ),
                    None,
                )
            if prior is None and current.report_date is not None:
                current_date = date.fromisoformat(current.report_date)
                prior = next(
                    (
                        filing
                        for filing in quarters[1:]
                        if filing.report_date is not None
                        and date.fromisoformat(filing.report_date).year == current_date.year - 1
                    ),
                    None,
                )
        return FilingRequirementContext(
            annual_report_date=annual.report_date if annual is not None else None,
            current_ytd_report_date=current.report_date if current is not None else None,
            prior_ytd_report_date=prior.report_date if prior is not None else None,
        )

    @staticmethod
    def _filing_fact_identities(
        raw_facts: tuple[RawFact, ...],
    ) -> dict[str, tuple[int, str]]:
        candidates: dict[str, set[tuple[int, str]]] = {}
        for fact in raw_facts:
            if fact.fiscal_year > 0 and fact.fiscal_period in {"FY", "Q1", "Q2", "Q3"}:
                candidates.setdefault(fact.accession, set()).add(
                    (fact.fiscal_year, fact.fiscal_period)
                )
        return {
            accession: next(iter(identities))
            for accession, identities in candidates.items()
            if len(identities) == 1
        }

    @classmethod
    def _verified_filing_artifacts(
        cls,
        identity: CompanyIdentity,
        filing: SecFilingDescriptor,
        records: list[dict[str, object]],
        issuer_root: Path,
        raw_facts: tuple[RawFact, ...],
    ) -> VerifiedFilingArtifacts:
        if identity.cik is None or filing.report_date is None or not records:
            raise ValueError("filing export identity is incomplete")
        root = issuer_root.resolve()
        artifacts: list[FilingArtifact] = []
        seen_paths: set[Path] = set()
        for record in records:
            artifact_kind = record.get("artifact_kind")
            if artifact_kind not in {"filing-index", "filing-artifact"}:
                raise ValueError("filing export record has unsupported artifact kind")
            expected = {
                "accession": filing.accession,
                "form": filing.form,
                "filing_date": filing.filing_date,
                "report_date": filing.report_date,
            }
            if any(record.get(key) != value for key, value in expected.items()):
                raise ValueError("filing export record disagrees with its plan")
            path_value = record.get("path")
            checksum = record.get("sha256")
            if not isinstance(path_value, str) or not isinstance(checksum, str):
                raise ValueError("filing export record is malformed")
            relative = Path(path_value)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("filing export path escapes issuer root")
            path = (issuer_root / relative).resolve()
            if root not in path.parents or path in seen_paths or not path.is_file():
                raise ValueError("filing export path is absent or duplicated")
            if hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
                raise ValueError("filing export checksum mismatch")
            seen_paths.add(path)
            if artifact_kind == "filing-artifact":
                artifacts.append(FilingArtifact(path, checksum))

        if not artifacts:
            raise ValueError("filing export contains no filing artifacts")

        filing_identity = cls._filing_fact_identities(raw_facts).get(filing.accession)
        if filing_identity is None:
            raise ValueError("filing fiscal identity is unavailable")
        fiscal_year, fiscal_period = filing_identity
        return VerifiedFilingArtifacts(
            filing.accession,
            filing.form,
            date.fromisoformat(filing.filing_date),
            date.fromisoformat(filing.report_date),
            fiscal_year,
            fiscal_period,
            identity.cik,
            tuple(artifacts),
        )

    @staticmethod
    def _post_acquisition_plan(
        plan: AnalysisPlan,
        status: AnalysisStatus,
        reason: str,
    ) -> AnalysisPlan:
        acquisition_state = (
            AnalysisStageState.BLOCKED
            if status is AnalysisStatus.BLOCKED
            else AnalysisStageState.COMPLETED
        )
        blocked = AnalysisStage(AnalysisStageState.BLOCKED, reason)
        return AnalysisPlan(
            plan.schema_version,
            status,
            plan.identity,
            AnalysisStage(acquisition_state, reason),
            blocked,
            blocked,
            blocked,
            plan.publishing,
            plan.evidence_plan,
        )

    def _emit(self, kind: AnalysisProgressKind, detail: str | None = None) -> None:
        if self.progress_observer is not None:
            self.progress_observer(AnalysisProgressEvent(kind, detail))

    def _generic_capital_cost(
        self,
        *,
        identity: CompanyIdentity,
        snapshot: object,
        market_input: MarketInput,
        research_as_of: date | None,
    ) -> CapitalCostResult | None:
        """Derive WACC only when all frozen canonical inputs are available."""
        import json

        from .accounting import AccountingSnapshot
        from .beta_evidence import (
            canonical_beta_evidence,
            load_cached_price_series,
        )
        from .capital_cost import (
            CapitalCostRequirements,
            CostOfDebtEvidence,
            IssuerValueEvidence,
            TaxRateSemantic,
            derive_effective_tax_rate,
            derive_wacc,
        )
        from .equity_risk_premium import (
            canonical_equity_risk_premium,
            load_cached_stern_erp_observations,
        )
        from .evidence_quality import content_identity
        from .risk_free_evidence import (
            canonical_risk_free_evidence,
            load_cached_treasury_observations,
        )

        if (
            not isinstance(snapshot, AccountingSnapshot)
            or research_as_of is None
            or identity.security_id is None
            or identity.issuer_id is None
            or snapshot.income_tax_expense is None
            or snapshot.pretax_income is None
            or snapshot.debt is None
        ):
            return None

        income_tax_expense = snapshot.income_tax_expense
        pretax_income = snapshot.pretax_income
        debt_value = snapshot.debt
        market_equity_value = market_input.market_equity

        assert income_tax_expense is not None
        assert pretax_income is not None
        assert debt_value is not None
        assert market_equity_value is not None

        cache_key = f"{identity.issuer_id}_{identity.ticker}"

        try:
            security_prices = load_cached_price_series(
                root=self.root,
                manifest_path=(
                    self.root / "data/cache/market/yfinance" / cache_key / "history-manifest.json"
                ),
            )
            benchmark_prices = load_cached_price_series(
                root=self.root,
                manifest_path=(
                    self.root
                    / "data/cache/market/yfinance"
                    / "benchmark_^GSPC"
                    / "history-manifest.json"
                ),
            )

            beta = canonical_beta_evidence(
                security=security_prices,
                benchmark=benchmark_prices,
            ).as_capital_cost_evidence()

            risk_free = canonical_risk_free_evidence(
                cache=load_cached_treasury_observations(
                    root=self.root,
                    manifest_path=(self.root / "data/cache/treasury/daily-par-yield/manifest.json"),
                ),
                evaluation_as_of=research_as_of,
            ).as_capital_cost_evidence()

            erp = canonical_equity_risk_premium(
                cache=load_cached_stern_erp_observations(
                    root=self.root,
                    manifest_path=(self.root / "data/cache/erp/nyu-stern/manifest.json"),
                ),
                evaluation_as_of=research_as_of,
            ).as_capital_cost_evidence()

            debt_directory = self.root / "data/cache/debt/market" / cache_key
            debt_artifacts = tuple(sorted(debt_directory.glob("*.json")))

            if len(debt_artifacts) != 1:
                return None

            debt_payload = json.loads(debt_artifacts[0].read_text(encoding="utf-8"))

            if (
                debt_payload.get("schema_version") != "market-debt-observation-v1"
                or debt_payload.get("issuer_id") != identity.issuer_id
                or debt_payload.get("security_id") != identity.security_id
            ):
                return None

            debt_identity = content_identity(debt_payload)

            cost_of_debt = CostOfDebtEvidence(
                debt_identity,
                identity.security_id,
                float(debt_payload["yield"]),
                "decimal_rate",
                date.fromisoformat(debt_payload["settlement_date"]),
                debt_identity,
                "secondary_market_quote",
                debt_identity,
                "market_debt_yield",
            )

            million = 1_000_000.0

            sec_quality = content_identity(
                {
                    "issuer_id": identity.issuer_id,
                    "period_end": snapshot.period_end.isoformat(),
                    "source_lineage": snapshot.source_lineage,
                }
            )

            tax_rate = derive_effective_tax_rate(
                tax_expense=IssuerValueEvidence(
                    f"{identity.security_id}:tax-expense",
                    identity.issuer_id,
                    "tax_expense",
                    "income_tax_expense",
                    income_tax_expense / million,
                    "USD million",
                    snapshot.period_end,
                    sec_quality,
                    "sec",
                    sec_quality,
                ),
                pretax_income=IssuerValueEvidence(
                    f"{identity.security_id}:pretax-income",
                    identity.issuer_id,
                    "pretax_income",
                    "pretax_income",
                    pretax_income / million,
                    "USD million",
                    snapshot.period_end,
                    sec_quality,
                    "sec",
                    sec_quality,
                ),
                identity=f"{identity.security_id}:effective-tax",
                quality_identity=sec_quality,
            )

            market_provenance = market_input.provenance(research_as_of)
            market_quality = market_provenance.market_quality_identity or content_identity(
                market_provenance.to_dict()
            )

            requirements = CapitalCostRequirements(
                "capm_wacc_v1",
                "10Y",
                "equity_risk_premium_methodology_v1",
                ("deterministic_regression",),
                ("total_interest_bearing_debt",),
                (TaxRateSemantic.EFFECTIVE,),
                365,
                cost_of_debt_methodology="market_debt_yield",
            )

            return derive_wacc(
                research_as_of=research_as_of,
                security_id=identity.security_id,
                requirements=requirements,
                risk_free=risk_free,
                equity_risk_premium=erp,
                beta=beta,
                interest_expense=None,
                average_debt=None,
                cost_of_debt=cost_of_debt,
                tax_rate=tax_rate,
                market_equity=IssuerValueEvidence(
                    f"{identity.security_id}:market-equity",
                    identity.issuer_id,
                    "market_equity",
                    "canonical_market_equity",
                    market_equity_value / million,
                    "USD million",
                    research_as_of,
                    market_quality,
                    "canonical_market_input",
                    market_quality,
                ),
                debt=IssuerValueEvidence(
                    f"{identity.security_id}:debt",
                    identity.issuer_id,
                    "debt",
                    "total_interest_bearing_debt",
                    debt_value / million,
                    "USD million",
                    snapshot.period_end,
                    sec_quality,
                    "sec",
                    sec_quality,
                ),
            )
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _generic_canonical_result(
        self,
        plan: AnalysisPlan,
        *,
        accounting_snapshot: AccountingSnapshot | None = None,
    ) -> CanonicalResearchResult:
        """Build reverse-DCF research without inventing forward scenarios."""
        from .accounting import AccountingSnapshot
        from .evidence_quality import content_identity
        from .valuation import (
            FcffInputs,
            calculate_nopat,
            calculate_roic,
            solve_fcff_implied_growth,
        )

        snapshot = accounting_snapshot or self._generic_accounting_snapshot(plan.identity)
        market_input = plan.market_input
        research_as_of = plan.market_research_as_of

        if (
            not isinstance(snapshot, AccountingSnapshot)
            or market_input is None
            or research_as_of is None
            or plan.identity.issuer_id is None
            or plan.identity.security_id is None
            or snapshot.ebit is None
            or snapshot.depreciation_amortization is None
            or snapshot.capex is None
            or snapshot.change_in_working_capital is None
            or snapshot.invested_capital is None
            or snapshot.cash is None
            or snapshot.marketable_securities is None
            or snapshot.debt is None
        ):
            raise ResearchResultError("GENERIC_RESEARCH_INPUTS_REQUIRED")

        ebit = snapshot.ebit
        depreciation_amortization = snapshot.depreciation_amortization
        capex = snapshot.capex
        change_in_working_capital = snapshot.change_in_working_capital
        invested_capital = snapshot.invested_capital
        cash = snapshot.cash
        marketable_securities = snapshot.marketable_securities
        debt_value = snapshot.debt
        market_equity_value = market_input.market_equity

        assert market_equity_value is not None
        assert ebit is not None
        assert depreciation_amortization is not None
        assert capex is not None
        assert change_in_working_capital is not None
        assert invested_capital is not None
        assert cash is not None
        assert marketable_securities is not None
        assert debt_value is not None

        capital = self._generic_capital_cost(
            identity=plan.identity,
            snapshot=snapshot,
            market_input=market_input,
            research_as_of=research_as_of,
        )
        if capital is None:
            raise ResearchResultError("GENERIC_CAPITAL_COST_REQUIRED")

        # valuation.py contract uses USD millions.
        million = 1_000_000.0

        fcff = FcffInputs(
            ebit / million,
            capital.tax_rate,
            depreciation_amortization / million,
            capex / million,
            change_in_working_capital / million,
        ).reconstructed_fcff()

        nopat = calculate_nopat(
            ebit=ebit / million,
            tax_rate=capital.tax_rate,
        )

        roic = calculate_roic(
            nopat=nopat,
            invested_capital=invested_capital.average / million,
        )

        market_equity = market_equity_value / million
        cash = cash / million
        marketable_securities = marketable_securities / million
        debt = debt_value / million

        enterprise_value = market_equity - cash - marketable_securities + debt

        if enterprise_value <= 0 or fcff <= 0:
            raise ResearchResultError("GENERIC_REVERSE_DCF_INPUT_INVALID")

        # These are sensitivity coordinates, not a forecast/base case.
        years = 10
        terminal_growth_rates = (0.02, 0.03, 0.04)

        reverse_points = [
            {
                "terminal_growth": terminal_growth,
                "implied_growth": solve_fcff_implied_growth(
                    market_enterprise_value=enterprise_value,
                    starting_fcff=fcff,
                    wacc=capital.wacc,
                    terminal_growth=terminal_growth,
                    years=years,
                ),
            }
            for terminal_growth in terminal_growth_rates
        ]

        security = self.registry.security(plan.identity.ticker)
        issuer = self.registry.issuer_for(plan.identity.ticker)
        market_provenance = market_input.provenance(research_as_of)

        model_policy = {
            "profile_id": "reverse-fcff-canonical",
            "version": "1",
            "years": years,
            "terminal_growth_rates": terminal_growth_rates,
            "selection_policy": "sensitivity_only_no_base_case",
        }

        model = {
            **model_policy,
            "content_identity": content_identity(model_policy),
        }

        research_identity = content_identity(
            {
                "issuer_id": security.issuer_id,
                "security_id": security.security_id,
                "research_as_of": research_as_of.isoformat(),
                "model": model["content_identity"],
            }
        )

        draft = CanonicalResearchResult(
            "research-result-v1",
            research_identity,
            research_as_of,
            {
                "issuer_id": issuer.id,
                "display_name": issuer.display_name,
            },
            {
                "security_id": security.security_id,
                "ticker": security.ticker,
                "exchange": security.exchange,
                "share_class": security.share_class,
            },
            {
                "kind": "canonical-generic",
                "issuer_evidence_identity": issuer.evidence_identity,
                "quality": None,
                "capital_cost": {
                    "source_mode": "canonical",
                    "provenance_identity": (capital.provenance.content_identity),
                },
            },
            model,
            market_provenance,
            {
                "financial_evidence_quality": None,
                "model_requirements": None,
                "market_quality_identity": (market_provenance.market_quality_identity),
                "market_source_mode": market_provenance.source_mode,
                "model_stage_readiness": {},
                "deterministic_research_ready": True,
                "agent_research_ready": False,
                "capital_cost_ready": True,
                "valuation_ready": True,
                "forward_scenarios_ready": False,
            },
            {
                "reconstructed_fcff": fcff,
                "normalized_fcff": fcff,
                "nopat": nopat,
                "roic": roic,
                "wacc": capital.wacc,
                "roic_minus_wacc": roic - capital.wacc,
                "fcff_yield": fcff / enterprise_value,
                "scenarios": {},
                "diagnostics": [
                    ("generic valuation is reverse-DCF-first; no analyst forward scenarios")
                ],
            },
            {
                "price": market_input.price,
                "market_equity": market_equity,
                "enterprise_value": enterprise_value,
            },
            {
                "methodology": "fcff_reverse_dcf_sensitivity_v1",
                "years": years,
                "wacc": capital.wacc,
                "terminal_growth_sensitivity": reverse_points,
            },
            "",
        )

        return CanonicalResearchResult(
            **{
                **draft.__dict__,
                "content_identity": content_identity(draft.payload(include_identity=False)),
            }
        )

    def _generic_accounting_snapshot(self, identity: CompanyIdentity) -> object | None:
        """Return only a fully validated local SEC accounting snapshot."""
        from .accounting import (
            AccountingError,
            normalize_accounting_snapshot,
            promote_local_sec_accounting_evidence,
        )
        from .local_sec_corpus import LocalSecCorpus, LocalSecCorpusError

        try:
            facts, spec = promote_local_sec_accounting_evidence(LocalSecCorpus(self.root), identity)
            return normalize_accounting_snapshot(facts, spec=spec, tax_rate=None)
        except (AccountingError, LocalSecCorpusError, OSError, ValueError):
            return None

    def _canonical_market_input(
        self, *, ticker: str, evaluation_as_of: date | None, snapshot: object
    ) -> MarketInput | None:
        """Promote one registered canonical market input, failing closed on all gaps."""
        from .accounting import AccountingSnapshot

        if not isinstance(snapshot, AccountingSnapshot) or snapshot.valuation_shares is None:
            return None
        if evaluation_as_of is None:
            return None
        try:
            return canonical_market_input(
                root=self.root,
                ticker=ticker,
                evaluation_as_of=evaluation_as_of,
                valuation_shares=snapshot.valuation_shares,
            )
        except (MarketInputError, UniverseError, OSError, ValueError):
            return None

    @staticmethod
    def _research_as_of(research: dict[str, object]) -> date | None:
        value = research.get("as_of")
        if not isinstance(value, str):
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None

    @staticmethod
    def _sec_client_from_env() -> SecClient:
        return SecClient(SecConfig.from_env())

    @classmethod
    def _unresolved_plan(cls, normalized: str, status: AnalysisStatus, reason: str) -> AnalysisPlan:
        return cls._blocked_plan(
            status,
            CompanyIdentity(normalized, None, None, None, None, None, None, None),
            reason,
        )

    @staticmethod
    def _blocked_plan(
        status: AnalysisStatus,
        identity: CompanyIdentity,
        reason: str,
        evidence_plan: EvidencePlan | None = None,
        *,
        acquisition: AnalysisStage | None = None,
    ) -> AnalysisPlan:
        blocked = AnalysisStage(AnalysisStageState.BLOCKED, reason)
        return AnalysisPlan(
            "analysis-plan-v1",
            status,
            identity,
            acquisition
            or AnalysisStage(AnalysisStageState.NOT_REQUESTED, "automatic acquisition is disabled"),
            blocked,
            blocked,
            blocked,
            AnalysisStage(AnalysisStageState.NOT_REQUESTED, "publishing is not requested"),
            evidence_plan,
        )
