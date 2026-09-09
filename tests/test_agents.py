"""Tests for the provider-independent agent research layer."""
# ruff: noqa: E501

import json
from dataclasses import replace
from pathlib import Path
from urllib.error import HTTPError, URLError

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
from qhapaq_finance.agents.ollama_adapter import (
    OllamaProvider,
    OllamaProviderError,
    _challenge_schema,
    _synthesis_schema,
)
from qhapaq_finance.agents.openai_adapter import OpenAIAgentsProvider
from qhapaq_finance.agents.orchestrator import AgentPipelineError, ResearchOrchestrator
from qhapaq_finance.agents.validation import NumericalClaimValidator, evidence_catalog
from qhapaq_finance.config import LOCAL_RESEARCH_PROFILE
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


@pytest.mark.parametrize(
    "path",
    [
        "/valuation/scenarios/base/intrinsic_value",
        "/interpretation/valuation_status",
        "/interpretation/margin_of_safety",
    ],
)
def test_firewall_rejects_invented_json_pointer_evidence_paths(path: str) -> None:
    artifact = build_company_artifact("QCOM", ROOT)
    interpretation = interpret_artifact(artifact)
    synthesis = FakeProvider().synthesize(artifact, interpretation)
    invalid = replace(
        synthesis,
        evidence_refs=(EvidenceRef(path, EvidenceKind.DETERMINISTIC_ARTIFACT),),
    )
    result = NumericalClaimValidator().validate(invalid, artifact, interpretation)
    assert not result.valid
    assert result.failures[0].reason == "unknown evidence reference"


def test_evidence_catalog_is_stable_and_is_the_validator_allowlist() -> None:
    artifact = build_company_artifact("QCOM", ROOT)
    interpretation = interpret_artifact(artifact)
    catalog = evidence_catalog(artifact, interpretation)
    assert catalog == evidence_catalog(artifact, interpretation)
    assert [entry.evidence_id for entry in catalog] == [
        "market_price",
        "base_intrinsic_value",
        "base_margin_of_safety",
        "base_terminal_value_share",
        "roic_minus_wacc",
        "growth_difference",
        "price_fair_value_distance",
        "market_implied_growth_gap",
        "roic_wacc_spread",
    ]
    assert next(
        entry for entry in catalog if entry.evidence_id == "base_intrinsic_value"
    ).to_dict() == {
        "evidence_id": "base_intrinsic_value",
        "evidence_path": "valuation.scenarios.base.intrinsic_value",
        "evidence_kind": "DETERMINISTIC_ARTIFACT",
        "metric_label": "Base intrinsic value",
        "value": artifact["valuation"]["scenarios"]["base"]["intrinsic_value"],
        "unit": "USD_PER_SHARE",
    }
    content = ResearchSynthesis(
        ticker="QCOM",
        assessment="Watch valuation discipline",
        confidence=Confidence.MEDIUM,
        thesis="Cash generation supports a conditional case",
        positive_evidence=("Value creation is positive",),
        negative_evidence=("Terminal dependence is material",),
        critical_assumptions=("Cash conversion persists",),
        invalidation_conditions=("Capital efficiency deteriorates",),
        open_questions=("What sustains durable demand",),
        evidence_refs=tuple(entry.evidence_ref for entry in catalog),
        numeric_claims=tuple(
            NumericClaim(entry.metric_label, entry.value, entry.unit, entry.evidence_ref)
            for entry in catalog
        ),
    )
    assert NumericalClaimValidator().validate(content, artifact, interpretation).valid


@pytest.mark.parametrize(
    ("label", "value", "unit", "reason"),
    [
        (
            "Invented label",
            0.0,
            NumericUnit.USD_PER_SHARE,
            "label does not match referenced metric",
        ),
        (
            "Market price",
            0.0,
            NumericUnit.USD_PER_SHARE,
            "value does not match deterministic evidence",
        ),
        ("Market price", 0.0, NumericUnit.RATIO, "unit does not match referenced value"),
    ],
)
def test_validator_rejects_changed_canonical_tuple_after_evidence_selection(
    label: str, value: float, unit: NumericUnit, reason: str
) -> None:
    artifact = build_company_artifact("QCOM", ROOT)
    interpretation = interpret_artifact(artifact)
    synthesis = FakeProvider().synthesize(artifact, interpretation)
    selected = next(
        entry
        for entry in evidence_catalog(artifact, interpretation)
        if entry.evidence_id == "market_price"
    )
    invalid = replace(
        synthesis,
        numeric_claims=(NumericClaim(label, value, unit, selected.evidence_ref),),
    )
    result = NumericalClaimValidator().validate(invalid, artifact, interpretation)
    assert not result.valid
    assert result.failures[0].reason == reason


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


