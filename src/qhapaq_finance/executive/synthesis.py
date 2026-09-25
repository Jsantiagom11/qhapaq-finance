"""Pure translation of already-validated Executive Shortlist DTOs."""

from __future__ import annotations

from dataclasses import dataclass

from qhapaq_finance.diamond.archetypes import Archetype

from .contracts import (
    ExecutiveAnalysisStatus,
    ExecutiveContradiction,
    ExecutiveEvidence,
    ImpliedExpectationResult,
)


@dataclass(frozen=True)
class ExecutiveSynthesis:
    """Deterministic translation with no acquisition or valuation."""

    surfaced_by: Archetype
    evidence_dtos: tuple[ExecutiveEvidence, ...]
    contradictions_dtos: tuple[ExecutiveContradiction, ...]
    analysis_status: ExecutiveAnalysisStatus
    expectation_result: ImpliedExpectationResult | None

    @property
    def bottom_line(self) -> str | None:
        """Expose only an upstream conclusion explicitly marked available."""
        if not self.analysis_status.conclusion_available:
            return None
        return self.analysis_status.bottom_line

    @staticmethod
    def translate(
        *,
        surfaced_by: Archetype,
        evidence_dtos: tuple[ExecutiveEvidence, ...],
        contradictions_dtos: tuple[ExecutiveContradiction, ...],
        analysis_status: ExecutiveAnalysisStatus,
        expectation_result: ImpliedExpectationResult | None,
    ) -> ExecutiveSynthesis:
        """Translate supplied DTOs without parsing, sorting, I/O, or recalculation."""
        return ExecutiveSynthesis(
            surfaced_by=surfaced_by,
            evidence_dtos=evidence_dtos,
            contradictions_dtos=contradictions_dtos,
            analysis_status=analysis_status,
            expectation_result=expectation_result,
        )
