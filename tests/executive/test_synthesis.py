from __future__ import annotations

import ast
import importlib
import inspect
from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path
from types import ModuleType

import pytest

from qhapaq_finance.analysis import AnalysisStatus
from qhapaq_finance.diamond.archetypes import Archetype
from qhapaq_finance.executive.contracts import (
    ExecutiveAnalysisStatus,
    ExecutiveContradiction,
    ExecutiveEvidence,
    ImpliedExpectationResult,
    ImpliedExpectationStatus,
)

FORBIDDEN_IMPORT_FRAGMENTS = (
    "qhapaq_finance.analysis",
    "qhapaq_finance.valuation",
    "qhapaq_finance.executive.goal_seek",
    "qhapaq_finance.agents.orchestrator",
    "qhapaq_finance.sec_client",
    "qhapaq_finance.market_provider",
    "qhapaq_finance.diamond.providers",
)

FORBIDDEN_IMPORTED_NAMES = (
    "AnalysisOrchestrator",
    "run_valuation",
    "present_value_fcff",
    "solve_implied_fcff_growth",
)

FORBIDDEN_IO_CALLS = (
    "open",
    "print",
    "input",
)


def _synthesis_module() -> ModuleType:
    try:
        return importlib.import_module("qhapaq_finance.executive.synthesis")
    except ModuleNotFoundError as exc:
        pytest.fail(f"synthesis module missing: {exc}", pytrace=False)


def _evidence(
    metric_id: str = "revenue_ttm",
    value: float | None = 100.0,
) -> ExecutiveEvidence:
    return ExecutiveEvidence(
        metric_id=metric_id,
        value=value,
        period_end=date(2026, 6, 30),
        source_identity=f"sec:{metric_id}",
        status="VALIDATED",
    )


def _contradiction(
    flag_id: str = "growth-vs-expectations",
) -> ExecutiveContradiction:
    return ExecutiveContradiction(
        flag_id=flag_id,
        severity="MATERIAL",
        description=f"Contradiction {flag_id}",
    )


def _expectation() -> ImpliedExpectationResult:
    return ImpliedExpectationResult(
        implied_fcff_growth=0.08,
        starting_fcff=100.0,
        hurdle_rate=0.094,
        terminal_growth_rate=0.03,
        years=10,
        observed_enterprise_value=1_000.0,
        solved_enterprise_value=1_000.5,
        relative_error=0.0005,
        lower_bound=-0.30,
        upper_bound=0.70,
        iterations=12,
        status=ImpliedExpectationStatus.SOLVED,
        reason=None,
    )


def _completed_status(
    bottom_line: str | None = "Validated executive conclusion.",
) -> ExecutiveAnalysisStatus:
    return ExecutiveAnalysisStatus(
        source_status=AnalysisStatus.COMPLETED,
        conclusion_available=True,
        reason=None,
        bottom_line=bottom_line,
    )


def _blocked_status() -> ExecutiveAnalysisStatus:
    return ExecutiveAnalysisStatus(
        source_status=AnalysisStatus.EVIDENCE_REQUIRED,
        conclusion_available=False,
        reason="Canonical evidence is incomplete.",
        bottom_line=None,
    )


def _assert_architecture_clean(source: str) -> None:
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if any(fragment in alias.name for fragment in FORBIDDEN_IMPORT_FRAGMENTS):
                    raise AssertionError(f"forbidden dependency import: {alias.name}")

        if isinstance(node, ast.ImportFrom):
            module = node.module or ""

            if any(fragment in module for fragment in FORBIDDEN_IMPORT_FRAGMENTS):
                raise AssertionError(f"forbidden dependency import: {module}")

            imported_names = {alias.name for alias in node.names}
            forbidden = imported_names.intersection(FORBIDDEN_IMPORTED_NAMES)
            if forbidden:
                name = sorted(forbidden)[0]
                raise AssertionError(f"forbidden imported symbol: {name}")

        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in FORBIDDEN_IO_CALLS
        ):
            raise AssertionError(f"forbidden I/O call: {node.func.id}")


def test_analysis_status_carries_validated_bottom_line() -> None:
    status = _completed_status("Validated conclusion.")

    assert status.bottom_line == "Validated conclusion."


def test_analysis_status_rejects_bottom_line_when_conclusion_unavailable() -> None:
    with pytest.raises(ValueError, match="bottom_line"):
        ExecutiveAnalysisStatus(
            source_status=AnalysisStatus.EVIDENCE_REQUIRED,
            conclusion_available=False,
            reason="Evidence is incomplete.",
            bottom_line="Must not leak.",
        )


def test_translate_signature_is_exact_five_input_contract() -> None:
    module = _synthesis_module()

    assert list(inspect.signature(module.ExecutiveSynthesis.translate).parameters) == [
        "surfaced_by",
        "evidence_dtos",
        "contradictions_dtos",
        "analysis_status",
        "expectation_result",
    ]


