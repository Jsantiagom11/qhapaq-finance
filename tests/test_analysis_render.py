from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from qhapaq_finance.analysis import (
    AnalysisOrchestrator,
    AnalysisPlan,
    AnalysisResult,
    AnalysisStage,
    AnalysisStageState,
    AnalysisStatus,
    CompanyIdentity,
)
from qhapaq_finance.analysis_render import AnalysisRenderOptions, render_analysis
from qhapaq_finance.evidence_orchestration import (
    EvidenceItem,
    EvidencePlan,
    EvidenceRequirement,
    EvidenceState,
    FreshnessPolicy,
)

ROOT = Path(__file__).resolve().parents[1]


def _identity() -> CompanyIdentity:
    return CompanyIdentity(
        ticker="JPM",
        security_id=None,
        issuer_id=None,
        display_name="JPMorgan Chase & Co.",
        exchange=None,
        share_class=None,
        cik="0000019617",
        source={"source_url": "https://www.sec.gov/files/company_tickers.json"},
    )


def _missing_evidence(identity: CompanyIdentity) -> EvidencePlan:
    requirements = (
        ("company-facts", "SEC_COMPANY_FACTS"),
        ("submissions", "SEC_SUBMISSIONS"),
        ("latest-10k", "SEC_LATEST_10K_METADATA"),
        ("latest-10q", "SEC_LATEST_10Q_METADATA"),
    )
    return EvidencePlan(
        "evidence-plan-v1",
        tuple(
            EvidenceItem(
                EvidenceRequirement(
                    identifier,
                    "SEC",
                    artifact_kind,
                    identity,
                    None,
                    (),
                    (),
                    FreshnessPolicy(7),
                    True,
                ),
                EvidenceState.MISSING,
                "no local artifact",
                None,
            )
            for identifier, artifact_kind in requirements
        ),
    )


def _result(status: AnalysisStatus, reason: str) -> AnalysisResult:
    identity = _identity()
    blocked = AnalysisStage(AnalysisStageState.BLOCKED, reason)
    plan = AnalysisPlan(
        "analysis-plan-v1",
        status,
        identity,
        AnalysisStage(AnalysisStageState.NOT_REQUESTED, "automatic acquisition is disabled"),
        blocked,
        blocked,
        blocked,
        AnalysisStage(AnalysisStageState.NOT_REQUESTED, "publishing is not requested"),
        _missing_evidence(identity) if status is AnalysisStatus.EVIDENCE_REQUIRED else None,
    )
    return AnalysisResult("analysis-result-v1", status, plan, None)


def _rendered_value(text: str, label: str) -> str:
    line = next(line for line in text.splitlines() if line.startswith(label))
    return line[len(label) :].strip()


def _rendered_values(text: str, label: str) -> list[str]:
    return [
        line[len(label) :].strip()
        for line in text.splitlines()
        if line.startswith(label) and line != label
    ]


def test_evidence_required_executive_view_is_human_and_omits_empty_valuation() -> None:
    result = _result(
        AnalysisStatus.EVIDENCE_REQUIRED,
        "checksum-verified canonical evidence is not available",
    )

    text = render_analysis(result, AnalysisRenderOptions(plain=True, width=72))

    assert "QHAPAQ - JPMorgan Chase & Co. (JPM)" in text
    assert "STATUS" in text
    assert "EVIDENCE REQUIRED" in text
    assert "Company facts" in text
    assert "SEC submissions" in text
    assert "BOTTOM LINE" in text
    assert "NEXT" in text
    assert "VALUATION" not in text
    assert '"schema_version"' not in text
    assert "\x1b[" not in text
    assert text.endswith("\n")
    assert not text.endswith("\n\n")