class _Response:
    def __init__(self, data: object) -> None:
        self._data = json.dumps(data).encode()

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._data


class OllamaTransport:
    def __init__(self, contents: list[object]) -> None:
        self.contents = contents
        self.requests: list[dict[str, object]] = []

    def __call__(self, request: object, *, timeout: float) -> _Response:
        data = json.loads(request.data.decode())  # type: ignore[attr-defined]
        self.requests.append(data)
        return _Response({"message": {"content": json.dumps(self.contents.pop(0))}})


def _ollama_synthesis(price: float) -> dict[str, object]:
    return {
        "ticker": "QCOM",
        "assessment": "Watch valuation discipline",
        "confidence": "MEDIUM",
        "thesis": "Cash generation supports a conditional case",
        "positive_evidence": ["Value creation is positive"],
        "negative_evidence": ["Terminal dependence is material"],
        "critical_assumptions": ["Cash conversion persists"],
        "invalidation_conditions": ["Capital efficiency deteriorates"],
        "open_questions": ["What sustains durable demand"],
        "evidence_refs": [{"evidence_id": "market_price"}],
        "numeric_claims": [{"evidence_id": "market_price"}],
    }


def _ollama_challenge() -> dict[str, object]:
    return {
        "challenges": ["The valuation depends on durable cash generation"],
        "fragile_assumptions": ["Capital returns remain strong"],
        "missing_evidence": ["Segment demand persistence needs evidence"],
        "potential_confirmation_bias": ["Recent execution may receive too much weight"],
        "evidence_refs": [{"evidence_id": "market_price"}],
        "numeric_claims": [],
    }


def test_ollama_provider_uses_schema_constrained_local_requests() -> None:
    artifact = build_company_artifact("QCOM", ROOT)
    transport = OllamaTransport(
        [_ollama_synthesis(float(artifact["market"]["price"])), _ollama_challenge()]
    )
    provider = OllamaProvider("chosen-model", opener=transport)
    result = ResearchOrchestrator(provider).investigate(artifact)
    assert result.validation["synthesis"].valid
    assert result.validation["challenge"].valid
    assert len(transport.requests) == 2
    assert provider.diagnostics == {
        "synthesis": {
            "initial_contract_valid": True,
            "repair_attempted": False,
            "repair_succeeded": False,
        },
        "challenge": {
            "initial_contract_valid": True,
            "repair_attempted": False,
            "repair_succeeded": False,
        },
    }
    for request in transport.requests:
        assert request["model"] == "chosen-model"
        assert request["stream"] is False
        assert request["think"] is False
        assert request["options"] == {"temperature": 0}
        assert request["format"]["type"] == "object"  # type: ignore[index]
        assert request["format"]["additionalProperties"] is False  # type: ignore[index]
        instructions = request["messages"][0]["content"]  # type: ignore[index]
        assert "must contain no digits" in instructions
        assert "prices, percentages, ratios, dates, counts" in instructions
        assert "only in numeric_claims" in instructions
        assert "Do not restate numeric facts in prose" in instructions
        assert "ALLOWED_EVIDENCE" in instructions
        assert "never invent, shorten, normalize, infer, or construct a path" in instructions
        payload = json.loads(request["messages"][1]["content"])  # type: ignore[index]
        assert "artifact" not in payload
        assert payload["ALLOWED_EVIDENCE"] == [
            entry.to_dict() for entry in evidence_catalog(artifact, interpret_artifact(artifact))
        ]
        assert any(
            entry["evidence_id"] == "base_intrinsic_value" for entry in payload["ALLOWED_EVIDENCE"]
        )


