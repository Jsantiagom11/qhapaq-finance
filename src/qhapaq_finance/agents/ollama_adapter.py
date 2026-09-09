"""Local-only Ollama adapter for the provider-independent research boundary."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .contracts import (
    RESEARCH_SYNTHESIS_QUALITATIVE_ITEMS_FIELDS,
    RESEARCH_SYNTHESIS_QUALITATIVE_TEXT_FIELDS,
    THESIS_CHALLENGE_QUALITATIVE_ITEMS_FIELDS,
    Confidence,
    EvidenceRef,
    NumericClaim,
    ResearchSynthesis,
    ThesisChallenge,
    contract_dict,
)
from .interpretation import DeterministicInterpretation
from .validation import EvidenceCatalogEntry, evidence_catalog

_Open = Callable[..., Any]
_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
MAX_REPAIR_ATTEMPTS = 1


class OllamaProviderError(RuntimeError):
    """Explicit local-provider failure; its prefix is safe to surface to operators."""

    initial_failure: OllamaProviderError | None = None
    repair_failure: OllamaProviderError | None = None


class OllamaProvider:
    """Run contract-constrained research through Ollama's local chat API only."""

    def __init__(
        self,
        model: str,
        *,
        base_url: str = "http://127.0.0.1:11434",
        timeout: float = 120.0,
        opener: _Open = urlopen,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme != "http" or parsed.hostname not in _LOCAL_HOSTS:
            raise ValueError("Ollama base_url must be an http localhost endpoint")
        if not model.strip():
            raise ValueError("Ollama model must be non-empty")
        if timeout <= 0:
            raise ValueError("Ollama timeout must be positive")
        self._model = model
        self._url = f"{base_url.rstrip('/')}/api/chat"
        self._timeout = timeout
        self._opener = opener
        self._diagnostics: dict[str, dict[str, bool]] = {}

    @property
    def diagnostics(self) -> dict[str, dict[str, bool]]:
        """Return per-stage contract-repair outcomes without changing the artifact schema."""
        return {stage: values.copy() for stage, values in self._diagnostics.items()}

    def synthesize(
        self, artifact: dict[str, object], interpretation: DeterministicInterpretation
    ) -> ResearchSynthesis:
        catalog = evidence_catalog(artifact, interpretation)
        return cast(
            ResearchSynthesis,
            self._run_contract(
                stage="synthesis",
                instructions=(
                    "Interpret only supplied deterministic evidence. Do not calculate, invent, or "
                    "change financial facts. Qualitative text must contain no digits: never write "
                    "prices, percentages, ratios, dates, counts, or other numbers in prose. Put "
                    "all numeric statements only in numeric_claims. Select only an evidence_id "
                    "from ALLOWED_EVIDENCE; never invent, shorten, normalize, infer, or construct "
                    "a path. Python resolves each ID to its canonical path, metric label, value, "
                    "and unit. If unsupported, omit the claim or state an open question. Do not "
                    "restate numeric facts in prose."
                ),
                schema=_synthesis_schema(catalog),
                payload=_provider_context(artifact, interpretation, catalog),
                constructor=lambda data: _research_synthesis(data, catalog),
                qualitative_fields=(
                    *RESEARCH_SYNTHESIS_QUALITATIVE_TEXT_FIELDS,
                    *RESEARCH_SYNTHESIS_QUALITATIVE_ITEMS_FIELDS,
                ),
                allowed_evidence=catalog,
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
            self._run_contract(
                stage="challenge",
                instructions=(
                    "Adversarially challenge the supplied thesis using only supplied deterministic "
                    "evidence. Do not calculate or invent financial facts. Genuinely attack the "
                    "synthesis. Qualitative text must contain no digits: never write prices, "
                    "percentages, ratios, dates, counts, or other numbers in prose. Put all "
                    "numeric statements only in numeric_claims. Select only an evidence_id from "
                    "ALLOWED_EVIDENCE; never invent, shorten, normalize, infer, or construct a "
                    "path. Python resolves each ID to its canonical path, metric label, value, "
                    "and unit. If unsupported, omit the claim or state missing evidence. Do not "
                    "restate numeric facts in prose."
                ),
                schema=_challenge_schema(catalog),
                payload={
                    **_provider_context(artifact, interpretation, catalog),
                    "synthesis": contract_dict(synthesis),
                },
                constructor=lambda data: _thesis_challenge(data, catalog),
                qualitative_fields=THESIS_CHALLENGE_QUALITATIVE_ITEMS_FIELDS,
                allowed_evidence=catalog,
            ),
        )

    def _run_contract(
        self,
        *,
        stage: str,
        instructions: str,
        schema: dict[str, object],
        payload: object,
        constructor: Callable[[dict[str, Any]], object],
        qualitative_fields: tuple[str, ...],
        allowed_evidence: tuple[EvidenceCatalogEntry, ...] | None = None,
    ) -> object:
        """Make one generation request and, only for a contract failure, one repair request."""
        diagnostics = {
            "initial_contract_valid": False,
            "repair_attempted": False,
            "repair_succeeded": False,
        }
        self._diagnostics[stage] = diagnostics
        initial = self._run(instructions=instructions, schema=schema, payload=payload)
        try:
            result = constructor(initial)
        except OllamaProviderError as initial_failure:
            if not _is_repairable_contract_failure(initial_failure):
                raise
            diagnostics["repair_attempted"] = True
            feedback = _repair_feedback(initial, qualitative_fields)
            try:
                repaired = self._run(
                    instructions=_repair_instructions(stage),
                    schema=schema,
                    payload={
                        "original_structured_output": initial,
                        "contract_feedback": feedback,
                        "output_json_schema": schema,
                        "ALLOWED_EVIDENCE": [entry.to_dict() for entry in allowed_evidence or ()],
                    },
                )
                result = constructor(repaired)
            except OllamaProviderError as repair_failure:
                failure = OllamaProviderError(
                    f"OLLAMA_CONTRACT_REPAIR_FAILED: {stage} contract repair failed"
                )
                failure.initial_failure = initial_failure
                failure.repair_failure = repair_failure
                raise failure from repair_failure
            diagnostics["repair_succeeded"] = True
            return result
        diagnostics["initial_contract_valid"] = True
        return result

    def _run(
        self, *, instructions: str, schema: dict[str, object], payload: object
    ) -> dict[str, Any]:
        request_body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": json.dumps(payload, default=str, sort_keys=True)},
            ],
            "stream": False,
            "think": False,
            "format": schema,
            "options": {"temperature": 0},
        }
        request = Request(
            self._url,
            data=json.dumps(request_body, sort_keys=True).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                raw = response.read()
        except HTTPError as exc:
            code = "OLLAMA_MODEL_MISSING" if exc.code == 404 else "OLLAMA_HTTP_ERROR"
            raise OllamaProviderError(f"{code}: HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise OllamaProviderError("OLLAMA_UNAVAILABLE: local daemon connection failed") from exc
        try:
            response_data = json.loads(raw.decode("utf-8"))
            content = response_data["message"]["content"]
        except (
            AttributeError,
            KeyError,
            TypeError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise OllamaProviderError("OLLAMA_INVALID_RESPONSE: malformed chat response") from exc
        if not isinstance(content, str):
            raise OllamaProviderError("OLLAMA_INVALID_RESPONSE: assistant content is not text")
        try:
            result = json.loads(content)
        except json.JSONDecodeError as exc:
            raise OllamaProviderError(
                "OLLAMA_INVALID_RESPONSE: structured content is not JSON"
            ) from exc
        if not isinstance(result, dict):
            raise OllamaProviderError(
                "OLLAMA_INVALID_RESPONSE: structured content is not an object"
            )
        return cast(dict[str, Any], result)


def _is_repairable_contract_failure(error: OllamaProviderError) -> bool:
    """Only dataclass/domain validation failures qualify for a bounded repair."""
    return isinstance(error.__cause__, ValueError)


def _repair_feedback(data: dict[str, Any], qualitative_fields: tuple[str, ...]) -> str:
    """Give the model stable, non-sensitive feedback derived from the parsed object."""
    for field in qualitative_fields:
        value = data.get(field)
        values = (value,) if isinstance(value, str) else value if isinstance(value, list) else ()
        if any(isinstance(item, str) and any(char.isdigit() for char in item) for item in values):
            return (
                f"FIELD: {field}\n"
                "ERROR: qualitative field contains numeric content\n"
                "RULE: qualitative fields must contain no digits\n"
                "ACTION: move every numeric statement into numeric_claims only when it uses "
                "already supplied canonical deterministic evidence; otherwise remove it and "
                "rewrite the field without digits"
            )
    return (
        "FIELD: contract\n"
        "ERROR: structured output violates the domain contract\n"
        "RULE: return the complete object matching the supplied JSON Schema and contract\n"
        "ACTION: correct only the invalid contract content without inventing evidence or "
        "numeric claims"
    )


def _repair_instructions(stage: str) -> str:
    return (
        f"Repair the supplied {stage} structured output. Return the COMPLETE corrected object "
        "and nothing else. Preserve qualitative meaning. Do not invent new evidence or numeric "
        "claims. Use only an evidence_id from ALLOWED_EVIDENCE. Move numeric statements only "
        "when they can be represented using authorized evidence; otherwise remove unsupported "
        "numeric wording. All "
        "qualitative strings must contain no digits. Follow the supplied contract feedback and "
        "output JSON Schema exactly."
    )


def _qualitative_string() -> dict[str, object]:
    """A non-empty qualitative string; domain validation forbids all digits.

    Ollama's structured-output implementation does not reliably accept JSON Schema
    ``pattern`` constraints, so the prompt provides this semantic restriction and
    the provider-independent contract remains the fail-closed enforcement point.
    """
    return {"type": "string", "minLength": 1}


def _qualitative_string_array() -> dict[str, object]:
    return {"type": "array", "minItems": 1, "items": _qualitative_string()}


def _provider_context(
    artifact: dict[str, object],
    interpretation: DeterministicInterpretation,
    catalog: tuple[EvidenceCatalogEntry, ...],
) -> dict[str, object]:
    """Compact deterministic context; numerical provenance is exclusively catalogued."""
    return {
        "ticker": artifact["identity"]["ticker"],  # type: ignore[index]
        "interpretation": interpretation.to_dict(),
        "ALLOWED_EVIDENCE": [entry.to_dict() for entry in catalog],
    }


def _evidence_ref_schema(catalog: tuple[EvidenceCatalogEntry, ...]) -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["evidence_id"],
        "properties": {
            "evidence_id": {"type": "string", "enum": [entry.evidence_id for entry in catalog]},
        },
    }


def _numeric_claim_schema(catalog: tuple[EvidenceCatalogEntry, ...]) -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["evidence_id"],
        "properties": {
            "evidence_id": {"type": "string", "enum": [entry.evidence_id for entry in catalog]},
        },
    }


def _base_schema(properties: dict[str, object]) -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }


def _synthesis_schema(catalog: tuple[EvidenceCatalogEntry, ...]) -> dict[str, object]:
    properties: dict[str, object] = {
        "ticker": {"type": "string", "minLength": 1},
        "confidence": {"type": "string", "enum": [item.value for item in Confidence]},
        "evidence_refs": {
            "type": "array",
            "minItems": 1,
            "items": _evidence_ref_schema(catalog),
        },
        "numeric_claims": {"type": "array", "items": _numeric_claim_schema(catalog)},
    }
    properties.update(
        {field: _qualitative_string() for field in RESEARCH_SYNTHESIS_QUALITATIVE_TEXT_FIELDS}
    )
    properties.update(
        {
            field: _qualitative_string_array()
            for field in RESEARCH_SYNTHESIS_QUALITATIVE_ITEMS_FIELDS
        }
    )
    return _base_schema(properties)


def _challenge_schema(catalog: tuple[EvidenceCatalogEntry, ...]) -> dict[str, object]:
    properties: dict[str, object] = {
        "evidence_refs": {
            "type": "array",
            "minItems": 1,
            "items": _evidence_ref_schema(catalog),
        },
        "numeric_claims": {"type": "array", "items": _numeric_claim_schema(catalog)},
    }
    properties.update(
        {field: _qualitative_string_array() for field in THESIS_CHALLENGE_QUALITATIVE_ITEMS_FIELDS}
    )
    return _base_schema(properties)