def test_evidence_required_detail_adds_compact_evidence_quality() -> None:
    result = _result(
        AnalysisStatus.EVIDENCE_REQUIRED,
        "checksum-verified canonical evidence is not available",
    )

    executive = render_analysis(result, AnalysisRenderOptions(plain=True))
    detail = render_analysis(result, AnalysisRenderOptions(detail=True, plain=True))

    assert "ANALYST DETAIL" not in executive
    assert "EVIDENCE QUALITY" not in executive
    assert "ANALYST DETAIL" in detail
    assert "EVIDENCE QUALITY" in detail
    assert "COMPANY FACTS" in detail
    assert "MISSING - no local artifact" in detail
    assert "IDENTIFIER" not in detail
    assert "PROVIDER" not in detail
    assert "ARTIFACT" not in detail
    assert len(detail) > len(executive)


def test_evidence_required_with_ready_sec_evidence_surfaces_existing_blocker() -> None:
    result = _result(
        AnalysisStatus.EVIDENCE_REQUIRED,
        "canonical market evidence is not available",
    )
    assert result.plan.evidence_plan is not None
    ready_plan = replace(
        result.plan.evidence_plan,
        items=tuple(
            replace(item, state=EvidenceState.VERIFIED, reason="validated local SEC corpus")
            for item in result.plan.evidence_plan.items
        ),
    )
    result = replace(result, plan=replace(result.plan, evidence_plan=ready_plan))

    text = render_analysis(result, AnalysisRenderOptions(plain=True))

    assert "canonical market evidence is not available" in text
    assert "canonical financial evidence is not available yet" not in text


def test_blocked_view_preserves_blocked_semantics() -> None:
    text = render_analysis(
        _result(
            AnalysisStatus.BLOCKED,
            "authoritative company resolution could not complete",
        ),
        AnalysisRenderOptions(plain=True),
    )

    assert "BLOCKED" in text
    assert "authoritative company resolution could not complete" in text
    assert "UNSUPPORTED TICKER" not in text


def test_unsupported_ticker_view_does_not_show_financial_sections() -> None:
    text = render_analysis(
        _result(
            AnalysisStatus.UNSUPPORTED_TICKER,
            "ticker is absent from the authoritative SEC company reference",
        ),
        AnalysisRenderOptions(plain=True),
    )

    assert "UNSUPPORTED TICKER" in text
    assert "ticker is absent from the authoritative SEC company reference" in text
    assert "FINANCIAL" not in text
    assert "VALUATION" not in text


def test_completed_executive_view_prioritizes_expectations_and_business_economics() -> None:
    result = AnalysisOrchestrator(ROOT).analyze("QCOM")
    canonical = result.canonical_result
    assert canonical is not None

    text = render_analysis(result, AnalysisRenderOptions(plain=True, width=88))

    assert "QHAPAQ - QUALCOMM Incorporated (QCOM)" in text
    assert "COMPLETED" in text
    assert "MARKET EXPECTATIONS" in text
    assert "IMPLIED FCF GROWTH" in text
    assert "IMPLIED DISCOUNT RATE" in text
    assert "BUSINESS ECONOMICS" in text
    assert "NORMALIZED FCFF" in text
    assert "ROIC - WACC" in text
    assert "EVIDENCE" in text
    assert "BOTTOM LINE" in text
    assert f"{canonical.valuation['wacc']:.2%}" in text
    assert f"{canonical.valuation['roic']:.2%}" in text
    assert f"{canonical.market_comparison['price']:,.2f}" in text
    assert "SCENARIO SUMMARY" not in text
    assert "BEAR VALUE/SHARE" not in text
    assert "RECONSTRUCTED FCFF" not in text
    assert "NOPAT" not in text
    assert "VALUATION READY" not in text
    assert canonical.content_identity not in text
    assert "BUY" not in text
    assert "SELL" not in text


