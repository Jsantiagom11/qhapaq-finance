"""Deterministic JSON and text presentation for an Executive Shortlist."""

from __future__ import annotations

import json
from typing import cast

from .contracts import (
    ExecutiveContradiction,
    ExecutiveEvidence,
    ExecutiveShortlistEntry,
    ExecutiveShortlistRun,
    ImpliedExpectationResult,
)

SCHEMA_VERSION = "executive-shortlist-v1"


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