def _catalog_entry(
    value: object, catalog: tuple[EvidenceCatalogEntry, ...]
) -> EvidenceCatalogEntry:
    if not isinstance(value, dict) or set(value) != {"evidence_id"}:
        raise OllamaProviderError("OLLAMA_INVALID_RESPONSE: invalid evidence reference")
    evidence_id = value.get("evidence_id")
    if not isinstance(evidence_id, str):
        raise OllamaProviderError("OLLAMA_INVALID_RESPONSE: invalid evidence reference")
    for entry in catalog:
        if entry.evidence_id == evidence_id:
            return entry
    raise OllamaProviderError("OLLAMA_INVALID_RESPONSE: unknown evidence_id")


def _evidence_ref(value: object, catalog: tuple[EvidenceCatalogEntry, ...]) -> EvidenceRef:
    return _catalog_entry(value, catalog).evidence_ref


def _numeric_claim(value: object, catalog: tuple[EvidenceCatalogEntry, ...]) -> NumericClaim:
    entry = _catalog_entry(value, catalog)
    return NumericClaim(
        label=entry.metric_label,
        value=entry.value,
        unit=entry.unit,
        evidence_ref=entry.evidence_ref,
    )


def _field_tuple(
    data: dict[str, Any], name: str, converter: Callable[[object], Any] = lambda x: x
) -> tuple[Any, ...]:
    value = data.get(name)
    if not isinstance(value, list):
        raise OllamaProviderError(f"OLLAMA_INVALID_RESPONSE: {name} must be an array")
    return tuple(converter(item) for item in value)