def test_completed_bottom_line_uses_canonical_spread_and_handles_negative_growth() -> None:
    result = AnalysisOrchestrator(ROOT).analyze("QCOM")
    canonical = result.canonical_result
    assert canonical is not None
    canonical = replace(
        canonical,
        valuation={
            **canonical.valuation,
            "roic": 0.50,
            "wacc": 0.01,
            "roic_minus_wacc": -0.03,
        },
        reverse_valuation={**canonical.reverse_valuation, "implied_growth": -0.052},
    )

    text = render_analysis(
        replace(result, canonical_result=canonical),
        AnalysisRenderOptions(plain=True, width=88),
    )
    normalized = " ".join(text.split())

    assert _rendered_value(text, "IMPLIED FCF GROWTH") == "-5.20%"
    assert "3.00 percentage points below WACC" in normalized
    assert "49.00 percentage points above WACC" not in normalized


def test_completed_non_finite_reverse_dcf_values_render_as_unavailable() -> None:
    result = AnalysisOrchestrator(ROOT).analyze("QCOM")
    canonical = result.canonical_result
    assert canonical is not None
    canonical = replace(
        canonical,
        valuation={**canonical.valuation, "roic_minus_wacc": float("nan")},
        market_comparison={
            **canonical.market_comparison,
            "fcff_implied_discount_rate": float("inf"),
        },
        reverse_valuation={**canonical.reverse_valuation, "implied_growth": float("nan")},
    )

    text = render_analysis(
        replace(result, canonical_result=canonical),
        AnalysisRenderOptions(plain=True, width=88),
    )

    assert _rendered_value(text, "IMPLIED FCF GROWTH") == "Unavailable"
    assert _rendered_value(text, "IMPLIED DISCOUNT RATE") == "Unavailable"
    assert "nan%" not in text.lower()
    assert "inf%" not in text.lower()


def test_completed_header_prefers_canonical_identity_and_sec_fallback_is_sanitized() -> None:
    completed = AnalysisOrchestrator(ROOT).analyze("QCOM")
    completed_text = render_analysis(completed, AnalysisRenderOptions(plain=True))
    assert "QHAPAQ - QUALCOMM Incorporated (QCOM)" in completed_text
    assert "/DE" not in completed_text.splitlines()[0]

    unresolved = _result(
        AnalysisStatus.EVIDENCE_REQUIRED,
        "checksum-verified canonical evidence is not available",
    )
    fallback_identity = replace(unresolved.plan.identity, ticker="ACME", display_name="ACME INC/DE")
    fallback = replace(unresolved, plan=replace(unresolved.plan, identity=fallback_identity))
    fallback_text = render_analysis(fallback, AnalysisRenderOptions(plain=True))

    assert "QHAPAQ - ACME INC (ACME)" in fallback_text
    assert "Acme Inc" not in fallback_text


def test_detail_preserves_executive_view_and_adds_approved_analyst_hierarchy() -> None:
    result = AnalysisOrchestrator(ROOT).analyze("QCOM")
    canonical = result.canonical_result
    assert canonical is not None

    executive = render_analysis(result, AnalysisRenderOptions(plain=True))
    detail = render_analysis(result, AnalysisRenderOptions(detail=True, plain=True))

    headings = (
        "ANALYST DETAIL",
        "FINANCIAL DETAIL",
        "DCF SCENARIOS",
        "EVIDENCE QUALITY",
        "READINESS",
        "PROVENANCE",
        "AUDIT",
    )

    assert detail.startswith(executive.rstrip() + "\n\nANALYST DETAIL\n")
    assert all(heading not in executive for heading in headings)
    lines = detail.splitlines()
    assert [lines.index(heading) for heading in headings] == sorted(
        lines.index(heading) for heading in headings
    )
    assert canonical.content_identity in detail


def test_detail_projects_compact_evidence_quality_without_flattened_internals() -> None:
    result = AnalysisOrchestrator(ROOT).analyze("QCOM")

    detail = render_analysis(result, AnalysisRenderOptions(detail=True, plain=True))

    for label in (
        "CANONICAL FACTS",
        "EVIDENCE SET",
        "PROVENANCE",
        "SOURCE INTEGRITY",
        "EFFECTIVE SOURCE SELECTION",
        "NORMALIZATION",
        "PERIOD SEMANTICS",
        "UNIT SEMANTICS",
        "TTM COMPATIBILITY",
        "GOLDEN FACTS",
        "CRITICAL FACT COMPLETENESS",
        "REPRODUCIBILITY",
    ):
        assert label in detail
    for internal_prefix in (
        "quality.gates[",
        "financial_evidence_quality.",
        "model_requirements.",
        "model_stage_readiness.",
    ):
        assert internal_prefix not in detail
    assert "qcom-fy25-10k" not in detail
    assert "REASON                Unavailable" not in detail
    assert "DIAGNOSTICS           None" not in detail


