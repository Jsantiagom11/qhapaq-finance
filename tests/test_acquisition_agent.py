from __future__ import annotations

from pathlib import Path

from qhapaq_finance.acquisition_agent import (
    AcquisitionAction,
    AcquisitionDecision,
    AcquisitionOutcome,
    AcquisitionStrategy,
    BoundedAcquisitionRunner,
    DeterministicAcquisitionPlanner,
    ProviderCapability,
    ProviderRegistry,
    RecoveryAction,
    RecoveryPlan,
)
from qhapaq_finance.analysis import CompanyIdentity
from qhapaq_finance.evidence_orchestration import (
    EvidenceItem,
    EvidencePlan,
    EvidenceRequirement,
    EvidenceState,
    FreshnessPolicy,
)
from qhapaq_finance.sec_acquisition import StagedSecResource


class Provider:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    def acquire(self, requirement: EvidenceRequirement) -> StagedSecResource:
        del requirement
        self.calls += 1
        if self.fail:
            raise RuntimeError("temporary failure")
        return StagedSecResource(Path("data/raw/sec/a.bin"), Path("a.json"), "a", 1)


def _item(provider: str = "SEC") -> EvidenceItem:
    identity = CompanyIdentity("ACME", None, None, "Acme", None, None, "0000000123", None)
    requirement = EvidenceRequirement(
        "facts",
        provider,
        "COMPANY_FACTS",
        identity,
        "https://data.sec.gov/facts",
        (),
        (),
        FreshnessPolicy(),
        True,
    )
    return EvidenceItem(requirement, EvidenceState.MISSING, "absent", None)


def _registry(*providers: tuple[str, Provider]) -> ProviderRegistry:
    return ProviderRegistry(
        {
            name: (provider, ProviderCapability(name, ("COMPANY_FACTS",)))
            for name, provider in providers
        }
    )


def test_single_provider_is_planned_deterministically_without_agent() -> None:
    provider = Provider()
    evidence = EvidencePlan("v1", (_item(),))
    decision = DeterministicAcquisitionPlanner().plan(evidence, _registry(("SEC", provider)))
    assert decision.actions[0].strategy is AcquisitionStrategy.DETERMINISTIC
    attempts = BoundedAcquisitionRunner(_registry(("SEC", provider))).run(evidence, decision)
    assert attempts[0].outcome is AcquisitionOutcome.SUCCESS
    assert provider.calls == 1


def test_multiple_providers_require_selection_and_block_unregistered_action() -> None:
    evidence = EvidencePlan("v1", (_item("ANY"),))
    registry = _registry(("SEC", Provider()), ("ARCHIVE", Provider()))
    assert DeterministicAcquisitionPlanner().plan(evidence, registry).actions == ()
    action = AcquisitionAction("facts", "UNKNOWN", AcquisitionStrategy.AGENT, "test boundary")
    decision = AcquisitionDecision((action,), RecoveryPlan(RecoveryAction.STOP, 1, (), "stop"))
    attempt = BoundedAcquisitionRunner(registry).run(evidence, decision)[0]
    assert attempt.outcome is AcquisitionOutcome.UNSUPPORTED


def test_partial_failure_has_bounded_auditable_retries_and_exhaustion() -> None:
    provider = Provider(fail=True)
    evidence = EvidencePlan("v1", (_item(),))
    action = AcquisitionAction(
        "facts", "SEC", AcquisitionStrategy.RECOVERY, "retry transient failure"
    )
    decision = AcquisitionDecision(
        (action,),
        RecoveryPlan(RecoveryAction.RETRY, 2, (AcquisitionOutcome.SUCCESS,), "two attempts only"),
    )
    attempts = BoundedAcquisitionRunner(_registry(("SEC", provider))).run(evidence, decision)
    assert [item.outcome for item in attempts] == [
        AcquisitionOutcome.TRANSIENT_FAILURE,
        AcquisitionOutcome.TRANSIENT_FAILURE,
    ]
    assert [item.ordinal for item in attempts] == [1, 2]
    assert provider.calls == 2
