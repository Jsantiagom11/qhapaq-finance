"""Immutable contracts for the Executive Shortlist pipeline."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from qhapaq_finance.analysis import AnalysisStatus
from qhapaq_finance.diamond.archetypes import Archetype
from qhapaq_finance.string_enum import StringEnum


class ImpliedExpectationStatus(StringEnum):
    """Outcome of the bounded implied-expectation solve."""

    SOLVED = "SOLVED"
    NO_SOLUTION_IN_RANGE = "NO_SOLUTION_IN_RANGE"
    INPUTS_UNAVAILABLE = "INPUTS_UNAVAILABLE"


def _required_text(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} must be a non-empty string")


def _optional_text(value: str | None, field: str) -> None:
    if value is not None:
        _required_text(value, field)


def _finite(value: float, field: str) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{field} must be finite")


def _optional_finite(value: float | None, field: str) -> None:
    if value is not None:
        _finite(value, field)


@dataclass(frozen=True)
class ExecutiveEvidence:
    """One executive-facing evidence item with stable provenance."""

    metric_id: str
    value: float | None
    period_end: date | None
    source_identity: str
    status: str

    def __post_init__(self) -> None:
        _required_text(self.metric_id, "metric_id")
        _optional_finite(self.value, "value")
        _required_text(self.source_identity, "source_identity")
        _required_text(self.status, "status")


@dataclass(frozen=True)
class ExecutiveContradiction:
    """One traceable contradiction exposed by deep analysis."""

    flag_id: str
    severity: str
    description: str

    def __post_init__(self) -> None:
        _required_text(self.flag_id, "flag_id")
        _required_text(self.severity, "severity")
        _required_text(self.description, "description")


@dataclass(frozen=True)
class ExecutiveAnalysisStatus:
    """Executive projection of the canonical analysis state."""

    source_status: AnalysisStatus
    conclusion_available: bool
    reason: str | None

    def __post_init__(self) -> None:
        _optional_text(self.reason, "reason")


@dataclass(frozen=True)
class ImpliedExpectationResult:
    """Bounded revenue-growth expectation and fixed assumptions."""

    implied_revenue_growth_cagr: float | None
    operating_margin_assumption: float
    hurdle_rate: float
    terminal_growth_rate: float
    lower_bound: float
    upper_bound: float
    iterations: int
    status: ImpliedExpectationStatus
    reason: str | None

    def __post_init__(self) -> None:
        _optional_finite(
            self.implied_revenue_growth_cagr,
            "implied_revenue_growth_cagr",
        )
        _finite(
            self.operating_margin_assumption,
            "operating_margin_assumption",
        )
        _finite(self.hurdle_rate, "hurdle_rate")
        _finite(self.terminal_growth_rate, "terminal_growth_rate")
        _finite(self.lower_bound, "lower_bound")
        _finite(self.upper_bound, "upper_bound")
        _optional_text(self.reason, "reason")


@dataclass(frozen=True)
class ExecutiveShortlistEntry:
    """One Diamond-selected company enriched without re-ranking."""

    ticker: str
    surfaced_by: Archetype
    research_priority: float
    why_it_surfaced: str
    evidence: tuple[ExecutiveEvidence, ...]
    contradictions: tuple[ExecutiveContradiction, ...]
    analysis_status: ExecutiveAnalysisStatus
    expectations: ImpliedExpectationResult | None
    bottom_line: str | None

    def __post_init__(self) -> None:
        _required_text(self.ticker, "ticker")
        _finite(self.research_priority, "research_priority")
        _required_text(self.why_it_surfaced, "why_it_surfaced")
        _optional_text(self.bottom_line, "bottom_line")

        if not self.analysis_status.conclusion_available and self.bottom_line is not None:
            raise ValueError("bottom_line must be None when conclusion_available is False")
