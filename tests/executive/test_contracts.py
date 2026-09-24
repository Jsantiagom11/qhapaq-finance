from __future__ import annotations

import importlib
import math
from dataclasses import FrozenInstanceError
from datetime import date
from types import ModuleType

import pytest

from qhapaq_finance.analysis import AnalysisStatus
from qhapaq_finance.diamond.archetypes import Archetype


def _contracts() -> ModuleType:
    try:
        return importlib.import_module("qhapaq_finance.executive.contracts")
    except ModuleNotFoundError as exc:
        pytest.fail(
            f"executive contracts module missing: {exc}",
            pytrace=False,
        )


def _evidence(module: ModuleType, **overrides: object) -> object:
    values: dict[str, object] = {
        "metric_id": "revenue_ttm",
        "value": 100.0,
        "period_end": date(2026, 6, 30),
        "source_identity": "sec:0000000000:10-Q:2026-06-30",
        "status": "VALIDATED",
    }
    values.update(overrides)
    return module.ExecutiveEvidence(**values)


def _contradiction(module: ModuleType, **overrides: object) -> object:
    values: dict[str, object] = {
        "flag_id": "growth-vs-expectations",
        "severity": "MATERIAL",
        "description": "Observed growth differs from the implied expectation.",
    }
    values.update(overrides)
    return module.ExecutiveContradiction(**values)


def _analysis_status(module: ModuleType, **overrides: object) -> object:
    values: dict[str, object] = {
        "source_status": AnalysisStatus.COMPLETED,
        "conclusion_available": True,
        "reason": None,
    }
    values.update(overrides)
    return module.ExecutiveAnalysisStatus(**values)


def _expectation(module: ModuleType, **overrides: object) -> object:
    values: dict[str, object] = {
        "implied_fcff_growth": 0.08,
        "starting_fcff": 100.0,
        "years": 10,
        "observed_enterprise_value": 1_000.0,
        "solved_enterprise_value": 1_000.5,
        "relative_error": 0.0005,
        "hurdle_rate": 0.094,
        "terminal_growth_rate": 0.03,
        "lower_bound": -0.30,
        "upper_bound": 0.70,
        "iterations": 12,
        "status": module.ImpliedExpectationStatus.SOLVED,
        "reason": None,
    }
    values.update(overrides)
    return module.ImpliedExpectationResult(**values)


def _entry(module: ModuleType, **overrides: object) -> object:
    values: dict[str, object] = {
        "ticker": "QCOM",
        "surfaced_by": Archetype.QUALITY_VALUE,
        "research_priority": 0.91,
        "why_it_surfaced": "Diamond surfaced the company as QUALITY_VALUE.",
        "evidence": (_evidence(module),),
        "contradictions": (_contradiction(module),),
        "analysis_status": _analysis_status(module),
        "expectations": _expectation(module),
        "bottom_line": "Evidence supports a complete executive conclusion.",
    }
    values.update(overrides)
    return module.ExecutiveShortlistEntry(**values)


def test_implied_expectation_status_is_frozen_v01_contract() -> None:
    module = _contracts()

    assert tuple(item.value for item in module.ImpliedExpectationStatus) == (
        "SOLVED",
        "NO_SOLUTION_IN_RANGE",
        "INPUTS_UNAVAILABLE",
    )


@pytest.mark.parametrize(
    "field",
    ("metric_id", "source_identity", "status"),
)
def test_evidence_rejects_empty_required_strings(field: str) -> None:
    module = _contracts()

    with pytest.raises(ValueError, match="non-empty"):
        _evidence(module, **{field: "   "})


@pytest.mark.parametrize("value", (math.nan, math.inf, -math.inf))
def test_evidence_rejects_non_finite_value(value: float) -> None:
    module = _contracts()

    with pytest.raises(ValueError, match="finite"):
        _evidence(module, value=value)


