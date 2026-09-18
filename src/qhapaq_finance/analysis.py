"""Generic, offline orchestration for a single-company Qhapaq analysis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path

from .capital_cost import CapitalCostResult
from .company_resolver import CompanyResolver, SymbolResolver
from .evidence_orchestration import EvidencePlan, EvidencePlanner
from .market_inputs import MarketInput, MarketInputError, canonical_market_input
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
            snapshot = self._generic_accounting_snapshot(identity)
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
                        AnalysisStage(
                            AnalysisStageState.NOT_REQUESTED, "automatic acquisition is disabled"
                        ),
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
                        AnalysisStage(
                            AnalysisStageState.NOT_REQUESTED,
                            "automatic acquisition is disabled",
                        ),
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
                    AnalysisStage(
                        AnalysisStageState.NOT_REQUESTED, "automatic acquisition is disabled"
                    ),
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
            if plan.market_input is not None and plan.market_research_as_of is not None:
                canonical = self._generic_canonical_result(plan)
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

        snapshot = self._generic_accounting_snapshot(plan.identity)
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
