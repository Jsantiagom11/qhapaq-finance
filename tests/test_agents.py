"""Tests for the provider-independent agent research layer."""
# ruff: noqa: E501

import json
from dataclasses import replace
from pathlib import Path

import pytest

from qhapaq_finance import cli
from qhapaq_finance.agents.contracts import (
    Confidence,
    EvidenceKind,
    EvidenceRef,
    NumericClaim,
    NumericUnit,
    ResearchSynthesis,
    ThesisChallenge,
)
from qhapaq_finance.agents.interpretation import (
    InterpretationThresholds,
    SignalCode,
    interpret_artifact,
)
from qhapaq_finance.agents.orchestrator import AgentPipelineError, ResearchOrchestrator
from qhapaq_finance.agents.validation import NumericalClaimValidator
from qhapaq_finance.dashboard import build_company_artifact, canonical_json

ROOT = Path(__file__).parents[1]
REF = EvidenceRef("market.price", EvidenceKind.DETERMINISTIC_ARTIFACT)


class FakeProvider:
    def __init__(self, *, bad_number: bool = False) -> None:
        self.events: list[str] = []
        self.bad_number = bad_number

    def synthesize(self, artifact: dict[str, object], interpretation: object) -> ResearchSynthesis:
        self.events.append("synthesis")
        return ResearchSynthesis(
            ticker="QCOM",
            assessment="Watch valuation discipline",
            confidence=Confidence.MEDIUM,
            thesis="Cash generation supports a conditional case",
            positive_evidence=("Value creation is positive",),
            negative_evidence=("Terminal dependence is material",),
            critical_assumptions=("Cash conversion persists",),
            invalidation_conditions=("Capital efficiency deteriorates",),
            open_questions=("What sustains durable demand",),
            evidence_refs=(REF,),
            numeric_claims=(
                NumericClaim(
                    "Market price",
                    999.0 if self.bad_number else float(artifact["market"]["price"]),
                    NumericUnit.USD_PER_SHARE,
                    REF,
                ),
            ),
        )

    def challenge(
        self, artifact: dict[str, object], interpretation: object, synthesis: ResearchSynthesis
    ) -> ThesisChallenge:
        self.events.append("challenge")
        return ThesisChallenge(
            challenges=("The valuation depends on durable cash generation",),
            fragile_assumptions=("Capital returns remain strong",),
            missing_evidence=("Segment demand persistence needs evidence",),
            potential_confirmation_bias=("Recent execution may receive too much weight",),
            evidence_refs=(REF,),
        )


def test_interpretation_is_deterministic_and_threshold_governed() -> None:
    artifact = build_company_artifact("QCOM", ROOT)
    result = interpret_artifact(artifact)
    assert result.valuation_status == SignalCode.ABOVE_FAIR_VALUE
    assert result.market_expectations_status == SignalCode.MARKET_EXPECTATIONS_ABOVE_BASE
    assert result.terminal_value_dependence is None
    assert (
        interpret_artifact(
            artifact, InterpretationThresholds(high_terminal_value_share=0.63)
        ).terminal_value_dependence
        == SignalCode.HIGH_TERMINAL_DEPENDENCE
    )
    assert result.value_creation_status == SignalCode.STRONG_VALUE_CREATION
    assert result.sensitivity_status == SignalCode.SENSITIVITY_FRAGILE
    boundary = json.loads(canonical_json(artifact))
    boundary["market"]["price"] = boundary["valuation"]["scenarios"]["base"]["intrinsic_value"]
    assert interpret_artifact(boundary).valuation_status == SignalCode.AT_FAIR_VALUE


def test_firewall_accepts_matching_claim_and_rejects_unit_and_value() -> None:
    artifact = build_company_artifact("QCOM", ROOT)
    interpretation = interpret_artifact(artifact)
    good = FakeProvider().synthesize(artifact, interpretation)
    assert NumericalClaimValidator().validate(good, artifact, interpretation).valid
    bad = replace(
        good, numeric_claims=(NumericClaim("Wrong", 1.5128, NumericUnit.PERCENTAGE_POINT, REF),)
    )
    failure = NumericalClaimValidator().validate(bad, artifact, interpretation)
    assert not failure.valid
    assert failure.failures[0].reason == "unit does not match referenced value"
    pp_claim = NumericClaim(
        "Growth difference",
        artifact["valuation"]["expectations"]["growth_difference_pp"] * 100,
        NumericUnit.PERCENTAGE_POINT,
        EvidenceRef(
            "valuation.expectations.growth_difference_pp", EvidenceKind.DETERMINISTIC_ARTIFACT
        ),
    )
    pp_synthesis = replace(good, numeric_claims=(pp_claim,))
    assert NumericalClaimValidator().validate(pp_synthesis, artifact, interpretation).valid


