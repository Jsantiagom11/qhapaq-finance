"""Offline, security-level canonical market evidence.

This layer consumes frozen provider observations.  It does not fetch data and does
not treat a provider field as canonical until provenance, identity, freshness, and
authority gates have passed.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .evidence import FinancialFact
from .evidence_quality import Gate, GateStatus, canonical_json
from .market import (
    Freshness,
    FreshnessPolicy,
    MarketDataError,
    MarketSnapshot,
    classify_freshness,
    load_market_snapshot,
)


class MarketEvidenceError(ValueError):
    """A market evidence artifact violates the deterministic contract."""


@dataclass(frozen=True)
class MarketSourceManifest:
    schema_version: str
    security_id: str
    source_id: str
    provider: str
    raw_artifact: Path
    raw_artifact_sha256: str


@dataclass(frozen=True)
class NormalizedMarketObservation:
    security_id: str
    metric_id: str
    value: float
    unit: str
    currency: str
    observed_at: datetime
    retrieved_at: datetime
    source_id: str
    provider: str
    market_state: str
    source_manifest_ref: str
    immutable_identity: str


@dataclass(frozen=True)
class CanonicalMarketFact:
    identifier: str
    normalized: NormalizedMarketObservation
    accepted_by: str


@dataclass(frozen=True)
class MarketQualityReport:
    schema_version: str
    security_id: str
    gates: tuple[Gate, ...]
    canonical_facts: tuple[CanonicalMarketFact, ...]
    immutable_identity: str
    evaluation_identity: str

    @property
    def ready(self) -> bool:
        return not any(item.blocking and item.status is GateStatus.FAIL for item in self.gates)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "security_id": self.security_id,
            "gates": [
                {
                    "id": item.identifier,
                    "status": item.status.value,
                    "blocking": item.blocking,
                    "failures": list(item.failures),
                    "references": list(item.references),
                }
                for item in self.gates
            ],
            "canonical_facts": [market_fact_dict(item) for item in self.canonical_facts],
            "immutable_identity": self.immutable_identity,
            "evaluation_identity": self.evaluation_identity,
            "ready": self.ready,
        }


@dataclass(frozen=True)
class DerivedMarketCap:
    identifier: str
    value: float
    currency: str
    price_fact_id: str
    share_fact_id: str
    formula: str


@dataclass(frozen=True)
class MarketCapReconciliation:
    status: GateStatus
    blocking: bool
    derived_value: float
    provider_value: float
    absolute_difference: float
    relative_difference: float
    tolerance: float
    source_refs: tuple[str, ...]


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MarketEvidenceError(f"market {name} must be a non-empty string")
    return value.strip()


def _positive(value: Any, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) <= 0
    ):
        raise MarketEvidenceError(f"market {name} must be finite and positive")
    return float(value)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MarketEvidenceError("MARKET_ARTIFACT_INVALID") from exc
    if not isinstance(raw, dict):
        raise MarketEvidenceError("MARKET_ARTIFACT_INVALID")
    return raw


def load_market_source_manifest(path: str | Path, root: str | Path = ".") -> MarketSourceManifest:
    raw = _load_json(Path(path))
    if raw.get("schema_version") != "market-source-manifest-v1":
        raise MarketEvidenceError("MARKET_MANIFEST_INVALID")
    relative = Path(_text(raw.get("raw_artifact"), "raw_artifact"))
    if relative.is_absolute() or ".." in relative.parts:
        raise MarketEvidenceError("MARKET_MANIFEST_INVALID")
    return MarketSourceManifest(
        "market-source-manifest-v1",
        _text(raw.get("security_id"), "security_id"),
        _text(raw.get("source_id"), "source_id"),
        _text(raw.get("provider"), "provider"),
        Path(root).resolve() / relative,
        _text(raw.get("raw_artifact_sha256"), "raw_artifact_sha256"),
    )


def verify_market_source_integrity(manifest: MarketSourceManifest) -> None:
    if not manifest.raw_artifact.is_file():
        raise MarketEvidenceError("MARKET_SOURCE_MISSING")
    if (
        hashlib.sha256(manifest.raw_artifact.read_bytes()).hexdigest()
        != manifest.raw_artifact_sha256
    ):
        raise MarketEvidenceError("MARKET_HASH_MISMATCH")


def _normalized(manifest: MarketSourceManifest) -> tuple[NormalizedMarketObservation, ...]:
    try:
        snapshot: MarketSnapshot = load_market_snapshot(manifest.raw_artifact)
    except MarketDataError as exc:
        raise MarketEvidenceError(f"MARKET_OBSERVATION_INVALID: {exc}") from exc
    if snapshot.source != manifest.provider:
        raise MarketEvidenceError("MARKET_PROVIDER_MISMATCH")
    items = [("price", snapshot.price, "currency_per_share")]
    if snapshot.market_cap is not None:
        items.append(("provider_market_cap", snapshot.market_cap, "currency"))
    return tuple(
        NormalizedMarketObservation(
            metric_id=metric,
            value=value,
            unit=unit,
            immutable_identity=hashlib.sha256(
                canonical_json(
                    {
                        "security_id": manifest.security_id,
                        "currency": snapshot.currency,
                        "observed_at": snapshot.observed_at.isoformat(),
                        "retrieved_at": snapshot.retrieved_at.isoformat(),
                        "metric_id": metric,
                        "value": value,
                        "unit": unit,
                    }
                ).encode()
            ).hexdigest(),
            security_id=manifest.security_id,
            currency=snapshot.currency,
            observed_at=snapshot.observed_at,
            retrieved_at=snapshot.retrieved_at,
            source_id=manifest.source_id,
            provider=manifest.provider,
            market_state=snapshot.market_state.value,
            source_manifest_ref=manifest.source_id,
        )
        for metric, value, unit in items
    )


def market_fact_dict(fact: CanonicalMarketFact) -> dict[str, object]:
    item = fact.normalized
    return {
        "id": fact.identifier,
        "metric_id": item.metric_id,
        "value": item.value,
        "unit": item.unit,
        "currency": item.currency,
        "security_id": item.security_id,
        "observed_at": item.observed_at.isoformat(),
        "retrieved_at": item.retrieved_at.isoformat(),
        "source_id": item.source_id,
        "provider": item.provider,
        "market_state": item.market_state,
        "source_manifest_ref": item.source_manifest_ref,
        "immutable_identity": item.immutable_identity,
        "accepted_by": fact.accepted_by,
    }


def evaluate_market_quality(
    profile_path: str | Path, *, registry: Any, root: str | Path = ".", now: datetime
) -> MarketQualityReport:
    """Evaluate a frozen security-level profile with an injected evaluation clock."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise MarketEvidenceError("MARKET_EVALUATION_CLOCK_NAIVE")
    profile = _load_json(Path(profile_path))
    if profile.get("schema_version") != "market-quality-profile-v1":
        raise MarketEvidenceError("MARKET_PROFILE_INVALID")
    security_id = _text(profile.get("security_id"), "security_id")
    try:
        security = registry.security_id(security_id)
    except Exception as exc:
        raise MarketEvidenceError("MARKET_SECURITY_UNKNOWN") from exc
    paths = profile.get("source_manifests")
    policy = profile.get("authority_policy")
    if (
        not isinstance(paths, list)
        or not paths
        or not isinstance(policy, dict)
        or not isinstance(policy.get("market_price"), dict)
    ):
        raise MarketEvidenceError("MARKET_PROFILE_INVALID")
    manifests = tuple(load_market_source_manifest(Path(root) / value, root) for value in paths)
    observations: list[NormalizedMarketObservation] = []
    failures: list[str] = []
    for manifest in manifests:
        try:
            if manifest.security_id != security.security_id:
                raise MarketEvidenceError("MARKET_SECURITY_MISMATCH")
            verify_market_source_integrity(manifest)
            observations.extend(_normalized(manifest))
        except MarketEvidenceError as exc:
            failures.append(str(exc))
    gates: list[Gate] = [
        Gate(
            "provenance",
            GateStatus.PASS if not failures else GateStatus.FAIL,
            True,
            tuple(failures),
            tuple(item.source_id for item in manifests),
        ),
        Gate(
            "source_integrity",
            GateStatus.PASS if not failures else GateStatus.FAIL,
            True,
            tuple(failures),
            tuple(item.source_id for item in manifests),
        ),
        Gate(
            "security_identity",
            GateStatus.PASS if not failures else GateStatus.FAIL,
            True,
            tuple(failures),
            (security.security_id,),
        ),
    ]
    prices = [item for item in observations if item.metric_id == "price"]
    freshness_required = profile.get("max_age_seconds")
    if freshness_required is None:
        gates.append(Gate("freshness", GateStatus.NOT_APPLICABLE, False))
    else:
        if not isinstance(freshness_required, int) or freshness_required <= 0:
            raise MarketEvidenceError("MARKET_PROFILE_INVALID")
        states = [
            classify_freshness(
                MarketSnapshot(
                    ticker=security.ticker,
                    price=item.value,
                    currency=item.currency,
                    observed_at=item.observed_at,
                    retrieved_at=item.retrieved_at,
                    source=item.provider,
                ),
                policy=FreshnessPolicy(max_age=timedelta(seconds=freshness_required)),
                now=now,
            )
            for item in prices
        ]
        status = (
            GateStatus.PASS
            if states and all(item is Freshness.FRESH for item in states)
            else GateStatus.FAIL
        )
        gates.append(
            Gate(
                "freshness",
                status,
                True,
                () if status is GateStatus.PASS else tuple(item.value for item in states),
            )
        )
    ranked = sorted(
        prices, key=lambda item: policy["market_price"].get(item.provider, -1), reverse=True
    )
    canonical: list[CanonicalMarketFact] = []
    if not ranked:
        gates.append(Gate("authority", GateStatus.FAIL, True, ("MARKET_PRICE_MISSING",)))
    else:
        top = policy["market_price"].get(ranked[0].provider, -1)
        winners = [item for item in ranked if policy["market_price"].get(item.provider, -1) == top]
        if len({(item.value, item.currency, item.unit) for item in winners}) != 1:
            gates.append(Gate("authority", GateStatus.FAIL, True, ("MARKET_SOURCE_CONFLICT",)))
        else:
            selected = winners[0]
            gates.extend(
                (
                    Gate("currency", GateStatus.PASS, True, references=(selected.currency,)),
                    Gate(
                        "unit",
                        GateStatus.PASS
                        if selected.unit == "currency_per_share"
                        else GateStatus.FAIL,
                        True,
                    ),
                    Gate("timestamp_validity", GateStatus.PASS, True),
                    Gate(
                        "market_state_semantics",
                        GateStatus.PASS,
                        True,
                        references=(selected.market_state,),
                    ),
                    Gate("authority", GateStatus.PASS, True, references=(selected.provider,)),
                )
            )
            canonical.append(CanonicalMarketFact("price", selected, "market-quality-v1"))
    immutable = hashlib.sha256(
        canonical_json([market_fact_dict(item) for item in canonical]).encode()
    ).hexdigest()
    evaluation = hashlib.sha256(
        canonical_json(
            {
                "immutable_identity": immutable,
                "now": now.isoformat(),
                "gates": [{"id": item.identifier, "status": item.status.value} for item in gates],
            }
        ).encode()
    ).hexdigest()
    return MarketQualityReport(
        "market-quality-report-v1",
        security_id,
        tuple(gates),
        tuple(canonical),
        immutable,
        evaluation,
    )


