"""Validated market-input bundle consumed by deterministic valuation loaders."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .market import FreshnessPolicy, MarketSnapshot, fetch_yfinance_snapshot, write_market_snapshot
from .market_evidence import MarketEvidenceError, evaluate_market_quality
from .universe import DomainRegistry


class MarketInputError(ValueError):
    """Canonical market evidence exists but cannot safely supply the requested input."""


@dataclass(frozen=True)
class MarketProvenance:
    security_id: str
    issuer_id: str
    source_mode: str
    observed_at: datetime | None
    research_as_of: date
    currency: str
    price_fact_identity: str | None = None
    market_quality_identity: str | None = None
    canonical_observation_identity: str | None = None
    source_manifest_identity: str | None = None
    market_equity_provenance: str | None = None

    def __post_init__(self) -> None:
        if self.source_mode not in {"canonical", "legacy", "fixture"}:
            raise MarketInputError("MARKET_PROVENANCE_MODE_INVALID")
        if self.source_mode == "canonical" and not all(
            (
                self.price_fact_identity,
                self.market_quality_identity,
                self.canonical_observation_identity,
            )
        ):
            raise MarketInputError("MARKET_PROVENANCE_CANONICAL_INCOMPLETE")
        if self.source_mode != "canonical" and any(
            (
                self.price_fact_identity,
                self.market_quality_identity,
                self.canonical_observation_identity,
            )
        ):
            raise MarketInputError("MARKET_PROVENANCE_MODE_MIXED")

    def to_dict(self) -> dict[str, object]:
        return {
            "security_id": self.security_id,
            "issuer_id": self.issuer_id,
            "source_mode": self.source_mode,
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
            "research_as_of": self.research_as_of.isoformat(),
            "currency": self.currency,
            "price_fact_identity": self.price_fact_identity,
            "market_quality_identity": self.market_quality_identity,
            "canonical_observation_identity": self.canonical_observation_identity,
            "source_manifest_identity": self.source_manifest_identity,
            "market_equity_provenance": self.market_equity_provenance,
        }

    @property
    def content_identity(self) -> str:
        from .evidence_quality import content_identity

        return content_identity(self.to_dict())


@dataclass(frozen=True)
class MarketInput:
    security_id: str
    issuer_id: str
    observed_at: datetime | None
    currency: str
    price: float
    price_provenance: str
    source_kind: str
    quality_identity: str | None
    market_equity: float | None
    market_equity_provenance: str
    price_fact_identity: str | None = None
    canonical_observation_identity: str | None = None
    source_manifest_identity: str | None = None

    def provenance(self, research_as_of: date) -> MarketProvenance:
        return MarketProvenance(
            self.security_id,
            self.issuer_id,
            self.source_kind,
            self.observed_at,
            research_as_of,
            self.currency,
            self.price_fact_identity,
            self.quality_identity,
            self.canonical_observation_identity,
            self.source_manifest_identity,
            self.market_equity_provenance,
        )


def _market_input_from_profile(
    *,
    root: str | Path,
    ticker: str,
    profile: str | Path,
    evaluation_as_of: date,
    valuation_shares: float,
    expected_currency: str | None = None,
    evaluation_at: datetime | None = None,
) -> MarketInput:
    registry = DomainRegistry(root)
    security = registry.security(ticker)
    try:
        report = evaluate_market_quality(
            Path(root) / profile,
            registry=registry,
            root=root,
            now=evaluation_at
            or datetime.combine(evaluation_as_of, datetime.min.time(), tzinfo=timezone.utc),
        )
    except MarketEvidenceError as exc:
        raise MarketInputError("MARKET_QUALITY_FAILED") from exc
    if not report.ready:
        raise MarketInputError("MARKET_QUALITY_FAILED")
    price = next(
        (item for item in report.canonical_facts if item.normalized.metric_id == "price"), None
    )
    if price is None:
        raise MarketInputError("MARKET_PRICE_UNAVAILABLE")
    if expected_currency is not None and price.normalized.currency != expected_currency:
        raise MarketInputError("MARKET_CURRENCY_MISMATCH")
    return MarketInput(
        security.security_id,
        security.issuer_id,
        price.normalized.observed_at,
        price.normalized.currency,
        price.normalized.value,
        f"canonical market fact {price.identifier}",
        "canonical",
        report.immutable_identity,
        price.normalized.value * valuation_shares,
        "canonical price × existing valuation share basis",
        price.identifier,
        price.normalized.immutable_identity,
        price.normalized.source_manifest_ref,
    )


def canonical_market_input(
    *, root: str | Path, ticker: str, evaluation_as_of: date, valuation_shares: float
) -> MarketInput | None:
    """Return canonical inputs; only no profile returns None, never a failed fallback."""
    registry = DomainRegistry(root)
    security = registry.security(ticker)
    profile = registry.research(security.issuer_id).get("market_quality_profile")
    if not profile:
        return None
    return _market_input_from_profile(
        root=root,
        ticker=ticker,
        profile=profile,
        evaluation_as_of=evaluation_as_of,
        valuation_shares=valuation_shares,
    )


def cache_yfinance_snapshot(
    *,
    root: str | Path,
    ticker: str,
    max_age: timedelta,
    fetcher: Callable[..., MarketSnapshot] = fetch_yfinance_snapshot,
    now: datetime | None = None,
) -> Path:
    """Fetch one registered security observation and bind it into the operational cache."""
    FreshnessPolicy(max_age=max_age)
    max_age_seconds = int(max_age.total_seconds())
    if max_age_seconds <= 0 or timedelta(seconds=max_age_seconds) != max_age:
        raise MarketInputError("MARKET_CACHE_FRESHNESS_INVALID")
    root_path = Path(root)
    registry = DomainRegistry(root_path)
    security = registry.security(ticker)
    snapshot = fetcher(security.ticker, now=now)
    if snapshot.ticker.strip().upper() != security.ticker or snapshot.source != "yfinance":
        raise MarketInputError("MARKET_CACHE_OBSERVATION_IDENTITY_INVALID")
    cache = root_path / "data/cache/market/yfinance" / security.security_id.replace(":", "_")
    raw = write_market_snapshot(snapshot, cache / "snapshot.json")
    raw_relative = raw.relative_to(root_path).as_posix()
    manifest = cache / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "market-source-manifest-v1",
                "security_id": security.security_id,
                "source_id": f"yfinance:{security.security_id}",
                "provider": "yfinance",
                "raw_artifact": raw_relative,
                "raw_artifact_sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    profile = cache / "market-quality-profile.json"
    profile.write_text(
        json.dumps(
            {
                "schema_version": "market-quality-profile-v1",
                "security_id": security.security_id,
                "source_manifests": [manifest.relative_to(root_path).as_posix()],
                "authority_policy": {"market_price": {"yfinance": 1}},
                "max_age_seconds": max_age_seconds,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return profile


def cached_canonical_market_input(
    *,
    root: str | Path,
    ticker: str,
    profile: str | Path,
    evaluation_as_of: date,
    valuation_shares: float,
    expected_currency: str | None = None,
    evaluation_at: datetime | None = None,
) -> MarketInput:
    """Promote an operationally cached observation through the canonical quality gates."""
    return _market_input_from_profile(
        root=root,
        ticker=ticker,
        profile=profile,
        evaluation_as_of=evaluation_as_of,
        valuation_shares=valuation_shares,
        expected_currency=expected_currency,
        evaluation_at=evaluation_at,
    )


def legacy_market_input(
    *, security_id: str, issuer_id: str, snapshot: MarketSnapshot, valuation_shares: float
) -> MarketInput:
    """Explicit compatibility adapter; this does not upgrade an observation to canonical."""
    return MarketInput(
        security_id,
        issuer_id,
        snapshot.observed_at,
        snapshot.currency,
        snapshot.price,
        f"legacy observation · {snapshot.source}",
        "legacy",
        None,
        snapshot.price * valuation_shares,
        "legacy price × existing valuation share basis",
    )


def compatibility_market_provenance(
    *, root: str | Path, ticker: str, research_as_of: date, source_mode: str
) -> MarketProvenance:
    security = DomainRegistry(root).security(ticker)
    return MarketProvenance(
        security.security_id, security.issuer_id, source_mode, None, research_as_of, "USD"
    )
