"""Pure terminal presentation for canonical analysis results."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from textwrap import wrap

from .analysis import AnalysisResult, AnalysisStage, AnalysisStageState, AnalysisStatus
from .evidence_orchestration import EvidenceItem, EvidenceState

_ANSI_RESET = "\x1b[0m"
_ANSI_GREEN = "\x1b[32m"
_ANSI_YELLOW = "\x1b[33m"
_ANSI_RED = "\x1b[31m"


@dataclass(frozen=True)
class AnalysisRenderOptions:
    """Explicit presentation choices for deterministic analysis rendering."""

    detail: bool = False
    plain: bool = False
    color: bool = False
    width: int = 88


def render_analysis(result: AnalysisResult, options: AnalysisRenderOptions) -> str:
    """Project an analysis result into human-readable terminal text."""
    width = max(48, options.width)
    lines = _render_header(result, options, width)
    if result.status is AnalysisStatus.COMPLETED:
        lines.extend(_render_completed(result, options, width))
    elif result.status is AnalysisStatus.EVIDENCE_REQUIRED:
        lines.extend(_render_evidence_required(result, options, width))
    elif result.status is AnalysisStatus.BLOCKED:
        lines.extend(_render_blocked(result, options, width))
    elif result.status is AnalysisStatus.UNSUPPORTED_TICKER:
        lines.extend(_render_unsupported(result, options, width))
    else:
        lines.extend(_render_blocked(result, options, width))
    return "\n".join(lines).rstrip() + "\n"


def _render_header(result: AnalysisResult, options: AnalysisRenderOptions, width: int) -> list[str]:
    identity = result.plan.identity
    title_parts = ["QHAPAQ"]
    if identity.display_name:
        title_parts.append(identity.display_name)
    title_parts.append(identity.ticker)
    title = " - ".join(title_parts)
    separator = "-" if options.plain else "─"
    return [title, separator * min(width, len(title)), ""]


def _render_completed(
    result: AnalysisResult, options: AnalysisRenderOptions, width: int
) -> list[str]:
    canonical = result.canonical_result
    lines = _field("STATUS", _status_label(result.status, options), width)
    if canonical is None:
        lines.extend(["", "BOTTOM LINE"])
        lines.extend(
            _paragraph(
                "The result is marked COMPLETED, but no canonical analysis result is available "
                "for presentation.",
                width,
            )
        )
        return lines

    lines.extend(
        _fields(
            (
                ("ISSUER", canonical.issuer.get("display_name")),
                ("SECURITY", canonical.security.get("ticker")),
                ("AS OF", canonical.research_as_of.isoformat()),
            ),
            width,
        )
    )
    lines.extend(["", "FINANCIAL SNAPSHOT"])
    lines.extend(
        _fields(
            (
                ("RECONSTRUCTED FCFF", _number(canonical.valuation.get("reconstructed_fcff"))),
                ("NORMALIZED FCFF", _number(canonical.valuation.get("normalized_fcff"))),
                ("NOPAT", _number(canonical.valuation.get("nopat"))),
            ),
            width,
        )
    )
    lines.extend(["", "CAPITAL EFFICIENCY"])
    lines.extend(
        _fields(
            (
                ("ROIC", _percentage(canonical.valuation.get("roic"))),
                ("ROIC - WACC", _percentage(canonical.valuation.get("roic_minus_wacc"))),
                ("FCFF YIELD", _percentage(canonical.valuation.get("fcff_yield"))),
            ),
            width,
        )
    )
    lines.extend(["", "COST OF CAPITAL"])
    lines.extend(_field("WACC", _percentage(canonical.valuation.get("wacc")), width))
    lines.extend(["", "MARKET EXPECTATIONS"])
    lines.extend(
        _fields(
            (
                ("MARKET PRICE", _number(canonical.market_comparison.get("price"))),
                (
                    "FCFF IMPLIED RATE",
                    _percentage(canonical.market_comparison.get("fcff_implied_discount_rate")),
                ),
                (
                    "IMPLIED GROWTH",
                    _percentage(canonical.reverse_valuation.get("implied_growth")),
                ),
                (
                    "EXPECTATION GAP",
                    _percentage(canonical.reverse_valuation.get("expectation_growth_gap")),
                ),
            ),
            width,
        )
    )
    lines.extend(["", "SCENARIO SUMMARY"])
    lines.extend(_scenario_summary(canonical.valuation.get("scenarios"), width))
    lines.extend(["", "EVIDENCE SUMMARY"])
    quality = canonical.financial_evidence.get("quality")
    quality_ready = quality.get("research_ready") if isinstance(quality, Mapping) else None
    lines.extend(
        _fields(
            (
                ("EVIDENCE KIND", canonical.financial_evidence.get("kind")),
                ("QUALITY READY", quality_ready),
                (
                    "RESEARCH READY",
                    canonical.readiness.get("deterministic_research_ready"),
                ),
                ("VALUATION READY", canonical.readiness.get("valuation_ready")),
            ),
            width,
        )
    )
    lines.extend(["", "BOTTOM LINE"])
    lines.extend(
        _paragraph(
            "Qhapaq completed the canonical analysis from the currently verified evidence. "
            "Review the market-expectations and scenario sections together with evidence "
            "readiness.",
            width,
        )
    )
    if options.detail:
        lines.extend(_render_detail(result, width))
    return lines


def _render_evidence_required(
    result: AnalysisResult, options: AnalysisRenderOptions, width: int
) -> list[str]:
    identity = result.plan.identity
    lines = _fields(
        (
            ("STATUS", _status_label(result.status, options)),
            ("CIK", identity.cik or "Unavailable"),
            ("RESOLUTION", "verified" if identity.cik else "unresolved"),
        ),
        width,
    )
    unresolved = _unready_critical_evidence(result)
    if unresolved:
        lines.extend(["", "EVIDENCE"])
        lines.extend(_evidence_line(item, options) for item in unresolved)
    lines.extend(["", "BOTTOM LINE"])
    subject = identity.ticker
    if unresolved:
        lines.extend(
            _paragraph(
                f"{subject} was resolved authoritatively, but canonical financial evidence is "
                "not available yet, so Qhapaq cannot continue to a financial analysis.",
                width,
            )
        )
    else:
        lines.extend(
            _paragraph(
                f"{subject} cannot continue to a financial analysis because "
                f"{_blocking_reason(result)}.",
                width,
            )
        )
    lines.extend(["", "NEXT"])
    if unresolved:
        lines.extend(_paragraph("Acquire and verify the missing SEC evidence.", width))
    else:
        lines.extend(_paragraph(_blocking_reason(result), width))
    if options.detail:
        lines.extend(_render_detail(result, width))
    return lines


def _render_blocked(
    result: AnalysisResult, options: AnalysisRenderOptions, width: int
) -> list[str]:
    identity = result.plan.identity
    lines = _field("STATUS", _status_label(result.status, options), width)
    if identity.cik:
        lines.extend(_field("CIK", identity.cik, width))
    reason = _blocking_reason(result)
    lines.extend(["", "BLOCKING REASON", *_paragraph(reason, width)])
    lines.extend(["", "BOTTOM LINE"])
    lines.extend(
        _paragraph(
            f"Analysis for {identity.ticker} is BLOCKED because {reason}. "
            "Resolve the operational blocker before retrying.",
            width,
        )
    )
    if options.detail:
        lines.extend(_render_detail(result, width))
    return lines


def _render_unsupported(
    result: AnalysisResult, options: AnalysisRenderOptions, width: int
) -> list[str]:
    reason = _blocking_reason(result)
    lines = [
        *_field("STATUS", _status_label(result.status, options), width),
        *_field("TICKER", result.plan.identity.ticker, width),
        "",
        "BOTTOM LINE",
        *_paragraph(reason, width),
    ]
    if options.detail:
        lines.extend(_render_detail(result, width))
    return lines


def _status_label(status: AnalysisStatus, options: AnalysisRenderOptions) -> str:
    label = status.value.replace("_", " ")
    if options.plain or not options.color:
        return label
    color = {
        AnalysisStatus.COMPLETED: _ANSI_GREEN,
        AnalysisStatus.EVIDENCE_REQUIRED: _ANSI_YELLOW,
        AnalysisStatus.BLOCKED: _ANSI_RED,
        AnalysisStatus.UNSUPPORTED_TICKER: _ANSI_RED,
    }.get(status, _ANSI_YELLOW)
    return f"{color}{label}{_ANSI_RESET}"


def _fields(items: Sequence[tuple[str, object]], width: int) -> list[str]:
    lines: list[str] = []
    for label, value in items:
        lines.extend(_field(label, value, width))
    return lines


def _field(label: str, value: object, width: int) -> list[str]:
    label_width = min(22, max(14, max(0, width // 3)))
    prefix = f"{label:<{label_width}}"
    displayed = _scalar(value)
    available = max(12, width - len(prefix))
    parts = wrap(
        displayed,
        width=available,
        break_long_words=False,
        break_on_hyphens=False,
    ) or [""]
    return [prefix + parts[0], *(" " * label_width + part for part in parts[1:])]


def _paragraph(text: str, width: int) -> list[str]:
    return wrap(text, width=width, break_long_words=False, break_on_hyphens=False) or [""]


def _number(value: object) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:,.2f}"
    return _scalar(value)


def _percentage(value: object) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:.2%}"
    return _scalar(value)


def _scalar(value: object) -> str:
    if value is None:
        return "Unavailable"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (str, int, float)):
        return str(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return ", ".join(_scalar(item) for item in value) if value else "None"
    return str(value)


def _scenario_summary(value: object, width: int) -> list[str]:
    if not isinstance(value, Mapping):
        return _field("SCENARIOS", "Unavailable", width)
    lines: list[str] = []
    names = [name for name in ("bear", "base", "bull") if name in value]
    names.extend(sorted(str(name) for name in value if name not in names))
    for name in names:
        scenario = value.get(name)
        if not isinstance(scenario, Mapping):
            continue
        lines.extend(
            _fields(
                (
                    (
                        f"{name.upper()} VALUE/SHARE",
                        _number(scenario.get("intrinsic_value_per_share")),
                    ),
                    (f"{name.upper()} MARGIN", _percentage(scenario.get("margin_of_safety"))),
                ),
                width,
            )
        )
    return lines or _field("SCENARIOS", "Unavailable", width)


def _render_detail(result: AnalysisResult, width: int) -> list[str]:
    canonical = result.canonical_result
    lines = ["", "ANALYSIS STAGES"]
    stages = (
        ("acquisition", result.plan.acquisition),
        ("evidence", result.plan.evidence),
        ("research", result.plan.research),
        ("valuation", result.plan.valuation),
        ("publishing", result.plan.publishing),
    )
    for name, stage in stages:
        value = stage.state.value
        if stage.reason:
            value = f"{value} - {stage.reason}"
        lines.extend(_field(name.upper(), value, width))

    lines.extend(["", "EVIDENCE DETAIL"])
    evidence_plan = result.plan.evidence_plan
    if evidence_plan is None:
        lines.extend(_field("EVIDENCE", "Unavailable", width))
    else:
        for item in evidence_plan.items:
            lines.extend(
                _fields(
                    (
                        ("IDENTIFIER", item.requirement.identifier),
                        ("PROVIDER", item.requirement.provider),
                        ("ARTIFACT", item.requirement.artifact_kind),
                        ("STATE", item.state.value),
                        ("REASON", item.reason),
                    ),
                    width,
                )
            )

    if canonical is None:
        return lines

    lines.extend(["", "FINANCIAL EVIDENCE"])
    lines.extend(_nested_fields(canonical.financial_evidence, width))
    lines.extend(["", "VALUATION SCENARIOS"])
    scenarios = canonical.valuation.get("scenarios")
    lines.extend(_nested_fields(scenarios, width))
    diagnostics = canonical.valuation.get("diagnostics")
    lines.extend(_field("diagnostics", diagnostics, width))
    lines.extend(["", "READINESS"])
    lines.extend(_nested_fields(canonical.readiness, width))
    lines.extend(["", "MARKET PROVENANCE"])
    lines.extend(_nested_fields(canonical.market_provenance.to_dict(), width))
    lines.extend(["", "AUDIT"])
    lines.extend(
        _fields(
            (
                ("RESEARCH IDENTITY", canonical.research_identity),
                ("CONTENT IDENTITY", canonical.content_identity),
                ("SCHEMA", canonical.schema_version),
            ),
            width,
        )
    )
    return lines


def _nested_fields(value: object, width: int, prefix: str = "") -> list[str]:
    if isinstance(value, Mapping):
        lines: list[str] = []
        for key in sorted(value, key=str):
            name = f"{prefix}.{key}" if prefix else str(key)
            lines.extend(_nested_fields(value[key], width, name))
        return lines or _field(prefix or "VALUE", "None", width)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if not value:
            return _field(prefix or "VALUE", "None", width)
        if all(
            not isinstance(item, (Mapping, Sequence)) or isinstance(item, str) for item in value
        ):
            return _field(prefix or "VALUE", value, width)
        lines = []
        for index, item in enumerate(value):
            name = f"{prefix}[{index}]" if prefix else f"[{index}]"
            lines.extend(_nested_fields(item, width, name))
        return lines
    return _field(prefix or "VALUE", value, width)


def _unready_critical_evidence(result: AnalysisResult) -> tuple[EvidenceItem, ...]:
    plan = result.plan.evidence_plan
    if plan is None:
        return ()
    ready = {EvidenceState.AVAILABLE, EvidenceState.VERIFIED}
    return tuple(
        item for item in plan.items if item.requirement.critical and item.state not in ready
    )


def _evidence_line(item: EvidenceItem, options: AnalysisRenderOptions) -> str:
    if options.plain:
        glyph = "-" if item.state is EvidenceState.NOT_APPLICABLE else "x"
    else:
        glyph = "✓" if item.state in {EvidenceState.AVAILABLE, EvidenceState.VERIFIED} else "✗"
    return f"  {glyph} {_evidence_label(item):<22}{_state_label(item.state)}"


def _evidence_label(item: EvidenceItem) -> str:
    identifier = item.requirement.identifier
    labels = {
        "company-facts": "Company facts",
        "submissions": "SEC submissions",
        "latest-10k": "Latest 10-K",
        "latest-10q": "Latest 10-Q",
        "canonical-financial-evidence": "Canonical evidence",
    }
    if identifier in labels:
        return labels[identifier]
    return identifier.replace("-", " ").capitalize()


def _state_label(state: EvidenceState) -> str:
    return state.value.replace("_", " ").title()


def _blocking_reason(result: AnalysisResult) -> str:
    stages: tuple[AnalysisStage, ...] = (
        result.plan.acquisition,
        result.plan.evidence,
        result.plan.research,
        result.plan.valuation,
        result.plan.publishing,
    )
    for stage in stages:
        if stage.state is AnalysisStageState.BLOCKED and stage.reason:
            return stage.reason
    for stage in stages:
        if stage.reason:
            return stage.reason
    return "the analysis could not continue"