def test_evidence_allows_explicitly_missing_numeric_value() -> None:
    module = _contracts()

    value = _evidence(
        module,
        value=None,
        period_end=None,
        status="MISSING",
    )

    assert value.value is None
    assert value.period_end is None


@pytest.mark.parametrize(
    "field",
    ("flag_id", "severity", "description"),
)
def test_contradiction_rejects_empty_required_strings(field: str) -> None:
    module = _contracts()

    with pytest.raises(ValueError, match="non-empty"):
        _contradiction(module, **{field: ""})


def test_analysis_status_preserves_existing_fail_closed_status() -> None:
    module = _contracts()

    value = _analysis_status(
        module,
        source_status=AnalysisStatus.EVIDENCE_REQUIRED,
        conclusion_available=False,
        reason="Canonical evidence is incomplete.",
    )

    assert value.source_status is AnalysisStatus.EVIDENCE_REQUIRED
    assert value.conclusion_available is False


def test_analysis_status_rejects_empty_optional_reason() -> None:
    module = _contracts()

    with pytest.raises(ValueError, match="non-empty"):
        _analysis_status(module, reason=" ")


@pytest.mark.parametrize(
    "field",
    (
        "implied_fcff_growth",
        "starting_fcff",
        "observed_enterprise_value",
        "solved_enterprise_value",
        "relative_error",
        "hurdle_rate",
        "terminal_growth_rate",
        "lower_bound",
        "upper_bound",
    ),
)
@pytest.mark.parametrize("value", (math.nan, math.inf, -math.inf))
def test_expectation_rejects_non_finite_numeric_values(
    field: str,
    value: float,
) -> None:
    module = _contracts()

    with pytest.raises(ValueError, match="finite"):
        _expectation(module, **{field: value})


def test_expectation_allows_unsolved_growth_to_be_none() -> None:
    module = _contracts()

    value = _expectation(
        module,
        implied_fcff_growth=None,
        status=module.ImpliedExpectationStatus.NO_SOLUTION_IN_RANGE,
        reason="No root exists inside the bounded search interval.",
    )

    assert value.implied_fcff_growth is None


@pytest.mark.parametrize(
    "field",
    ("ticker", "why_it_surfaced"),
)
def test_shortlist_entry_rejects_empty_required_strings(field: str) -> None:
    module = _contracts()

    with pytest.raises(ValueError, match="non-empty"):
        _entry(module, **{field: " "})


@pytest.mark.parametrize("value", (math.nan, math.inf, -math.inf))
def test_shortlist_entry_rejects_non_finite_priority(value: float) -> None:
    module = _contracts()

    with pytest.raises(ValueError, match="finite"):
        _entry(module, research_priority=value)


def test_incomplete_analysis_cannot_publish_bottom_line() -> None:
    module = _contracts()

    incomplete = _analysis_status(
        module,
        source_status=AnalysisStatus.EVIDENCE_REQUIRED,
        conclusion_available=False,
        reason="Evidence is incomplete.",
    )

    with pytest.raises(ValueError, match="bottom_line"):
        _entry(
            module,
            analysis_status=incomplete,
            bottom_line="This conclusion must not leak.",
        )


def test_incomplete_analysis_accepts_none_bottom_line() -> None:
    module = _contracts()

    incomplete = _analysis_status(
        module,
        source_status=AnalysisStatus.BLOCKED,
        conclusion_available=False,
        reason="Analysis is blocked.",
    )

    value = _entry(
        module,
        analysis_status=incomplete,
        expectations=None,
        bottom_line=None,
    )

    assert value.bottom_line is None


def test_optional_bottom_line_rejects_blank_text() -> None:
    module = _contracts()

    with pytest.raises(ValueError, match="non-empty"):
        _entry(module, bottom_line="   ")


def test_contracts_are_frozen() -> None:
    module = _contracts()
    value = _entry(module)

    with pytest.raises(FrozenInstanceError):
        value.ticker = "NVDA"  # type: ignore[misc]