def test_ollama_schema_contains_all_contract_qualitative_fields() -> None:
    artifact = build_company_artifact("QCOM", ROOT)
    catalog = evidence_catalog(artifact, interpret_artifact(artifact))
    synthesis_properties = _synthesis_schema(catalog)["properties"]  # type: ignore[index]
    assert synthesis_properties["evidence_refs"]["items"]["properties"]["evidence_id"][  # type: ignore[index]
        "enum"
    ] == [entry.evidence_id for entry in catalog]
    assert synthesis_properties["numeric_claims"]["items"]["properties"]["evidence_id"][  # type: ignore[index]
        "enum"
    ] == [entry.evidence_id for entry in catalog]
    for field in ("assessment", "thesis"):
        assert synthesis_properties[field] == {"type": "string", "minLength": 1}  # type: ignore[index]
    for field in (
        "positive_evidence",
        "negative_evidence",
        "critical_assumptions",
        "invalidation_conditions",
        "open_questions",
    ):
        assert synthesis_properties[field]["items"] == {"type": "string", "minLength": 1}  # type: ignore[index]

    challenge_properties = _challenge_schema(catalog)["properties"]  # type: ignore[index]
    for field in (
        "challenges",
        "fragile_assumptions",
        "missing_evidence",
        "potential_confirmation_bias",
    ):
        assert challenge_properties[field]["items"] == {"type": "string", "minLength": 1}  # type: ignore[index]


def test_ollama_resolves_a_valid_canonical_evidence_selection() -> None:
    artifact = build_company_artifact("QCOM", ROOT)
    response = _ollama_synthesis(float(artifact["market"]["price"]))
    response["evidence_refs"] = [{"evidence_id": "base_intrinsic_value"}]
    response["numeric_claims"] = [{"evidence_id": "base_intrinsic_value"}]
    provider = OllamaProvider("chosen-model", opener=OllamaTransport([response]))
    synthesis = provider.synthesize(artifact, interpret_artifact(artifact))
    assert synthesis.numeric_claims == (
        NumericClaim(
            "Base intrinsic value",
            float(artifact["valuation"]["scenarios"]["base"]["intrinsic_value"]),
            NumericUnit.USD_PER_SHARE,
            EvidenceRef(
                "valuation.scenarios.base.intrinsic_value", EvidenceKind.DETERMINISTIC_ARTIFACT
            ),
        ),
    )


def test_openai_provider_receives_the_same_allowed_evidence_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = build_company_artifact("QCOM", ROOT)
    interpretation = interpret_artifact(artifact)
    expected = [entry.to_dict() for entry in evidence_catalog(artifact, interpretation)]
    provider = OpenAIAgentsProvider()
    calls: list[dict[str, object]] = []

    def capture(**kwargs: object) -> object:
        calls.append(kwargs)
        return (
            FakeProvider().synthesize(artifact, interpretation)
            if kwargs["name"] == "Qhapaq Research Synthesis"
            else FakeProvider().challenge(
                artifact, interpretation, FakeProvider().synthesize(artifact, interpretation)
            )
        )

    monkeypatch.setattr(provider, "_run", capture)
    synthesis = provider.synthesize(artifact, interpretation)
    provider.challenge(artifact, interpretation, synthesis)
    assert [call["payload"]["ALLOWED_EVIDENCE"] for call in calls] == [expected, expected]  # type: ignore[index]