def test_detail_preserves_failed_evidence_gate_and_reason() -> None:
    result = AnalysisOrchestrator(ROOT).analyze("QCOM")
    canonical = result.canonical_result
    assert canonical is not None
    quality = canonical.financial_evidence["quality"]
    assert isinstance(quality, dict)
    gates = [dict(gate) for gate in quality["gates"]]
    gates[0] = {
        **gates[0],
        "status": "FAIL",
        "failures": ["source lineage is incomplete"],
        "references": ["internal-source-reference"],
    }
    failed_quality = {**quality, "gates": gates, "blocking_failures": ["provenance"]}
    canonical = replace(
        canonical,
        financial_evidence={**canonical.financial_evidence, "quality": failed_quality},
    )

    detail = render_analysis(
        replace(result, canonical_result=canonical),
        AnalysisRenderOptions(detail=True, plain=True),
    )

    assert _rendered_value(detail, "PROVENANCE") == "FAIL"
    assert _rendered_value(detail, "PROVENANCE FAILURE") == "source lineage is incomplete"
    assert "internal-source-reference" not in detail


def test_detail_readiness_uses_unambiguous_human_labels() -> None:
    result = AnalysisOrchestrator(ROOT).analyze("QCOM")

    detail = render_analysis(result, AnalysisRenderOptions(detail=True, plain=True))
    readiness = detail.split("\nREADINESS\n", maxsplit=1)[1].split("\n\nPROVENANCE\n", maxsplit=1)[
        0
    ]

    for label in (
        "RESEARCH",
        "MODEL",
        "CAPITAL STRUCTURE",
        "FCFF",
        "INVESTED CAPITAL",
        "NOPAT",
        "OPERATING MODEL",
        "PER SHARE",
    ):
        assert _rendered_value(readiness, label) == "READY"
    assert "CAPITAL COST READY" not in detail
    assert "VALUATION READY" not in detail
    assert "capital_cost_ready" not in detail
    assert "valuation_ready" not in detail


def test_detail_does_not_convert_false_readiness_to_success() -> None:
    result = AnalysisOrchestrator(ROOT).analyze("QCOM")
    canonical = result.canonical_result
    assert canonical is not None
    model_requirements = canonical.readiness["model_requirements"]
    stage_readiness = canonical.readiness["model_stage_readiness"]
    assert isinstance(model_requirements, dict)
    assert isinstance(stage_readiness, dict)
    readiness = {
        **canonical.readiness,
        "deterministic_research_ready": False,
        "model_requirements": {**model_requirements, "model_ready": False},
        "model_stage_readiness": {
            **stage_readiness,
            "fcff": {**stage_readiness["fcff"], "ready": False},
        },
    }

    detail = render_analysis(
        replace(result, canonical_result=replace(canonical, readiness=readiness)),
        AnalysisRenderOptions(detail=True, plain=True),
    )
    readiness_section = detail.split("\nREADINESS\n", maxsplit=1)[1].split(
        "\n\nPROVENANCE\n", maxsplit=1
    )[0]

    assert _rendered_value(readiness_section, "RESEARCH") == "NOT READY"
    assert _rendered_value(readiness_section, "MODEL") == "NOT READY"
    assert _rendered_value(readiness_section, "FCFF") == "NOT READY"


