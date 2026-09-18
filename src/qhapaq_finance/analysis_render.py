"""Pure terminal presentation for canonical analysis results."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from textwrap import wrap

from .analysis import AnalysisResult, AnalysisStage, AnalysisStageState, AnalysisStatus
from .evidence_orchestration import EvidenceItem, EvidenceState

_ANSI_RESET = "\x1b[0m"
_ANSI_GREEN = "\x1b[32m"
_ANSI_YELLOW = "\x1b[33m"
_ANSI_RED = "\x1b[31m"
_SEC_INCORPORATION_SUFFIX = re.compile(r"\s*/[A-Z]{2}\s*$")


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
    canonical = result.canonical_result
    canonical_name = canonical.issuer.get("display_name") if canonical is not None else None
    display_name = _sanitize_company_name(
        canonical_name
        if isinstance(canonical_name, str) and canonical_name.strip()
        else identity.display_name
    )
    separator_glyph = "-" if options.plain else "─"
    title_separator = " - " if options.plain else " — "
    title = (
        f"QHAPAQ{title_separator}{display_name} ({identity.ticker})"
        if display_name
        else f"QHAPAQ{title_separator}{identity.ticker}"
    )
    return [title, separator_glyph * min(width, len(title)), ""]


def _sanitize_company_name(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = _SEC_INCORPORATION_SUFFIX.sub("", value).strip()
    return cleaned or None


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

    lines.extend(_field("AS OF", canonical.research_as_of.isoformat(), width))

    lines.extend(["", "MARKET EXPECTATIONS"])
    lines.extend(
        _fields(
            (
                ("MARKET PRICE", _number(canonical.market_comparison.get("price"))),
                (
                    "IMPLIED FCF GROWTH",
                    _percentage(canonical.reverse_valuation.get("implied_growth")),
                ),
                (
                    "IMPLIED DISCOUNT RATE",
                    _percentage(canonical.market_comparison.get("fcff_implied_discount_rate")),
                ),
            ),
            width,
        )
    )

    lines.extend(["", "BUSINESS ECONOMICS"])
    lines.extend(
        _fields(
            (
                ("NORMALIZED FCFF", _number(canonical.valuation.get("normalized_fcff"))),
                ("ROIC", _percentage(canonical.valuation.get("roic"))),
                ("WACC", _percentage(canonical.valuation.get("wacc"))),
                ("ROIC - WACC", _percentage(canonical.valuation.get("roic_minus_wacc"))),
            ),
            width,
        )
    )

    lines.extend(["", "BOTTOM LINE"])
    lines.extend(_completed_bottom_line(canonical, width))

    lines.extend(["", "EVIDENCE"])
    lines.extend(
        _fields(
            (
                ("EVIDENCE KIND", canonical.financial_evidence.get("kind")),
                ("MARKET SOURCE", canonical.market_provenance.source_mode),
            ),
            width,
        )
    )

    if options.detail:
        lines.extend(_render_detail(result, width))
    return lines


def _completed_bottom_line(canonical: object, width: int) -> list[str]:
    reverse = getattr(canonical, "reverse_valuation")
    valuation = getattr(canonical, "valuation")
    growth = reverse.get("implied_growth")
    spread = valuation.get("roic_minus_wacc")

    sentences: list[str] = []
    if _is_finite_number(growth):
        sentences.append(
            "At the current market price, the model implies approximately "
            f"{_percentage(growth)} FCF growth under the stated assumptions."
        )
    else:
        sentences.append(
            "At the current market price, implied FCF growth is unavailable under the stated "
            "assumptions."
        )

    if _is_finite_number(spread):
        numeric_spread = float(spread)
        if numeric_spread > 0:
            sentences.append(
                "Current business economics show ROIC "
                f"{_percentage_points(numeric_spread)} percentage points above WACC."
            )
        elif numeric_spread < 0:
            sentences.append(
                "Current business economics show ROIC "
                f"{_percentage_points(numeric_spread)} percentage points below WACC."
            )
        else:
            sentences.append("Current business economics show ROIC approximately equal to WACC.")

    return _paragraph(" ".join(sentences), width)


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


def _is_finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _number(value: object) -> str:
    if _is_finite_number(value):
        return f"{float(value):,.2f}"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "Unavailable"
    return _scalar(value)


def _percentage(value: object) -> str:
    if _is_finite_number(value):
        return f"{float(value):.2%}"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "Unavailable"
    return _scalar(value)


def _percentage_points(value: float) -> str:
    return f"{abs(value) * 100:.2f}"


def _scalar(value: object) -> str:
    if value is None:
        return "Unavailable"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value) if _is_finite_number(value) else "Unavailable"
    if isinstance(value, str):
        return value
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
        fields: list[tuple[str, object]] = [
            (f"{name.upper()} VALUE/SHARE", _number(scenario.get("intrinsic_value_per_share"))),
            (f"{name.upper()} MARGIN", _percentage(scenario.get("margin_of_safety"))),
            (f"{name.upper()} EXPLICIT GROWTH", _percentage(scenario.get("explicit_growth"))),
            (f"{name.upper()} TERMINAL GROWTH", _percentage(scenario.get("terminal_growth"))),
            (
                f"{name.upper()} TERMINAL SHARE",
                _percentage(scenario.get("terminal_value_share")),
            ),
        ]
        warnings = scenario.get("warnings")
        if warnings:
            fields.append((f"{name.upper()} WARNINGS", warnings))
        lines.extend(_fields(tuple(fields), width))
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

    lines.extend(["", "FINANCIAL DETAIL"])
    lines.extend(
        _fields(
            (
                ("RECONSTRUCTED FCFF", _number(canonical.valuation.get("reconstructed_fcff"))),
                ("NOPAT", _number(canonical.valuation.get("nopat"))),
                ("FCFF YIELD", _percentage(canonical.valuation.get("fcff_yield"))),
                (
                    "EXPECTATION GAP",
                    _percentage(canonical.reverse_valuation.get("expectation_growth_gap")),
                ),
            ),
            width,
        )
    )
    lines.extend(["", "FINANCIAL EVIDENCE"])
    lines.extend(_nested_fields(canonical.financial_evidence, width))
    lines.extend(["", "DCF SCENARIOS"])
    scenarios = canonical.valuation.get("scenarios")
    lines.extend(_scenario_summary(scenarios, width))
    diagnostics = canonical.valuation.get("diagnostics")
    lines.extend(_field("DIAGNOSTICS", diagnostics, width))
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