def derive_market_cap(
    *,
    price: CanonicalMarketFact,
    shares: FinancialFact,
    share_count_semantic: str,
    security_has_single_listed_share_class: bool,
) -> DerivedMarketCap:
    """Only current outstanding shares for a single listed share class may derive equity value."""
    if price.normalized.metric_id != "price" or price.normalized.unit != "currency_per_share":
        raise MarketEvidenceError("MARKET_PRICE_INCOMPATIBLE")
    if (
        share_count_semantic != "current_shares_outstanding"
        or shares.concept != "EntityCommonStockSharesOutstanding"
    ):
        raise MarketEvidenceError("MARKET_SHARE_COUNT_INELIGIBLE")
    if not security_has_single_listed_share_class:
        raise MarketEvidenceError("MARKET_SHARE_CLASS_AMBIGUOUS")
    if shares.period_kind.value != "INSTANT" or shares.unit != "million shares":
        raise MarketEvidenceError("MARKET_SHARE_COUNT_INELIGIBLE")
    value = price.normalized.value * shares.value * 1_000_000
    return DerivedMarketCap(
        "derived_market_cap",
        value,
        price.normalized.currency,
        price.identifier,
        shares.id,
        "canonical security price × eligible current shares outstanding",
    )


def reconcile_market_cap(
    *,
    derived: DerivedMarketCap,
    provider: NormalizedMarketObservation,
    tolerance: float,
    blocking: bool,
) -> MarketCapReconciliation:
    if (
        provider.metric_id != "provider_market_cap"
        or provider.currency != derived.currency
        or tolerance < 0
    ):
        raise MarketEvidenceError("MARKET_CAP_RECONCILIATION_INVALID")
    absolute = abs(derived.value - provider.value)
    relative = absolute / derived.value
    status = GateStatus.PASS if relative <= tolerance else GateStatus.FAIL
    return MarketCapReconciliation(
        status,
        blocking,
        derived.value,
        provider.value,
        absolute,
        relative,
        tolerance,
        (derived.price_fact_id, derived.share_fact_id, provider.source_id),
    )