def test_translate_preserves_supplied_dtos_without_recalculation() -> None:
    module = _synthesis_module()

    evidence = (
        _evidence("revenue_ttm", 100.0),
        _evidence("fcff_ttm", 25.0),
    )
    contradictions = (
        _contradiction("growth-gap"),
        _contradiction("terminal-dependence"),
    )
    status = _completed_status()
    expectation = _expectation()

    result = module.ExecutiveSynthesis.translate(
        surfaced_by=Archetype.QUALITY_VALUE,
        evidence_dtos=evidence,
        contradictions_dtos=contradictions,
        analysis_status=status,
        expectation_result=expectation,
    )

    assert result.surfaced_by is Archetype.QUALITY_VALUE

    # Pure translation: preserve the exact already-built DTOs.
    assert result.evidence_dtos is evidence
    assert result.contradictions_dtos is contradictions
    assert result.analysis_status is status
    assert result.expectation_result is expectation


def test_translate_preserves_input_order_exactly() -> None:
    module = _synthesis_module()

    evidence = (
        _evidence("z-last-upstream"),
        _evidence("a-first-upstream"),
    )
    contradictions = (
        _contradiction("z-flag"),
        _contradiction("a-flag"),
    )

    result = module.ExecutiveSynthesis.translate(
        surfaced_by=Archetype.INFLECTION,
        evidence_dtos=evidence,
        contradictions_dtos=contradictions,
        analysis_status=_completed_status(),
        expectation_result=_expectation(),
    )

    assert tuple(item.metric_id for item in result.evidence_dtos) == (
        "z-last-upstream",
        "a-first-upstream",
    )
    assert tuple(item.flag_id for item in result.contradictions_dtos) == (
        "z-flag",
        "a-flag",
    )


def test_bottom_line_is_only_translated_from_analysis_status() -> None:
    module = _synthesis_module()
    status = _completed_status("Canonical validated conclusion.")

    result = module.ExecutiveSynthesis.translate(
        surfaced_by=Archetype.COMPOUNDER,
        evidence_dtos=(),
        contradictions_dtos=(),
        analysis_status=status,
        expectation_result=None,
    )

    assert result.bottom_line == "Canonical validated conclusion."


def test_bottom_line_fails_closed_when_conclusion_unavailable() -> None:
    module = _synthesis_module()

    result = module.ExecutiveSynthesis.translate(
        surfaced_by=Archetype.INFLECTION,
        evidence_dtos=(),
        contradictions_dtos=(),
        analysis_status=_blocked_status(),
        expectation_result=None,
    )

    assert result.bottom_line is None


def test_translation_is_deterministic_and_frozen() -> None:
    module = _synthesis_module()

    kwargs = {
        "surfaced_by": Archetype.QUALITY_VALUE,
        "evidence_dtos": (_evidence(),),
        "contradictions_dtos": (_contradiction(),),
        "analysis_status": _completed_status(),
        "expectation_result": _expectation(),
    }

    first = module.ExecutiveSynthesis.translate(**kwargs)
    second = module.ExecutiveSynthesis.translate(**kwargs)

    assert first == second

    with pytest.raises(FrozenInstanceError):
        first.surfaced_by = Archetype.INFLECTION  # type: ignore[misc]


@pytest.mark.parametrize(
    "illegal_source",
    (
        "from qhapaq_finance.analysis import AnalysisOrchestrator",
        "from qhapaq_finance.valuation import run_valuation",
        ("from qhapaq_finance.executive.goal_seek import solve_implied_fcff_growth"),
        ("from qhapaq_finance.diamond.providers.market import MarketProvider"),
        "print('side effect')",
    ),
)
def test_architecture_detector_rejects_synthetic_illegal_source(
    illegal_source: str,
) -> None:
    with pytest.raises(AssertionError, match="forbidden"):
        _assert_architecture_clean(illegal_source)


def test_real_synthesis_module_respects_architecture_boundary() -> None:
    module = _synthesis_module()
    source = Path(module.__file__).read_text()

    _assert_architecture_clean(source)


def test_real_synthesis_module_contains_no_financial_arithmetic() -> None:
    module = _synthesis_module()
    source = Path(module.__file__).read_text()
    tree = ast.parse(source)

    forbidden_arithmetic_ops = (
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.FloorDiv,
        ast.Mod,
        ast.Pow,
        ast.MatMult,
    )

    assert not any(
        isinstance(node, ast.BinOp) and isinstance(node.op, forbidden_arithmetic_ops)
        for node in ast.walk(tree)
    )
    assert not any(isinstance(node, ast.AugAssign) for node in ast.walk(tree))
