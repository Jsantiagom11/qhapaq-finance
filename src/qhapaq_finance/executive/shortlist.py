"""Executive Shortlist orchestration without re-ranking Diamond."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import cast

from qhapaq_finance.analysis import AnalysisOrchestrator
from qhapaq_finance.company_resolver import CompanyResolver
from qhapaq_finance.diamond.engine import DiamondResult
from qhapaq_finance.diamond.funnel import (
    FunnelRun,
    FunnelRunMetadata,
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
from .deep_analysis import (
    DeepAnalysisOrchestrator,
    DeepAnalysisResult,
)
from .goal_seek import GoalSeekInputs, solve_implied_fcff_growth
from .synthesis import ExecutiveSynthesis

SCHEMA_VERSION = "executive-shortlist-v1"


@dataclass(frozen=True)
class ExecutiveShortlistRun:
    """Diamond-selected and deep-analysis-enriched shortlist."""

    universe_id: str
    as_of: date
    entries: tuple[ExecutiveShortlistEntry, ...]
    funnel_metadata: FunnelRunMetadata


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


def _evidence_payload(
    item: ExecutiveEvidence,
) -> dict[str, object]:
    return {
        "metric_id": item.metric_id,
        "value": item.value,
        "period_end": (item.period_end.isoformat() if item.period_end is not None else None),
        "source_identity": item.source_identity,
        "status": item.status,
    }


def _contradiction_payload(
    item: ExecutiveContradiction,
) -> dict[str, object]:
    return {
        "flag_id": item.flag_id,
        "severity": item.severity,
        "description": item.description,
    }


def _expectation_payload(
    item: ImpliedExpectationResult | None,
) -> dict[str, object] | None:
    if item is None:
        return None

    return {
        "implied_fcff_growth": item.implied_fcff_growth,
        "starting_fcff": item.starting_fcff,
        "hurdle_rate": item.hurdle_rate,
        "terminal_growth_rate": item.terminal_growth_rate,
        "years": item.years,
        "observed_enterprise_value": (item.observed_enterprise_value),
        "solved_enterprise_value": (item.solved_enterprise_value),
        "relative_error": item.relative_error,
        "lower_bound": item.lower_bound,
        "upper_bound": item.upper_bound,
        "iterations": item.iterations,
        "status": item.status.value,
        "reason": item.reason,
    }


def _stable_output_float(value: float) -> float:
    """Bound presentation precision so equivalent runtime floats serialize identically."""
    return float(format(value, ".15g"))


def _entry_payload(
    item: ExecutiveShortlistEntry,
) -> dict[str, object]:
    return {
        "ticker": item.ticker,
        "surfaced_by": item.surfaced_by.value,
        "research_priority": _stable_output_float(item.research_priority),
        "why_it_surfaced": item.why_it_surfaced,
        "evidence": [_evidence_payload(evidence) for evidence in item.evidence],
        "contradictions": [
            _contradiction_payload(contradiction) for contradiction in item.contradictions
        ],
        "analysis_status": {
            "source_status": (item.analysis_status.source_status.value),
            "conclusion_available": (item.analysis_status.conclusion_available),
            "reason": item.analysis_status.reason,
        },
        "expectations": _expectation_payload(item.expectations),
        "bottom_line": item.bottom_line,
    }


def shortlist_payload(
    run: ExecutiveShortlistRun,
) -> dict[str, object]:
    """Stable semantic payload shared by JSON and text renderers."""
    return {
        "schema_version": SCHEMA_VERSION,
        "universe": run.universe_id,
        "as_of": run.as_of.isoformat(),
        "dataset_identity": (run.funnel_metadata.dataset_identity),
        "entries": [_entry_payload(item) for item in run.entries],
    }


def canonical_shortlist_json(
    run: ExecutiveShortlistRun,
) -> str:
    return (
        json.dumps(
            shortlist_payload(run),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )


def _text_value(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def render_shortlist_text(
    run: ExecutiveShortlistRun,
) -> str:
    payload = shortlist_payload(run)

    lines = [
        "QHAPAQ EXECUTIVE SHORTLIST",
        f"universe={payload['universe']}",
        f"as_of={payload['as_of']}",
        f"dataset_identity={payload['dataset_identity']}",
        f"count={len(run.entries)}",
    ]

    entries = cast(
        list[dict[str, object]],
        payload["entries"],
    )

    for index, entry in enumerate(entries, start=1):
        analysis = cast(
            dict[str, object],
            entry["analysis_status"],
        )
        expectation = cast(
            dict[str, object] | None,
            entry["expectations"],
        )

        lines.extend(
            (
                "",
                f"[{index}] ticker={entry['ticker']}",
                f"surfaced_by={entry['surfaced_by']}",
                (f"research_priority={entry['research_priority']}"),
                f"why_it_surfaced={entry['why_it_surfaced']}",
                (f"analysis_status={analysis['source_status']}"),
                (f"conclusion_available={_text_value(analysis['conclusion_available'])}"),
                (f"analysis_reason={_text_value(analysis['reason'])}"),
            )
        )

        if expectation is None:
            lines.append("expectation_status=-")
        else:
            for key in (
                "status",
                "implied_fcff_growth",
                "starting_fcff",
                "hurdle_rate",
                "terminal_growth_rate",
                "years",
                "observed_enterprise_value",
                "solved_enterprise_value",
                "relative_error",
            ):
                label = "expectation_status" if key == "status" else key
                lines.append(f"{label}={_text_value(expectation[key])}")

        lines.append(f"bottom_line={_text_value(entry['bottom_line'])}")
        lines.append(
            "evidence="
            + json.dumps(
                entry["evidence"],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        )
        lines.append(
            "contradictions="
            + json.dumps(
                entry["contradictions"],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        )

    return "\n".join(lines) + "\n"