def test_ollama_synthesis_repairs_numeric_qualitative_field_once() -> None:
    artifact = build_company_artifact("QCOM", ROOT)
    catalog = evidence_catalog(artifact, interpret_artifact(artifact))
    invalid = _ollama_synthesis(float(artifact["market"]["price"]))
    invalid["assessment"] = "Watch at 10 percent"
    valid = _ollama_synthesis(float(artifact["market"]["price"]))
    transport = OllamaTransport([invalid, valid])
    provider = OllamaProvider("chosen-model", opener=transport)
    synthesis = provider.synthesize(artifact, interpret_artifact(artifact))
    assert synthesis.assessment == "Watch valuation discipline"
    assert synthesis.numeric_claims[0].value == artifact["market"]["price"]
    assert len(transport.requests) == 2
    assert provider.diagnostics["synthesis"] == {
        "initial_contract_valid": False,
        "repair_attempted": True,
        "repair_succeeded": True,
    }
    repair = transport.requests[1]
    assert repair["model"] == "chosen-model"
    assert repair["stream"] is False
    assert repair["think"] is False
    assert repair["options"] == {"temperature": 0}
    assert repair["format"] == _synthesis_schema(catalog)
    repair_payload = json.loads(repair["messages"][1]["content"])  # type: ignore[index]
    assert repair_payload["original_structured_output"] == invalid
    assert repair_payload["output_json_schema"] == _synthesis_schema(catalog)
    assert "FIELD: assessment" in repair_payload["contract_feedback"]
    assert "qualitative fields must contain no digits" in repair_payload["contract_feedback"]


def test_ollama_challenge_repairs_numeric_qualitative_field_once() -> None:
    artifact = build_company_artifact("QCOM", ROOT)
    invalid = _ollama_challenge()
    invalid["challenges"] = ["The downside is 10 percent"]
    transport = OllamaTransport([invalid, _ollama_challenge()])
    provider = OllamaProvider("chosen-model", opener=transport)
    interpretation = interpret_artifact(artifact)
    challenge = provider.challenge(
        artifact,
        interpretation,
        FakeProvider().synthesize(artifact, interpretation),
    )
    assert challenge.challenges == ("The valuation depends on durable cash generation",)
    assert len(transport.requests) == 2
    assert provider.diagnostics["challenge"]["repair_succeeded"]
    repair_payload = json.loads(transport.requests[1]["messages"][1]["content"])  # type: ignore[index]
    assert "FIELD: challenges" in repair_payload["contract_feedback"]


def test_ollama_contract_repair_failure_is_explicit_and_bounded() -> None:
    artifact = build_company_artifact("QCOM", ROOT)
    invalid = _ollama_synthesis(float(artifact["market"]["price"]))
    invalid["thesis"] = "The result is 10 percent favorable"
    transport = OllamaTransport([invalid, invalid])
    provider = OllamaProvider("chosen-model", opener=transport)
    with pytest.raises(OllamaProviderError, match="OLLAMA_CONTRACT_REPAIR_FAILED") as exc:
        provider.synthesize(artifact, interpret_artifact(artifact))
    assert len(transport.requests) == 2
    assert exc.value.initial_failure is not None
    assert exc.value.repair_failure is not None
    assert provider.diagnostics["synthesis"]["repair_succeeded"] is False


@pytest.mark.parametrize(
    "content",
    ["not json", ["not", "an", "object"], {"ticker": "QCOM"}],
)
def test_ollama_provider_fails_closed_for_invalid_structured_output(content: object) -> None:
    artifact = build_company_artifact("QCOM", ROOT)
    transport = OllamaTransport([content])
    with pytest.raises(OllamaProviderError, match="OLLAMA_INVALID_RESPONSE"):
        OllamaProvider("chosen-model", opener=transport).synthesize(
            artifact, interpret_artifact(artifact)
        )
    assert len(transport.requests) == 1


def test_ollama_provider_reports_connection_failure_explicitly() -> None:
    requests: list[object] = []

    def unavailable(request: object, *, timeout: float) -> _Response:
        requests.append(request)
        raise URLError("refused")

    artifact = build_company_artifact("QCOM", ROOT)
    with pytest.raises(OllamaProviderError, match="OLLAMA_UNAVAILABLE"):
        OllamaProvider("chosen-model", opener=unavailable).synthesize(
            artifact, interpret_artifact(artifact)
        )
    assert len(requests) == 1


def test_ollama_provider_rejects_wrong_ollama_response_shape() -> None:
    def wrong_shape(request: object, *, timeout: float) -> _Response:
        return _Response({"response": "not a chat response"})

    artifact = build_company_artifact("QCOM", ROOT)
    with pytest.raises(OllamaProviderError, match="OLLAMA_INVALID_RESPONSE"):
        OllamaProvider("chosen-model", opener=wrong_shape).synthesize(
            artifact, interpret_artifact(artifact)
        )


