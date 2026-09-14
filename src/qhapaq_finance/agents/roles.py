"""Logical agent responsibilities; providers implement only Analyst and Challenger calls today."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AgentRole(str, Enum):
    EVIDENCE_SCOUT = "evidence_scout"
    EVIDENCE_AUDITOR = "evidence_auditor"
    RESEARCH_ANALYST = "research_analyst"
    THESIS_CHALLENGER = "thesis_challenger"
    CROSS_SECTIONAL_REVIEWER = "cross_sectional_reviewer"


ROLE_BOUNDARIES = {
    AgentRole.EVIDENCE_SCOUT: "May identify candidate provenance; never writes canonical finance.",
    AgentRole.EVIDENCE_AUDITOR: (
        "Gates provenance and reporting compatibility; never repairs numbers by guesswork."
    ),
    AgentRole.RESEARCH_ANALYST: "Synthesizes only validated deterministic evidence.",
    AgentRole.THESIS_CHALLENGER: "Challenges a thesis using only allowed evidence references.",
    AgentRole.CROSS_SECTIONAL_REVIEWER: (
        "Compares completed validated artifacts; never recomputes canonical finance."
    ),
}


@dataclass(frozen=True)
class EvidenceAuditFinding:
    """Non-authoritative diagnostic output for a future Evidence Auditor agent.

    Findings may point a human or deterministic configuration at a problem. They
    cannot carry a replacement value, alter quality gates, or mark research ready.
    """

    code: str
    explanation: str
    source_references: tuple[str, ...]
    severity: str