def test_detail_provenance_omits_unavailable_internal_fields() -> None:
    result = AnalysisOrchestrator(ROOT).analyze("QCOM")

    detail = render_analysis(result, AnalysisRenderOptions(detail=True, plain=True))

    assert _rendered_values(detail, "MARKET SOURCE")[-1] == "Legacy"
    assert _rendered_value(detail, "CURRENCY") == "USD"
    assert _rendered_value(detail, "RESEARCH AS OF") == "2026-09-08"
    assert "canonical_observation_identity" not in detail
    assert "market_quality_identity" not in detail
    assert "price_fact_identity" not in detail


def test_detail_only_shows_scenario_diagnostics_when_present() -> None:
    result = AnalysisOrchestrator(ROOT).analyze("QCOM")
    canonical = result.canonical_result
    assert canonical is not None
    without_diagnostics = render_analysis(
        result,
        AnalysisRenderOptions(detail=True, plain=True),
    )
    with_diagnostics = render_analysis(
        replace(
            result,
            canonical_result=replace(
                canonical,
                valuation={**canonical.valuation, "diagnostics": ["terminal share is elevated"]},
            ),
        ),
        AnalysisRenderOptions(detail=True, plain=True),
    )

    assert "DIAGNOSTICS" not in without_diagnostics
    assert _rendered_value(with_diagnostics, "DIAGNOSTICS") == "terminal share is elevated"


def test_rendering_is_deterministic_for_explicit_options() -> None:
    result = AnalysisOrchestrator(ROOT).analyze("QCOM")
    options = AnalysisRenderOptions(detail=True, plain=True, width=72)

    assert render_analysis(result, options) == render_analysis(result, options)


def test_plain_mode_has_no_ansi_or_unicode_presentation_glyphs() -> None:
    text = render_analysis(
        AnalysisOrchestrator(ROOT).analyze("QCOM"),
        AnalysisRenderOptions(plain=True, color=True),
    )

    assert text.isascii()
    assert "\x1b[" not in text
    for glyph in ("─", "✓", "⚠", "✗"):
        assert glyph not in text


def test_renderer_does_not_invoke_financial_engines(monkeypatch: pytest.MonkeyPatch) -> None:
    result = AnalysisOrchestrator(ROOT).analyze("QCOM")

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("renderer must not calculate finance")

    monkeypatch.setattr("qhapaq_finance.valuation.analyze_case", forbidden)
    monkeypatch.setattr("qhapaq_finance.research_result.build_canonical_research_result", forbidden)

    text = render_analysis(result, AnalysisRenderOptions(detail=True, plain=True))

    assert "COMPLETED" in text


@pytest.mark.parametrize("width", [60, 88])
def test_renderer_wraps_to_explicit_width_except_atomic_tokens(width: int) -> None:
    result = AnalysisOrchestrator(ROOT).analyze("QCOM")
    text = render_analysis(
        result,
        AnalysisRenderOptions(detail=True, plain=True, width=width),
    )

    for line in text.splitlines():
        assert len(line) <= width or any(len(token) > width for token in line.split())


def test_completed_without_canonical_result_does_not_fabricate_financials() -> None:
    result = AnalysisOrchestrator(ROOT).analyze("QCOM")

    text = render_analysis(
        replace(result, canonical_result=None),
        AnalysisRenderOptions(plain=True),
    )

    assert "COMPLETED" in text
    assert "no canonical analysis result is available" in text
    assert "MARKET EXPECTATIONS" not in text


# --- Task 7 acquisition rendering contracts ---


def _task7_acquisition_result(
    result: AnalysisResult,
    state: AnalysisStageState,
    reason: str,
) -> AnalysisResult:
    return replace(
        result,
        plan=replace(
            result.plan,
            acquisition=AnalysisStage(state, reason),
        ),
    )


