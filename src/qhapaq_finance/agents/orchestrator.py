"""Explicit, offline-testable sequencing for the agent research vertical slice."""
# ruff: noqa: E501

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .contracts import ResearchSynthesis, ThesisChallenge, contract_dict
from .interpretation import DeterministicInterpretation, interpret_artifact
from .provider import AgentProvider
from .validation import NumericalClaimValidator, ValidationResult


class AgentPipelineError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentResearchArtifact:
    schema_version: str
    ticker: str
    deterministic_artifact_ref: str
    deterministic_interpretation: DeterministicInterpretation
    synthesis: ResearchSynthesis
    challenge: ThesisChallenge
    validation: dict[str, ValidationResult]
    provenance: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ticker": self.ticker,
            "deterministic_artifact_ref": self.deterministic_artifact_ref,
            "deterministic_interpretation": self.deterministic_interpretation.to_dict(),
            "synthesis": contract_dict(self.synthesis),
            "challenge": contract_dict(self.challenge),
            "validation": {name: result.to_dict() for name, result in self.validation.items()},
            "provenance": self.provenance,
        }


class ResearchOrchestrator:
    def __init__(
        self, provider: AgentProvider, validator: NumericalClaimValidator | None = None
    ) -> None:
        self._provider = provider
        self._validator = validator or NumericalClaimValidator()

    def investigate(self, artifact: dict[str, Any]) -> AgentResearchArtifact:
        deterministic_artifact = deepcopy(artifact)
        interpretation = interpret_artifact(deterministic_artifact)
        synthesis = self._synthesize(deepcopy(deterministic_artifact), interpretation)
        synthesis_validation = self._validator.validate(
            synthesis, deterministic_artifact, interpretation
        )
        if not synthesis_validation.valid:
            raise AgentPipelineError(
                f"synthesis numerical validation failed: {synthesis_validation.failures}"
            )
        challenge = self._challenge(
            deepcopy(deterministic_artifact), interpretation, deepcopy(synthesis)
        )
        challenge_validation = self._validator.validate(
            challenge, deterministic_artifact, interpretation
        )
        if not challenge_validation.valid:
            raise AgentPipelineError(
                f"challenge numerical validation failed: {challenge_validation.failures}"
            )
        ticker = str(deterministic_artifact["identity"]["ticker"])
        if synthesis.ticker != ticker:
            raise AgentPipelineError("synthesis ticker does not match deterministic artifact")
        return AgentResearchArtifact(
            schema_version="agent-research-v1",
            ticker=ticker,
            deterministic_artifact_ref="dashboard-research-v1",
            deterministic_interpretation=interpretation,
            synthesis=synthesis,
            challenge=challenge,
            validation={"synthesis": synthesis_validation, "challenge": challenge_validation},
            provenance={
                "provider": type(self._provider).__name__,
                "network": "provider-boundary-only",
            },
        )

    def _synthesize(
        self, artifact: dict[str, Any], interpretation: DeterministicInterpretation
    ) -> ResearchSynthesis:
        try:
            result = self._provider.synthesize(artifact, interpretation)
        except Exception as exc:
            raise AgentPipelineError("synthesis provider failed") from exc
        if not isinstance(result, ResearchSynthesis):
            raise AgentPipelineError("synthesis provider returned malformed structured output")
        return result

    def _challenge(
        self,
        artifact: dict[str, Any],
        interpretation: DeterministicInterpretation,
        synthesis: ResearchSynthesis,
    ) -> ThesisChallenge:
        try:
            result = self._provider.challenge(artifact, interpretation, synthesis)
        except Exception as exc:
            raise AgentPipelineError("challenge provider failed") from exc
        if not isinstance(result, ThesisChallenge):
            raise AgentPipelineError("challenge provider returned malformed structured output")
        return result
