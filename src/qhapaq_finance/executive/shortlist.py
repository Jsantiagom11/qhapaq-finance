"""Executive Shortlist orchestration without re-ranking Diamond."""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path

from qhapaq_finance.analysis import AnalysisOrchestrator
from qhapaq_finance.company_resolver import CompanyResolver
from qhapaq_finance.diamond.engine import DiamondResult
from qhapaq_finance.diamond.funnel import (
    FunnelRun,
    run_funnel,
)
from qhapaq_finance.diamond.providers.protocol import (
    FundamentalDataProvider,
)
from qhapaq_finance.executive.identity_resolver import DiamondIdentityResolver
from qhapaq_finance.research_result import CanonicalResearchResult

from .contracts import (
    ExecutiveContradiction,
    ExecutiveEvidence,
    ExecutiveShortlistEntry,
    ImpliedExpectationResult,
)
from .contracts import ExecutiveShortlistRun as ExecutiveShortlistRun
from .deep_analysis import (
    DeepAnalysisOrchestrator,
    DeepAnalysisResult,
)
from .goal_seek import GoalSeekInputs, solve_implied_fcff_growth

# Keep the existing shortlist imports available to Python callers.
from .shortlist_render import SCHEMA_VERSION as SCHEMA_VERSION
from .shortlist_render import canonical_shortlist_json as canonical_shortlist_json
from .shortlist_render import render_shortlist_text as render_shortlist_text
from .shortlist_render import shortlist_payload as shortlist_payload
from .synthesis import ExecutiveSynthesis


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None

    converted = float(value)
    return converted if math.isfinite(converted) else None


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None


def _mapping(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _canonical_evidence(
    canonical: CanonicalResearchResult,
) -> tuple[ExecutiveEvidence, ...]:
    valuation = canonical.valuation
    market = canonical.market_comparison

    values = (
        ("normalized_fcff", valuation.get("normalized_fcff")),
        ("roic", valuation.get("roic")),
        ("wacc", valuation.get("wacc")),
        ("enterprise_value", market.get("enterprise_value")),
    )

    return tuple(
        ExecutiveEvidence(
            metric_id=metric_id,
            value=_number(raw_value),
            period_end=None,
            source_identity=canonical.content_identity,
            status=("CANONICAL" if _number(raw_value) is not None else "UNAVAILABLE"),
        )
        for metric_id, raw_value in values
    )


def _diagnostics(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()

    return tuple(item for item in value if isinstance(item, str) and item.strip())


def _contradictions(
    candidate: DiamondResult,
    canonical: CanonicalResearchResult | None,
) -> tuple[ExecutiveContradiction, ...]:
    items: list[ExecutiveContradiction] = []

    for diagnostic in candidate.diagnostics:
        items.append(
            ExecutiveContradiction(
                flag_id=f"DIAMOND:{diagnostic}",
                severity="DIAGNOSTIC",
                description=(f"Diamond diagnostic: {diagnostic}"),
            )
        )

    if canonical is not None:
        for diagnostic in _diagnostics(canonical.valuation.get("diagnostics")):
            items.append(
                ExecutiveContradiction(
                    flag_id=f"ANALYSIS:{diagnostic}",
                    severity="DIAGNOSTIC",
                    description=(
                        "Canonical analysis diagnostic: "
                        f"{diagnostic}; "
                        f"source={canonical.content_identity}"
                    ),
                )
            )

    return tuple(items)


def _goal_seek(
    canonical: CanonicalResearchResult,
) -> ImpliedExpectationResult:
    scenarios = _mapping(canonical.valuation.get("scenarios"))
    base = _mapping(scenarios.get("base"))

    return solve_implied_fcff_growth(
        GoalSeekInputs(
            observed_enterprise_value=_number(canonical.market_comparison.get("enterprise_value")),
            starting_fcff=_number(canonical.valuation.get("normalized_fcff")),
            hurdle_rate=_number(canonical.valuation.get("wacc")),
            terminal_growth_rate=_number(base.get("terminal_growth")),
            years=_positive_int(base.get("years")),
        )
    )


def _why_it_surfaced(candidate: DiamondResult) -> str:
    surfaced_by = candidate.archetypes.surfaced_by
    priority = candidate.archetypes.research_priority

    if surfaced_by is None or priority is None:
        raise ValueError(f"unrankable Diamond result in shortlist: {candidate.ticker}")

    return (
        f"Diamond surfaced {candidate.ticker} as "
        f"{surfaced_by.value} with "
        f"research_priority={priority:.6g}"
    )


def _entry(
    candidate: DiamondResult,
    deep: DeepAnalysisResult,
) -> ExecutiveShortlistEntry:
    if candidate.ticker != deep.ticker:
        raise ValueError(f"shortlist index mismatch: {candidate.ticker} != {deep.ticker}")

    surfaced_by = candidate.archetypes.surfaced_by
    priority = candidate.archetypes.research_priority

    if surfaced_by is None or priority is None:
        raise ValueError(f"unrankable Diamond result in shortlist: {candidate.ticker}")

    canonical: CanonicalResearchResult | None = None
    if deep.analysis_result is not None and deep.analysis_result.canonical_result is not None:
        canonical = deep.analysis_result.canonical_result

    evidence = _canonical_evidence(canonical) if canonical is not None else ()
    contradictions = _contradictions(
        candidate,
        canonical,
    )
    expectations = _goal_seek(canonical) if canonical is not None else None

    synthesis = ExecutiveSynthesis.translate(
        surfaced_by=surfaced_by,
        evidence_dtos=evidence,
        contradictions_dtos=contradictions,
        analysis_status=deep.analysis_status,
        expectation_result=expectations,
    )

    return ExecutiveShortlistEntry(
        ticker=candidate.ticker,
        surfaced_by=synthesis.surfaced_by,
        research_priority=float(priority),
        why_it_surfaced=_why_it_surfaced(candidate),
        evidence=synthesis.evidence_dtos,
        contradictions=synthesis.contradictions_dtos,
        analysis_status=synthesis.analysis_status,
        expectations=synthesis.expectation_result,
        bottom_line=synthesis.bottom_line,
    )


async def build_shortlist_from_funnel(
    funnel: FunnelRun,
    *,
    universe_id: str,
    as_of: date,
    deep_analysis: DeepAnalysisOrchestrator,
) -> ExecutiveShortlistRun:
    """Enrich an already-ranked FunnelRun without changing its order."""
    deep_results = await deep_analysis.analyze(funnel.results)

    entries = tuple(
        _entry(candidate, deep)
        for candidate, deep in zip(
            funnel.results,
            deep_results,
            strict=True,
        )
    )

    return ExecutiveShortlistRun(
        universe_id=universe_id,
        as_of=as_of,
        entries=entries,
        funnel_metadata=funnel.metadata,
    )


async def run_shortlist(
    provider: FundamentalDataProvider,
    *,
    universe_id: str,
    as_of: date,
    depth: int,
    repository_root: str | Path = ".",
) -> ExecutiveShortlistRun:
    """Run real Diamond then bounded deep analysis, preserving Top-N."""
    funnel = run_funnel(
        provider,
        universe_id=universe_id,
        as_of=as_of,
        depth=depth,
    )

    fallback = CompanyResolver(repository_root)
    resolver = DiamondIdentityResolver(funnel.results, fallback)
    analyzer = AnalysisOrchestrator(
        repository_root,
        resolver=resolver,
    )
    deep_analysis = DeepAnalysisOrchestrator(analyzer=analyzer)

    return await build_shortlist_from_funnel(
        funnel,
        universe_id=universe_id,
        as_of=as_of,
        deep_analysis=deep_analysis,
    )