def test_ollama_provider_reports_missing_model_explicitly() -> None:
    requests: list[object] = []

    def missing_model(request: object, *, timeout: float) -> _Response:
        requests.append(request)
        raise HTTPError("http://127.0.0.1:11434/api/chat", 404, "not found", {}, None)

    artifact = build_company_artifact("QCOM", ROOT)
    with pytest.raises(OllamaProviderError, match="OLLAMA_MODEL_MISSING"):
        OllamaProvider("absent-model", opener=missing_model).synthesize(
            artifact, interpret_artifact(artifact)
        )
    assert len(requests) == 1


def test_ollama_http_error_does_not_trigger_repair() -> None:
    requests: list[object] = []

    def server_error(request: object, *, timeout: float) -> _Response:
        requests.append(request)
        raise HTTPError("http://127.0.0.1:11434/api/chat", 500, "server error", {}, None)

    artifact = build_company_artifact("QCOM", ROOT)
    with pytest.raises(OllamaProviderError, match="OLLAMA_HTTP_ERROR"):
        OllamaProvider("chosen-model", opener=server_error).synthesize(
            artifact, interpret_artifact(artifact)
        )
    assert len(requests) == 1


def test_unknown_evidence_id_fails_closed_without_repair() -> None:
    artifact = build_company_artifact("QCOM", ROOT)
    response = _ollama_synthesis(float(artifact["market"]["price"]))
    response["evidence_refs"] = [{"evidence_id": "invented_path"}]
    transport = OllamaTransport([response])
    provider = OllamaProvider("chosen-model", opener=transport)
    with pytest.raises(OllamaProviderError, match="OLLAMA_INVALID_RESPONSE: unknown evidence_id"):
        provider.synthesize(artifact, interpret_artifact(artifact))
    assert len(transport.requests) == 1


def test_ollama_cli_does_not_require_openai_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    artifact = build_company_artifact("QCOM", ROOT)
    responses = [_ollama_synthesis(float(artifact["market"]["price"])), _ollama_challenge()]
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(OllamaProvider, "preflight", lambda self: None)
    monkeypatch.setattr(OllamaProvider, "unload", lambda self: True)
    monkeypatch.setattr(OllamaProvider, "_run", lambda *args, **kwargs: responses.pop(0))
    cli.main(["investigate", "QCOM", "--provider", "ollama", "--model", "qwen3.5:9b", "--json"])
    assert '"provider": "OllamaProvider"' in capsys.readouterr().out


def test_local_profile_is_the_validated_immutable_default() -> None:
    assert LOCAL_RESEARCH_PROFILE.provider == "ollama"
    assert LOCAL_RESEARCH_PROFILE.model == "qwen3.5:9b"
    assert LOCAL_RESEARCH_PROFILE.endpoint == "http://127.0.0.1:11434"
    assert LOCAL_RESEARCH_PROFILE.temperature == 0
    assert not LOCAL_RESEARCH_PROFILE.think
    assert not LOCAL_RESEARCH_PROFILE.stream
    assert LOCAL_RESEARCH_PROFILE.max_contract_repairs == 1
    assert LOCAL_RESEARCH_PROFILE.unload_after_run


def test_ollama_preflight_checks_tags_without_pulling() -> None:
    requests: list[object] = []

    def available(request: object, *, timeout: float) -> _Response:
        requests.append(request)
        return _Response({"models": [{"name": "qwen3.5:9b"}]})

    OllamaProvider("qwen3.5:9b", opener=available).preflight()
    assert requests[0].get_method() == "GET"  # type: ignore[attr-defined]
    assert requests[0].full_url.endswith("/api/tags")  # type: ignore[attr-defined]


def test_ollama_preflight_reports_unavailable_and_missing_model() -> None:
    def unavailable(request: object, *, timeout: float) -> _Response:
        raise URLError("refused")

    with pytest.raises(OllamaProviderError, match="OLLAMA_UNAVAILABLE"):
        OllamaProvider("qwen3.5:9b", opener=unavailable).preflight()

    with pytest.raises(OllamaProviderError, match=r"ollama pull qwen3.5:9b"):
        OllamaProvider(
            "qwen3.5:9b", opener=lambda request, timeout: _Response({"models": []})
        ).preflight()


