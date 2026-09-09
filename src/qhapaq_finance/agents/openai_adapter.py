"""Optional OpenAI Agents SDK adapter; the only OpenAI-specific module."""
# ruff: noqa: E501

from __future__ import annotations

import json
from typing import Any, cast

from .contracts import ResearchSynthesis, ThesisChallenge
from .interpretation import DeterministicInterpretation
from .validation import evidence_catalog


class OpenAIAgentsProvider:
    """Use structured SDK outputs without leaking SDK types into Qhapaq's domain."""

    def __init__(self, model: str = "gpt-4.1-mini") -> None:
        self._model = model

    def synthesize(
        self, artifact: dict[str, object], interpretation: DeterministicInterpretation
    ) -> ResearchSynthesis:
        catalog = evidence_catalog(artifact, interpretation)
        return cast(
            ResearchSynthesis,
            self._run(
                name="Qhapaq Research Synthesis",
                instructions=(
                    "Interpret only supplied deterministic evidence. Do not calculate, invent, or "
                    "change financial facts. All prose must be qualitative: place every number in "
                    "numeric_claims with an explicit evidence_ref. Use ONLY ALLOWED_EVIDENCE; "
                    "never invent or infer paths. Copy its exact path, metric label, value, and unit."
                ),
                output_type=ResearchSynthesis,
                payload={
                    "artifact": artifact,
                    "interpretation": interpretation.to_dict(),
                    "ALLOWED_EVIDENCE": [entry.to_dict() for entry in catalog],
                },
            ),
        )

    def challenge(
        self,
        artifact: dict[str, object],
        interpretation: DeterministicInterpretation,
        synthesis: ResearchSynthesis,
    ) -> ThesisChallenge:
        catalog = evidence_catalog(artifact, interpretation)
        return cast(
            ThesisChallenge,
            self._run(
                name="Qhapaq Thesis Challenge",
                instructions=(
                    "Adversarially challenge the supplied thesis using only supplied deterministic "
                    "evidence. Do not calculate or invent financial facts. Put every number in "
                    "numeric_claims with an explicit evidence_ref. Use ONLY ALLOWED_EVIDENCE; "
                    "never invent or infer paths. Copy its exact path, metric label, value, and unit."
                ),
                output_type=ThesisChallenge,
                payload={
                    "artifact": artifact,
                    "interpretation": interpretation.to_dict(),
                    "synthesis": synthesis,
                    "ALLOWED_EVIDENCE": [entry.to_dict() for entry in catalog],
                },
            ),
        )

    def _run(self, *, name: str, instructions: str, output_type: Any, payload: object) -> object:
        try:
            from agents import Agent, Runner  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - depends on optional installation
            raise RuntimeError(
                "OpenAI adapter requires the optional 'agents' dependency: uv sync --extra agents"
            ) from exc
        agent = Agent(
            name=name, instructions=instructions, model=self._model, output_type=output_type
        )
        result = Runner.run_sync(agent, json.dumps(payload, default=str, sort_keys=True))
        return result.final_output
