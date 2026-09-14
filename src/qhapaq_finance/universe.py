"""Declarative issuer, security, universe, and research-capability registry."""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from .evidence import load_facts
from .evidence_quality import EvidenceQualityError, QualityReport, evaluate_quality
from .model_requirements import ModelReadinessReport, evaluate_model_readiness, load_model_profile


class UniverseError(ValueError):
    """Explicit registry, membership, or research-readiness failure."""


@dataclass(frozen=True)
class Issuer:
    id: str
    display_name: str
    evidence_identity: str


@dataclass(frozen=True)
class Security:
    security_id: str
    ticker: str
    issuer_id: str
    exchange: str
    share_class: str


@dataclass(frozen=True)
class ResearchCapability:
    universe_member: bool
    evidence_available: bool
    deterministic_research_ready: bool
    agent_research_ready: bool
    research_kind: str | None
    quality_report: QualityReport | None = None
    model_readiness: ModelReadinessReport | None = None


@dataclass(frozen=True)
class UniverseSnapshot:
    universe_id: str
    as_of: date
    provenance: str
    securities: tuple[Security, ...]


def _root(root: str | Path) -> Path:
    return Path(root)


class DomainRegistry:
    def __init__(self, root: str | Path = ".") -> None:
        self.root = _root(root)
        try:
            payload = json.loads(
                (self.root / "data/domain/issuers.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise UniverseError("issuer/security registry is unavailable") from exc
        if payload.get("schema_version") != "issuer-security-registry-v1":
            raise UniverseError("unsupported issuer/security registry schema")
        self._issuers: dict[str, Issuer] = {}
        self._securities: dict[str, Security] = {}
        self._research: dict[str, dict[str, Any]] = {}
        for item in payload.get("issuers", []):
            issuer = Issuer(item["id"], item["display_name"], item["evidence_identity"])
            if issuer.id in self._issuers:
                raise UniverseError(f"duplicate issuer id: {issuer.id}")
            self._issuers[issuer.id] = issuer
            self._research[issuer.id] = dict(item.get("research", {}))
            for security_data in item.get("securities", []):
                security = Security(
                    security_data.get(
                        "security_id", f"{issuer.id}:{security_data['ticker'].upper()}"
                    ),
                    security_data["ticker"].upper(),
                    issuer.id,
                    security_data["exchange"],
                    security_data["share_class"],
                )
                if security.ticker in self._securities:
                    raise UniverseError(f"duplicate security ticker: {security.ticker}")
                self._securities[security.ticker] = security

    def security(self, ticker: str) -> Security:
        value = ticker.strip().upper()
        try:
            return self._securities[value]
        except KeyError as exc:
            raise UniverseError(f"unknown security: {value}") from exc

    def issuer_for(self, ticker: str) -> Issuer:
        return self._issuers[self.security(ticker).issuer_id]

    def security_id(self, security_id: str) -> Security:
        for security in self._securities.values():
            if security.security_id == security_id:
                return security
        raise UniverseError(f"unknown security identity: {security_id}")

    def research(self, issuer_id: str) -> dict[str, Any]:
        return self._research.get(issuer_id, {}).copy()

    def capability(
        self, ticker: str, snapshot: UniverseSnapshot | None = None
    ) -> ResearchCapability:
        security = self.security(ticker)
        research = self.research(security.issuer_id)
        kind = research.get("kind")
        profile = research.get("quality_profile")
        report: QualityReport | None = None
        model_readiness: ModelReadinessReport | None = None
        if profile:
            try:
                report = evaluate_quality(self.root / profile, self.root)
                model_path = research.get("model_profile")
                evidence_path = research.get("evidence_manifest")
                as_of = research.get("as_of")
                if model_path and evidence_path and as_of:
                    model_readiness = evaluate_model_readiness(
                        load_model_profile(self.root / model_path),
                        load_facts(
                            self.root / evidence_path,
                            self.root,
                            as_of=date.fromisoformat(as_of),
                        ),
                        report,
                    )
            except (EvidenceQualityError, ValueError, OSError):
                report = None
        evidence = report is not None
        deterministic = bool(
            report
            and model_readiness
            and model_readiness.model_ready
            and research.get("deterministic_loader")
        )
        member = snapshot is not None and any(
            item.ticker == security.ticker for item in snapshot.securities
        )
        return ResearchCapability(
            member,
            evidence,
            deterministic,
            bool(deterministic and research.get("agent_eligible")),
            kind,
            report,
            model_readiness,
        )

    def load_case(self, ticker: str) -> Any:
        security = self.security(ticker)
        research = self.research(security.issuer_id)
        loader = research.get("deterministic_loader")
        capability = self.capability(ticker)
        if loader and not capability.deterministic_research_ready:
            raise UniverseError(
                f"deterministic research unavailable for {security.ticker}: "
                "validated evidence is unavailable"
            )
        if loader:
            module_name, function_name = loader.split(":", maxsplit=1)
            return getattr(importlib.import_module(module_name), function_name)(self.root)
        fixture = research.get("fixture_path")
        if fixture and (self.root / fixture).is_file():
            # Explicitly labelled synthetic fixtures remain test/demo inputs, not
            # evidence-backed research capability.
            from .valuation import load_research_case

            return load_research_case(self.root / fixture)
        raise UniverseError(
            f"deterministic research unavailable for {security.ticker}: "
            "validated evidence is unavailable"
        )

    def audit(self, ticker: str) -> tuple[Path, date, Any] | None:
        security = self.security(ticker)
        research = self.research(security.issuer_id)
        audit = research.get("audit")
        manifest = research.get("evidence_manifest")
        as_of = research.get("as_of")
        if not (audit and manifest and as_of):
            return None
        module_name, function_name = audit.split(":", maxsplit=1)
        return (
            Path(manifest),
            date.fromisoformat(as_of),
            getattr(importlib.import_module(module_name), function_name),
        )


def load_universe(universe_id: str, root: str | Path = ".") -> UniverseSnapshot:
    directory = _root(root) / "data/universes"
    matches = sorted(directory.glob(f"{universe_id}-*.json"))
    if len(matches) != 1:
        raise UniverseError(f"universe unavailable: {universe_id}")
    try:
        payload = json.loads(matches[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UniverseError(f"universe unavailable: {universe_id}") from exc
    if payload.get("schema_version") != "universe-snapshot-v1":
        raise UniverseError("unsupported universe snapshot schema")
    registry = DomainRegistry(root)
    items = payload.get("constituents", [])
    if [item.get("rank") for item in items] != list(range(1, len(items) + 1)):
        raise UniverseError("universe constituent ranks must be contiguous and ordered")
    securities = tuple(registry.security(item["ticker"]) for item in items)
    if len({item.ticker for item in securities}) != len(securities):
        raise UniverseError("universe contains duplicate securities")
    if any(
        item["issuer_id"] != security.issuer_id
        for item, security in zip(items, securities, strict=True)
    ):
        raise UniverseError("universe issuer reference does not match security registry")
    return UniverseSnapshot(
        payload["universe_id"],
        date.fromisoformat(payload["as_of"]),
        payload["provenance"],
        securities,
    )


def issuer_batch_plan(
    snapshot: UniverseSnapshot, registry: DomainRegistry, *, agent_only: bool = False
) -> tuple[Issuer, ...]:
    """Ordered, issuer-deduplicated plan; no provider work happens here."""
    seen: set[str] = set()
    plan: list[Issuer] = []
    for security in snapshot.securities:
        if security.issuer_id in seen:
            continue
        capability = registry.capability(security.ticker, snapshot)
        if not agent_only or capability.agent_research_ready:
            plan.append(registry.issuer_for(security.ticker))
        seen.add(security.issuer_id)
    return tuple(plan)