def test_ollama_unload_uses_local_keep_alive_zero_request() -> None:
    requests: list[object] = []

    def released(request: object, *, timeout: float) -> _Response:
        requests.append(request)
        return _Response({"done": True})

    provider = OllamaProvider("qwen3.5:9b", opener=released)
    assert provider.unload()
    request = requests[0]
    assert request.full_url.endswith("/api/generate")  # type: ignore[attr-defined]
    assert json.loads(request.data.decode()) == {  # type: ignore[attr-defined]
        "model": "qwen3.5:9b",
        "keep_alive": 0,
        "stream": False,
    }
    assert provider.lifecycle_diagnostics["model_unload_attempted"]
    assert provider.lifecycle_diagnostics["model_unload_succeeded"]


def test_local_cli_selects_default_or_overridden_model_and_never_needs_openai(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    artifact = build_company_artifact("QCOM", ROOT)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(OllamaProvider, "preflight", lambda self: None)
    monkeypatch.setattr(OllamaProvider, "unload", lambda self: True)
    seen: list[str] = []
    responses = [_ollama_synthesis(float(artifact["market"]["price"])), _ollama_challenge()]

    def respond(self: OllamaProvider, **kwargs: object) -> dict[str, object]:
        seen.append(self._model)
        return responses.pop(0)

    monkeypatch.setattr(OllamaProvider, "_run", respond)
    cli.main(["investigate", "QCOM", "--local", "--json"])
    assert seen == ["qwen3.5:9b", "qwen3.5:9b"]
    capsys.readouterr()
    responses[:] = [_ollama_synthesis(float(artifact["market"]["price"])), _ollama_challenge()]
    cli.main(["investigate", "QCOM", "--local", "--model", "custom-local", "--json"])
    assert seen[-2:] == ["custom-local", "custom-local"]


def test_local_cli_rejects_explicit_provider_combination() -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["investigate", "QCOM", "--local", "--provider", "ollama"])
    assert exc.value.code == 2


def test_local_cli_unloads_once_after_pipeline_success_or_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = build_company_artifact("QCOM", ROOT)
    events: list[str] = []
    monkeypatch.setattr(OllamaProvider, "preflight", lambda self: events.append("preflight"))
    monkeypatch.setattr(OllamaProvider, "unload", lambda self: events.append("unload") or True)
    responses = [_ollama_synthesis(float(artifact["market"]["price"])), _ollama_challenge()]

    def success(self: OllamaProvider, **kwargs: object) -> dict[str, object]:
        events.append("challenge" if responses and len(responses) == 1 else "synthesis")
        return responses.pop(0)

    monkeypatch.setattr(OllamaProvider, "_run", success)
    cli.main(["investigate", "QCOM", "--local"])
    assert events == ["preflight", "synthesis", "challenge", "unload"]

    events.clear()
    monkeypatch.setattr(OllamaProvider, "_run", lambda self, **kwargs: {"ticker": "QCOM"})
    monkeypatch.setattr(
        OllamaProvider,
        "unload",
        lambda self: events.append("unload") or (_ for _ in ()).throw(RuntimeError("cleanup")),
    )
    with pytest.raises(AgentPipelineError):
        cli.main(["investigate", "QCOM", "--local"])
    assert events == ["preflight", "unload"]


def test_unload_failure_is_diagnostic_only_after_valid_local_artifact(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    artifact = build_company_artifact("QCOM", ROOT)
    monkeypatch.setattr(OllamaProvider, "preflight", lambda self: None)
    monkeypatch.setattr(OllamaProvider, "unload", lambda self: False)
    responses = [_ollama_synthesis(float(artifact["market"]["price"])), _ollama_challenge()]
    monkeypatch.setattr(OllamaProvider, "_run", lambda *args, **kwargs: responses.pop(0))
    cli.main(["investigate", "QCOM", "--local", "--json"])
    captured = capsys.readouterr()
    assert '"schema_version": "agent-research-v1"' in captured.out
    assert "Ollama model unload failed" in captured.err
