"""Narrow boundary that keeps provider and network dependencies out of the domain."""

from __future__ import annotations

from typing import Protocol

from .contracts import ResearchSynthesis, ThesisChallenge
from .interpretation import DeterministicInterpretation


class AgentProvider(Protocol):
    def synthesize(
        self, artifact: dict[str, object], interpretation: DeterministicInterpretation
    ) -> ResearchSynthesis: ...

    def challenge(
        self,
        artifact: dict[str, object],
        interpretation: DeterministicInterpretation,
        synthesis: ResearchSynthesis,
    ) -> ThesisChallenge: ...
