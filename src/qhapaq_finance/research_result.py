"""Canonical, UI-independent deterministic research-result contract."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from .evidence_quality import canonical_json, content_identity
from .market_inputs import MarketProvenance
from .model_requirements import load_model_profile
from .universe import DomainRegistry, ResearchCapability, Security
from .valuation import ResearchResult, analyze_case, load_fixture_case


class ResearchResultError(ValueError):
    """A deterministic result cannot be represented by the canonical contract."""


@dataclass(frozen=True)
class CanonicalResearchResult:
    """Immutable semantic handoff from valuation to every downstream consumer."""

    schema_version: str
    research_identity: str
    research_as_of: date
    issuer: dict[str, str]
    security: dict[str, str]
    financial_evidence: dict[str, object]
    model: dict[str, object]
    market_provenance: MarketProvenance
    readiness: dict[str, object]
    valuation: dict[str, object]
    market_comparison: dict[str, object]
    reverse_valuation: dict[str, object]
    content_identity: str

    def payload(self, *, include_identity: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": self.schema_version,
            "research_identity": self.research_identity,
            "research_as_of": self.research_as_of.isoformat(),
            "issuer": self.issuer,
            "security": self.security,
            "financial_evidence": self.financial_evidence,
            "model": self.model,
            "market_provenance": self.market_provenance.to_dict(),
            "readiness": self.readiness,
            "valuation": self.valuation,
            "market_comparison": self.market_comparison,
            "reverse_valuation": self.reverse_valuation,
        }
        if include_identity:
            value["content_identity"] = self.content_identity
        return value

    def to_dict(self) -> dict[str, object]:
        return self.payload()


def _profile_identity(root: Path, reference: str) -> dict[str, object]:
    path = root / reference
    profile = load_model_profile(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchResultError("MODEL_PROFILE_UNAVAILABLE") from exc
    return {
        "profile_id": profile.profile_id,
        "version": profile.version,
        "content_identity": content_identity(raw),
    }


def _market(case_result: ResearchResult, security: Security) -> MarketProvenance:
    provenance = case_result.case.market_provenance
    if provenance is None:
        raise ResearchResultError("MARKET_PROVENANCE_REQUIRED")
    if provenance.security_id != security.security_id:
        raise ResearchResultError("RESULT_MARKET_SECURITY_MISMATCH")
    if provenance.issuer_id != security.issuer_id:
        raise ResearchResultError("RESULT_MARKET_ISSUER_MISMATCH")
    if provenance.research_as_of != case_result.case.as_of_date:
        raise ResearchResultError("RESULT_MARKET_AS_OF_MISMATCH")
    return provenance


def _valuation(
    result: ResearchResult,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    case = result.case
    scenarios = {
        item.name: {
            "enterprise_value": item.enterprise_value,
            "equity_value": item.equity_value,
            "intrinsic_value_per_share": item.intrinsic_value_per_share,
            "margin_of_safety": item.margin_of_safety,
            "explicit_growth": next(
                x.explicit_growth for x in case.scenarios if x.name == item.name
            ),
            "terminal_growth": item.terminal_growth,
            "years": next(x.years for x in case.scenarios if x.name == item.name),
            "terminal_spread": item.terminal_spread,
            "pv_explicit_period": item.pv_explicit_period,
            "pv_terminal_value": item.pv_terminal_value,
            "terminal_value_share": item.terminal_value_share,
            "warnings": list(item.warnings),
        }
        for item in result.scenarios
    }
    valuation = {
        "reconstructed_fcff": result.reconstructed_fcff,
        "normalized_fcff": result.normalized_fcff,
        "nopat": result.nopat,
        "roic": result.roic,
        "wacc": case.capital_cost.wacc,
        "roic_minus_wacc": result.roic_minus_wacc,
        "fcff_yield": result.fcff_yield,
        "scenarios": scenarios,
        "diagnostics": list(result.diagnostics),
    }
    comparison: dict[str, object] = {
        "price": case.market_snapshot.price,
        "market_equity": case.market_snapshot.equity_value,
        "enterprise_value": case.market_snapshot.enterprise_value,
        "fcff_implied_discount_rate": result.fcff_implied_discount_rate,
    }
    reverse: dict[str, object] = {
        "implied_growth": result.reverse_implied_growth,
        "expectation_growth_gap": result.expectation_growth_gap,
    }
    return valuation, comparison, reverse


def _stage_readiness(
    root: Path, model_ref: object, capability: ResearchCapability
) -> dict[str, object]:
    """Group the existing requirement decisions; this does not re-evaluate them."""
    if not isinstance(model_ref, str):
        return {}
    report = capability.model_readiness
    if report is None:
        return {}
    profile = load_model_profile(root / model_ref)
    statuses = {item.requirement_id: item.status.value for item in report.requirements}
    stages: dict[str, list[str]] = {}
    for requirement in profile.requirements:
        stages.setdefault(requirement.stage, []).append(requirement.identifier)
    return {
        stage: {
            "requirement_ids": identifiers,
            "ready": all(statuses[item] == "SATISFIED" for item in identifiers),
        }
        for stage, identifiers in sorted(stages.items())
    }


def build_canonical_research_result(
    ticker: str, repository_root: str | Path = "."
) -> CanonicalResearchResult:
    """Build the generic result from registered evidence, case, and valuation only."""
    root = Path(repository_root)
    registry = DomainRegistry(root)
    security = registry.security(ticker)
    result = analyze_case(load_fixture_case(security.ticker, root))
    if result.case.ticker != security.ticker:
        raise ResearchResultError("RESULT_SECURITY_TICKER_MISMATCH")
    market = _market(result, security)
    research = registry.research(security.issuer_id)
    capability = registry.capability(security.ticker)
    kind = research.get("kind")
    if kind not in {"evidence-backed", "fixture"}:
        raise ResearchResultError("RESULT_RESEARCH_KIND_UNSUPPORTED")
    quality = capability.quality_report
    model_ref = research.get("model_profile")
    financial_evidence: dict[str, object] = {
        "kind": kind,
        "issuer_evidence_identity": registry.issuer_for(security.ticker).evidence_identity,
        "quality": quality.to_dict() if quality else None,
    }
    capital = result.case.capital_cost
    model: dict[str, object] = (
        _profile_identity(root, model_ref)
        if model_ref
        else {"profile_id": None, "version": None, "content_identity": None}
    )
    readiness: dict[str, object] = {
        "financial_evidence_quality": quality.to_dict() if quality else None,
        "model_requirements": (
            capability.model_readiness.to_dict() if capability.model_readiness else None
        ),
        "market_quality_identity": market.market_quality_identity,
        "market_source_mode": market.source_mode,
        "model_stage_readiness": _stage_readiness(root, model_ref, capability),
        "deterministic_research_ready": capability.deterministic_research_ready,
        "agent_research_ready": capability.agent_research_ready,
        "capital_cost_ready": capital.source_mode == "canonical" and capital.provenance is not None,
        "valuation_ready": capital.source_mode == "canonical" and capital.provenance is not None,
    }
    financial_evidence["capital_cost"] = {
        "source_mode": capital.source_mode,
        "provenance_identity": getattr(capital.provenance, "content_identity", None),
    }
    valuation, comparison, reverse = _valuation(result)
    draft = CanonicalResearchResult(
        "research-result-v1",
        content_identity(
            {
                "issuer_id": security.issuer_id,
                "security_id": security.security_id,
                "research_as_of": result.case.as_of_date.isoformat(),
            }
        ),
        result.case.as_of_date,
        {
            "issuer_id": security.issuer_id,
            "display_name": registry.issuer_for(security.ticker).display_name,
        },
        {
            "security_id": security.security_id,
            "ticker": security.ticker,
            "exchange": security.exchange,
            "share_class": security.share_class,
        },
        financial_evidence,
        model,
        market,
        readiness,
        valuation,
        comparison,
        reverse,
        "",
    )
    return CanonicalResearchResult(
        **{
            **draft.__dict__,
            "content_identity": content_identity(draft.payload(include_identity=False)),
        }
    )


def canonical_research_json(result: CanonicalResearchResult) -> str:
    """Stable JSON for CLI, exports, and persisted result artifacts."""
    return canonical_json(result.to_dict()) + "\n"


def agent_projection(result: CanonicalResearchResult) -> dict[str, Any]:
    """Bounded legacy-shaped numeric projection; it has no independent domain truth."""
    base = result.valuation["scenarios"]["base"]  # type: ignore[index]
    return {
        "schema_version": "research-result-agent-projection-v1",
        "canonical_result_identity": result.content_identity,
        "identity": {"ticker": result.security["ticker"]},
        "market": {"price": result.market_comparison["price"]},
        "economics": {
            "roic_minus_wacc": result.valuation["roic_minus_wacc"],
        },
        "valuation": {
            "scenarios": {
                "base": {
                    "intrinsic_value": base["intrinsic_value_per_share"],
                    "margin_of_safety": base["margin_of_safety"],
                    "terminal_value_share": base["terminal_value_share"],
                }
            },
            "expectations": {
                "growth_difference_pp": result.reverse_valuation["expectation_growth_gap"]
            },
        },
        "sensitivity": {"wacc_terminal_growth": {"cells": [[base["intrinsic_value_per_share"]]]}},
    }