def test_firewall_rejects_metric_label_substitution() -> None:
    artifact = build_company_artifact("QCOM", ROOT)
    interpretation = interpret_artifact(artifact)
    synthesis = FakeProvider().synthesize(artifact, interpretation)
    mislabelled = replace(
        synthesis,
        numeric_claims=(
            NumericClaim(
                "Revenue",
                float(artifact["market"]["price"]),
                NumericUnit.USD_PER_SHARE,
                REF,
            ),
        ),
    )
    result = NumericalClaimValidator().validate(mislabelled, artifact, interpretation)
    assert not result.valid
    assert result.failures[0].reason == "label does not match referenced metric"


def test_firewall_rejects_spoofed_evidence_reference() -> None:
    artifact = build_company_artifact("QCOM", ROOT)
    interpretation = interpret_artifact(artifact)
    synthesis = FakeProvider().synthesize(artifact, interpretation)
    spoofed = replace(
        synthesis,
        evidence_refs=(
            EvidenceRef("market.enterprise_value", EvidenceKind.DETERMINISTIC_ARTIFACT),
        ),
    )
    result = NumericalClaimValidator().validate(spoofed, artifact, interpretation)
    assert not result.valid
    assert result.failures[0].reason == "unknown evidence reference"


def test_orchestration_order_serialization_and_failure_propagation() -> None:
    artifact = build_company_artifact("QCOM", ROOT)
    provider = FakeProvider()
    result = ResearchOrchestrator(provider).investigate(artifact)
    assert provider.events == ["synthesis", "challenge"]
    serialized = result.to_dict()
    assert serialized["schema_version"] == "agent-research-v1"
    assert serialized["validation"]["synthesis"]["valid"]
    assert json.loads(canonical_json(serialized))["ticker"] == "QCOM"
    failed = FakeProvider(bad_number=True)
    with pytest.raises(AgentPipelineError, match="synthesis numerical validation failed"):
        ResearchOrchestrator(failed).investigate(artifact)
    assert failed.events == ["synthesis"]


class FailingProvider(FakeProvider):
    def synthesize(self, artifact: dict[str, object], interpretation: object) -> ResearchSynthesis:
        raise RuntimeError("provider unavailable")


class MalformedProvider(FakeProvider):
    def synthesize(self, artifact: dict[str, object], interpretation: object) -> ResearchSynthesis:
        return object()  # type: ignore[return-value]


class MutatingProvider(FakeProvider):
    def synthesize(self, artifact: dict[str, object], interpretation: object) -> ResearchSynthesis:
        artifact["market"] = {"price": 999.0}
        return super().synthesize(artifact, interpretation)


@pytest.mark.parametrize(
    ("provider", "message"),
    [
        (FailingProvider(), "synthesis provider failed"),
        (MalformedProvider(), "synthesis provider returned malformed structured output"),
    ],
)
def test_orchestration_makes_provider_and_malformed_output_failures_explicit(
    provider: FakeProvider, message: str
) -> None:
    artifact = build_company_artifact("QCOM", ROOT)
    with pytest.raises(AgentPipelineError, match=message):
        ResearchOrchestrator(provider).investigate(artifact)


def test_provider_cannot_mutate_the_deterministic_validation_snapshot() -> None:
    artifact = build_company_artifact("QCOM", ROOT)
    original_price = artifact["market"]["price"]
    with pytest.raises(AgentPipelineError, match="synthesis numerical validation failed"):
        ResearchOrchestrator(MutatingProvider()).investigate(artifact)
    assert artifact["market"]["price"] == original_price


def test_contract_rejects_numbers_in_qualitative_evidence() -> None:
    with pytest.raises(ValueError, match="numeric_claims"):
        ResearchSynthesis(
            ticker="QCOM",
            assessment="Watch",
            confidence=Confidence.LOW,
            thesis="Qualitative",
            positive_evidence=("Growth is 10 percent",),
            negative_evidence=("Risk",),
            critical_assumptions=("Assumption",),
            invalidation_conditions=("Condition",),
            open_questions=("Question",),
            evidence_refs=(REF,),
        )


def test_investigate_requires_configuration_without_affecting_offline_commands(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(SystemExit) as exc:
        cli.main(["investigate", "QCOM", "--json"])
    assert exc.value.code == 2
    assert "OPENAI_API_KEY" in capsys.readouterr().err
    cli.main(["research", "QCOM", "--json"])
    assert '"schema_version": "dashboard-research-v1"' in capsys.readouterr().out
