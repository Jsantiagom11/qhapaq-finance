"""Bounded, auditable acquisition decisions above staging-only providers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

from .evidence_orchestration import (
    AcquisitionCoordinator,
    AcquisitionProvider,
    EvidenceItem,
    EvidencePlan,
    EvidenceRequirement,
    EvidenceState,
)


class AcquisitionStrategy(str, Enum):
    DETERMINISTIC = "DETERMINISTIC"
    AGENT = "AGENT"
    RECOVERY = "RECOVERY"


class AcquisitionOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    TRANSIENT_FAILURE = "TRANSIENT_FAILURE"
    RATE_LIMITED = "RATE_LIMITED"
    MALFORMED = "MALFORMED"
    NOT_FOUND = "NOT_FOUND"
    SOURCE_CHANGED = "SOURCE_CHANGED"
    UNSUPPORTED = "UNSUPPORTED"
    BLOCKED = "BLOCKED"


class RecoveryAction(str, Enum):
    RETRY = "RETRY"
    TRY_ALTERNATIVE = "TRY_ALTERNATIVE"
    STOP = "STOP"


@dataclass(frozen=True)
class ProviderCapability:
    provider: str
    artifact_kinds: tuple[str, ...]


@dataclass(frozen=True)
class AcquisitionAction:
    requirement_id: str
    provider: str
    strategy: AcquisitionStrategy
    reason: str


@dataclass(frozen=True)
class AcquisitionAttempt:
    action: AcquisitionAction
    ordinal: int
    outcome: AcquisitionOutcome
    detail: str


@dataclass(frozen=True)
class RecoveryPlan:
    action: RecoveryAction
    max_attempts: int
    stop_when: tuple[AcquisitionOutcome, ...]
    reason: str


@dataclass(frozen=True)
class AcquisitionDecision:
    actions: tuple[AcquisitionAction, ...]
    recovery: RecoveryPlan


class AcquisitionAgent:
    """Optional bounded chooser: it receives descriptors, never providers or clients."""

    def select(
        self,
        requirements: Sequence[EvidenceRequirement],
        capabilities: Sequence[ProviderCapability],
    ) -> tuple[AcquisitionAction, ...]:
        choices: list[AcquisitionAction] = []
        for requirement in requirements:
            available = [
                item for item in capabilities if requirement.artifact_kind in item.artifact_kinds
            ]
            if len(available) == 1:
                choices.append(
                    AcquisitionAction(
                        requirement.identifier,
                        available[0].provider,
                        AcquisitionStrategy.AGENT,
                        "only permitted provider",
                    )
                )
        return tuple(choices)


class ProviderRegistry:
    """Closed provider registry; unregistered providers cannot be selected."""

    def __init__(
        self, providers: Mapping[str, tuple[AcquisitionProvider, ProviderCapability]]
    ) -> None:
        self._providers = dict(providers)
        if any(name != capability.provider for name, (_, capability) in self._providers.items()):
            raise ValueError("provider registry names must match capabilities")

    @property
    def capabilities(self) -> tuple[ProviderCapability, ...]:
        return tuple(capability for _, capability in self._providers.values())

    def candidates(self, requirement: EvidenceRequirement) -> tuple[str, ...]:
        return tuple(
            name
            for name, (_, capability) in self._providers.items()
            if requirement.artifact_kind in capability.artifact_kinds
            and (requirement.provider == "ANY" or requirement.provider == name)
        )

    def provider(self, name: str) -> AcquisitionProvider | None:
        item = self._providers.get(name)
        return item[0] if item else None


class DeterministicAcquisitionPlanner:
    """Plan single-provider missing/stale requirements without agent involvement."""

    def plan(self, evidence: EvidencePlan, registry: ProviderRegistry) -> AcquisitionDecision:
        actions: list[AcquisitionAction] = []
        for item in evidence.items:
            if item.state not in {EvidenceState.MISSING, EvidenceState.STALE}:
                continue
            candidates = registry.candidates(item.requirement)
            if len(candidates) == 1:
                actions.append(
                    AcquisitionAction(
                        item.requirement.identifier,
                        candidates[0],
                        AcquisitionStrategy.DETERMINISTIC,
                        "single permitted provider",
                    )
                )
        return AcquisitionDecision(
            tuple(actions),
            RecoveryPlan(RecoveryAction.RETRY, 2, (AcquisitionOutcome.SUCCESS,), "bounded retry"),
        )


class BoundedAcquisitionRunner:
    """Execute approved actions solely by delegating to ``AcquisitionCoordinator``."""

    def __init__(self, registry: ProviderRegistry) -> None:
        self.registry = registry

    def run(
        self, evidence: EvidencePlan, decision: AcquisitionDecision
    ) -> tuple[AcquisitionAttempt, ...]:
        items = {item.requirement.identifier: item for item in evidence.items}
        attempts: list[AcquisitionAttempt] = []
        for action in decision.actions:
            item = items.get(action.requirement_id)
            provider = self.registry.provider(action.provider)
            if item is None or provider is None:
                attempts.append(
                    AcquisitionAttempt(
                        action, 1, AcquisitionOutcome.UNSUPPORTED, "action is not permitted"
                    )
                )
                continue
            for ordinal in range(1, decision.recovery.max_attempts + 1):
                result = (
                    AcquisitionCoordinator({action.provider: provider})
                    .acquire(EvidencePlan(evidence.schema_version, (item,)))
                    .items[0]
                )
                outcome = self._outcome(result)
                attempts.append(
                    AcquisitionAttempt(action, ordinal, outcome, result.reason or outcome.value)
                )
                if (
                    outcome in decision.recovery.stop_when
                    or decision.recovery.action is RecoveryAction.STOP
                ):
                    break
        return tuple(attempts)

    @staticmethod
    def _outcome(item: EvidenceItem) -> AcquisitionOutcome:
        if item.state is EvidenceState.STAGED:
            return AcquisitionOutcome.SUCCESS
        if item.state is EvidenceState.INVALID:
            return AcquisitionOutcome.MALFORMED
        if item.state is EvidenceState.BLOCKED:
            return AcquisitionOutcome.TRANSIENT_FAILURE
        return AcquisitionOutcome.PARTIAL