def _research_synthesis(
    data: dict[str, Any], catalog: tuple[EvidenceCatalogEntry, ...]
) -> ResearchSynthesis:
    expected = {
        "ticker",
        "assessment",
        "confidence",
        "thesis",
        "positive_evidence",
        "negative_evidence",
        "critical_assumptions",
        "invalidation_conditions",
        "open_questions",
        "evidence_refs",
        "numeric_claims",
    }
    if set(data) != expected:
        raise OllamaProviderError("OLLAMA_INVALID_RESPONSE: synthesis fields do not match contract")
    try:
        return ResearchSynthesis(
            ticker=data["ticker"],
            assessment=data["assessment"],
            confidence=Confidence(data["confidence"]),
            thesis=data["thesis"],
            positive_evidence=_field_tuple(data, "positive_evidence"),
            negative_evidence=_field_tuple(data, "negative_evidence"),
            critical_assumptions=_field_tuple(data, "critical_assumptions"),
            invalidation_conditions=_field_tuple(data, "invalidation_conditions"),
            open_questions=_field_tuple(data, "open_questions"),
            evidence_refs=_field_tuple(
                data, "evidence_refs", lambda value: _evidence_ref(value, catalog)
            ),
            numeric_claims=_field_tuple(
                data, "numeric_claims", lambda value: _numeric_claim(value, catalog)
            ),
        )
    except (TypeError, ValueError) as exc:
        raise OllamaProviderError("OLLAMA_INVALID_RESPONSE: synthesis violates contract") from exc


def _thesis_challenge(
    data: dict[str, Any], catalog: tuple[EvidenceCatalogEntry, ...]
) -> ThesisChallenge:
    expected = {
        "challenges",
        "fragile_assumptions",
        "missing_evidence",
        "potential_confirmation_bias",
        "evidence_refs",
        "numeric_claims",
    }
    if set(data) != expected:
        raise OllamaProviderError("OLLAMA_INVALID_RESPONSE: challenge fields do not match contract")
    try:
        return ThesisChallenge(
            challenges=_field_tuple(data, "challenges"),
            fragile_assumptions=_field_tuple(data, "fragile_assumptions"),
            missing_evidence=_field_tuple(data, "missing_evidence"),
            potential_confirmation_bias=_field_tuple(data, "potential_confirmation_bias"),
            evidence_refs=_field_tuple(
                data, "evidence_refs", lambda value: _evidence_ref(value, catalog)
            ),
            numeric_claims=_field_tuple(
                data, "numeric_claims", lambda value: _numeric_claim(value, catalog)
            ),
        )
    except (TypeError, ValueError) as exc:
        raise OllamaProviderError("OLLAMA_INVALID_RESPONSE: challenge violates contract") from exc