@pytest.mark.parametrize(
    "reason",
    [
        "SEC fast path canonical evidence verified",
        "SEC filing fallback canonical evidence verified: MISSING_STANDARD_CONCEPT",
    ],
)
def test_task7_renderer_surfaces_completed_sec_acquisition_summary(
    reason: str,
) -> None:
    result = AnalysisOrchestrator(ROOT).analyze("QCOM")
    result = _task7_acquisition_result(
        result,
        AnalysisStageState.COMPLETED,
        reason,
    )

    text = render_analysis(
        result,
        AnalysisRenderOptions(plain=True),
    )

    assert "ACQUISITION" in text
    assert "SEC" in text
    if "fallback" in reason:
        assert "filing fallback canonical evidence verified" in text
        assert "MISSING_STANDARD_CONCEPT" in text
    else:
        assert reason in text


def test_task7_renderer_detail_preserves_typed_fallback_reason() -> None:
    result = AnalysisOrchestrator(ROOT).analyze("QCOM")
    result = _task7_acquisition_result(
        result,
        AnalysisStageState.COMPLETED,
        "SEC filing fallback canonical evidence verified: MISSING_STANDARD_CONCEPT",
    )

    text = render_analysis(
        result,
        AnalysisRenderOptions(detail=True, plain=True),
    )

    assert "ACQUISITION" in text
    assert "MISSING_STANDARD_CONCEPT" in text


def test_task7_evidence_required_after_acquisition_avoids_manual_sec_instruction() -> None:
    result = _result(
        AnalysisStatus.EVIDENCE_REQUIRED,
        "SEC canonical evidence gap after fallback: REQUIRED_COMPONENT_MISSING",
    )
    result = _task7_acquisition_result(
        result,
        AnalysisStageState.COMPLETED,
        "SEC canonical evidence gap after fallback: REQUIRED_COMPONENT_MISSING",
    )

    text = render_analysis(
        result,
        AnalysisRenderOptions(plain=True),
    )

    assert "ACQUISITION" in text
    assert "SEC acquisition" in text
    assert "Acquire and verify the missing SEC evidence." not in text


def test_task7_blocked_after_sec_acquisition_has_sec_oriented_next_action() -> None:
    result = _result(
        AnalysisStatus.BLOCKED,
        "SEC acquisition or canonicalization could not complete",
    )
    result = _task7_acquisition_result(
        result,
        AnalysisStageState.BLOCKED,
        "SEC acquisition or canonicalization could not complete",
    )

    text = render_analysis(
        result,
        AnalysisRenderOptions(plain=True),
    )

    assert "BLOCKED" in text
    assert "\nNEXT\n" in text

    next_section = text.split("\nNEXT\n", maxsplit=1)[1]
    assert "SEC" in next_section

    assert "Traceback" not in text
    assert "RuntimeError" not in text


def test_completed_acquisition_does_not_render_stale_preexecution_evidence() -> None:
    result = _result(
        AnalysisStatus.EVIDENCE_REQUIRED,
        "SEC canonical evidence gap after fallback: MISSING_STANDARD_CONCEPT",
    )
    result = _task7_acquisition_result(
        result,
        AnalysisStageState.COMPLETED,
        "SEC canonical evidence gap after fallback: MISSING_STANDARD_CONCEPT",
    )

    text = render_analysis(
        result,
        AnalysisRenderOptions(plain=True),
    )

    assert "Latest 10-K" not in text
    assert "Latest 10-Q" not in text
    assert "Automatic SEC acquisition already ran" in text
    assert "MISSING_STANDARD_CONCEPT" in text


def test_completed_acquisition_detail_reports_post_acquisition_gap_not_stale_plan() -> None:
    result = _result(
        AnalysisStatus.EVIDENCE_REQUIRED,
        "SEC canonical evidence gap after fallback: MISSING_STANDARD_CONCEPT",
    )
    result = _task7_acquisition_result(
        result,
        AnalysisStageState.COMPLETED,
        "SEC canonical evidence gap after fallback: MISSING_STANDARD_CONCEPT",
    )

    text = render_analysis(
        result,
        AnalysisRenderOptions(detail=True, plain=True),
    )

    assert "POST-ACQUISITION EVIDENCE" in text
    assert "MISSING_STANDARD_CONCEPT" in text
    assert "LATEST 10-K" not in text
    assert "LATEST 10-Q" not in text
