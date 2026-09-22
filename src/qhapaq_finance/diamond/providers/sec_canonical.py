"""Canonical issuer-level SEC snapshot cache."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from qhapaq_finance.diamond.cache import DiamondCache, DiamondCacheError
from qhapaq_finance.diamond.canonical_json import sha256_canonical_json
from qhapaq_finance.diamond.contracts import (
    FiscalSlot,
    FundamentalObservation,
    FundamentalPeriodType,
    PeriodKind,
    UnitKind,
)

CANONICAL_SCHEMA_VERSION = "diamond-canonical-issuer-v1"
SEC_CANONICALIZER_VERSION = "sec-canonicalizer-v2"


class SecCanonicalError(RuntimeError):
    """Canonical SEC issuer data cannot be trusted."""


@dataclass(frozen=True, slots=True)
class CanonicalIssuerSnapshot:
    schema_version: str
    canonicalizer_version: str
    issuer_id: str
    cik: str
    as_of: date
    history_years: int
    evidence_revision_sha256: str
    fundamental_period_type: FundamentalPeriodType
    fundamental_period_end: date
    fiscal_year_end: str | None
    observations: tuple[FundamentalObservation, ...]


def _identity_payload(
    *,
    schema_version: str,
    canonicalizer_version: str,
    issuer_id: str,
    as_of: date,
    history_years: int,
    evidence_revision_sha256: str,
) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "canonicalizer_version": canonicalizer_version,
        "issuer_id": issuer_id,
        "as_of": as_of.isoformat(),
        "history_years": history_years,
        "evidence_revision_sha256": evidence_revision_sha256,
    }


def _observation_payload(observation: FundamentalObservation) -> dict[str, object]:
    return {
        "metric_id": observation.metric_id,
        "fiscal_slot": observation.fiscal_slot.value,
        "value": observation.value,
        "period_start": (
            observation.period_start.isoformat() if observation.period_start is not None else None
        ),
        "period_end": observation.period_end.isoformat(),
        "period_kind": observation.period_kind.value,
        "unit_kind": observation.unit_kind.value,
        "source_provider": observation.source_provider,
        "source_identity": observation.source_identity,
        "share_class_id": observation.share_class_id,
        "adjustment_basis_id": observation.adjustment_basis_id,
    }


def _snapshot_payload(snapshot: CanonicalIssuerSnapshot) -> dict[str, object]:
    return {
        "schema_version": snapshot.schema_version,
        "canonicalizer_version": snapshot.canonicalizer_version,
        "issuer_id": snapshot.issuer_id,
        "cik": snapshot.cik,
        "as_of": snapshot.as_of.isoformat(),
        "history_years": snapshot.history_years,
        "evidence_revision_sha256": snapshot.evidence_revision_sha256,
        "fundamental_period_type": snapshot.fundamental_period_type.value,
        "fundamental_period_end": snapshot.fundamental_period_end.isoformat(),
        "fiscal_year_end": snapshot.fiscal_year_end,
        "observations": [
            _observation_payload(observation) for observation in snapshot.observations
        ],
    }


def _required_text(
    payload: Mapping[str, object],
    field: str,
) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise SecCanonicalError("CANONICAL_CACHE_PAYLOAD_INVALID")
    return value


def _decode_observation(raw: object) -> FundamentalObservation:
    if not isinstance(raw, Mapping):
        raise SecCanonicalError("CANONICAL_CACHE_PAYLOAD_INVALID")

    try:
        period_start_raw = raw.get("period_start")
        source_identity_raw = raw.get("source_identity")
        share_class_raw = raw.get("share_class_id")
        adjustment_basis_raw = raw.get("adjustment_basis_id")
        value_raw = raw["value"]

        if isinstance(value_raw, bool) or not isinstance(value_raw, (int, float)):
            raise SecCanonicalError("CANONICAL_CACHE_PAYLOAD_INVALID")

        if period_start_raw is not None and not isinstance(period_start_raw, str):
            raise SecCanonicalError("CANONICAL_CACHE_PAYLOAD_INVALID")
        if source_identity_raw is not None and not isinstance(source_identity_raw, str):
            raise SecCanonicalError("CANONICAL_CACHE_PAYLOAD_INVALID")
        if share_class_raw is not None and not isinstance(share_class_raw, str):
            raise SecCanonicalError("CANONICAL_CACHE_PAYLOAD_INVALID")
        if adjustment_basis_raw is not None and not isinstance(
            adjustment_basis_raw,
            str,
        ):
            raise SecCanonicalError("CANONICAL_CACHE_PAYLOAD_INVALID")

        return FundamentalObservation(
            metric_id=_required_text(raw, "metric_id"),
            fiscal_slot=FiscalSlot(_required_text(raw, "fiscal_slot")),
            value=float(value_raw),
            period_start=(
                date.fromisoformat(period_start_raw) if period_start_raw is not None else None
            ),
            period_end=date.fromisoformat(_required_text(raw, "period_end")),
            period_kind=PeriodKind(_required_text(raw, "period_kind")),
            unit_kind=UnitKind(_required_text(raw, "unit_kind")),
            source_provider=_required_text(raw, "source_provider"),
            source_identity=source_identity_raw,
            share_class_id=share_class_raw,
            adjustment_basis_id=adjustment_basis_raw,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SecCanonicalError("CANONICAL_CACHE_PAYLOAD_INVALID") from exc


def _decode_snapshot(payload: Mapping[str, object]) -> CanonicalIssuerSnapshot:
    observations_raw = payload.get("observations")
    history_years_raw = payload.get("history_years")
    fiscal_year_end_raw = payload.get("fiscal_year_end")

    if not isinstance(observations_raw, list):
        raise SecCanonicalError("CANONICAL_CACHE_PAYLOAD_INVALID")

    if (
        isinstance(history_years_raw, bool)
        or not isinstance(history_years_raw, int)
        or history_years_raw < 1
    ):
        raise SecCanonicalError("CANONICAL_CACHE_PAYLOAD_INVALID")

    if fiscal_year_end_raw is not None and not isinstance(fiscal_year_end_raw, str):
        raise SecCanonicalError("CANONICAL_CACHE_PAYLOAD_INVALID")

    try:
        return CanonicalIssuerSnapshot(
            schema_version=_required_text(payload, "schema_version"),
            canonicalizer_version=_required_text(
                payload,
                "canonicalizer_version",
            ),
            issuer_id=_required_text(payload, "issuer_id"),
            cik=_required_text(payload, "cik"),
            as_of=date.fromisoformat(_required_text(payload, "as_of")),
            history_years=history_years_raw,
            evidence_revision_sha256=_required_text(
                payload,
                "evidence_revision_sha256",
            ),
            fundamental_period_type=FundamentalPeriodType(
                _required_text(payload, "fundamental_period_type")
            ),
            fundamental_period_end=date.fromisoformat(
                _required_text(payload, "fundamental_period_end")
            ),
            fiscal_year_end=fiscal_year_end_raw,
            observations=tuple(_decode_observation(raw) for raw in observations_raw),
        )
    except (TypeError, ValueError) as exc:
        raise SecCanonicalError("CANONICAL_CACHE_PAYLOAD_INVALID") from exc


class CanonicalIssuerCache:
    PROVIDER = "sec-canonical-issuer"

    def __init__(self, cache: DiamondCache) -> None:
        self._cache = cache
        self.cache_hits = 0
        self.cache_misses = 0

    @staticmethod
    def _identity(
        *,
        schema_version: str,
        canonicalizer_version: str,
        issuer_id: str,
        as_of: date,
        history_years: int,
        evidence_revision_sha256: str,
    ) -> str:
        digest = sha256_canonical_json(
            _identity_payload(
                schema_version=schema_version,
                canonicalizer_version=canonicalizer_version,
                issuer_id=issuer_id,
                as_of=as_of,
                history_years=history_years,
                evidence_revision_sha256=evidence_revision_sha256,
            )
        )
        return f"sec-canonical:{digest}"

    @classmethod
    def request_identity(
        cls,
        *,
        issuer_id: str,
        as_of: date,
        history_years: int,
        evidence_revision_sha256: str,
    ) -> str:
        return cls._identity(
            schema_version=CANONICAL_SCHEMA_VERSION,
            canonicalizer_version=SEC_CANONICALIZER_VERSION,
            issuer_id=issuer_id,
            as_of=as_of,
            history_years=history_years,
            evidence_revision_sha256=evidence_revision_sha256,
        )

    def store(
        self,
        snapshot: CanonicalIssuerSnapshot,
    ) -> CanonicalIssuerSnapshot:
        if snapshot.schema_version != CANONICAL_SCHEMA_VERSION:
            raise SecCanonicalError("CANONICAL_CACHE_SCHEMA_MISMATCH")

        identity = self._identity(
            schema_version=snapshot.schema_version,
            canonicalizer_version=snapshot.canonicalizer_version,
            issuer_id=snapshot.issuer_id,
            as_of=snapshot.as_of,
            history_years=snapshot.history_years,
            evidence_revision_sha256=snapshot.evidence_revision_sha256,
        )

        try:
            self._cache.store(
                identity,
                provider=self.PROVIDER,
                data_as_of=snapshot.as_of,
                payload=_snapshot_payload(snapshot),
            )
        except DiamondCacheError as exc:
            raise SecCanonicalError("CANONICAL_CACHE_WRITE_FAILED") from exc

        return snapshot

    def load(
        self,
        *,
        issuer_id: str,
        as_of: date,
        history_years: int,
        evidence_revision_sha256: str,
    ) -> CanonicalIssuerSnapshot | None:
        identity = self.request_identity(
            issuer_id=issuer_id,
            as_of=as_of,
            history_years=history_years,
            evidence_revision_sha256=evidence_revision_sha256,
        )

        try:
            cached = self._cache.load(identity)
        except DiamondCacheError as exc:
            raise SecCanonicalError("CANONICAL_CACHE_INVALID") from exc

        if cached is None:
            self.cache_misses += 1
            return None

        if cached.provider != self.PROVIDER:
            raise SecCanonicalError("CANONICAL_CACHE_PROVIDER_MISMATCH")
        if cached.data_as_of != as_of:
            raise SecCanonicalError("CANONICAL_CACHE_AS_OF_MISMATCH")
        if not isinstance(cached.payload, Mapping):
            raise SecCanonicalError("CANONICAL_CACHE_PAYLOAD_INVALID")

        payload = cached.payload

        if payload.get("schema_version") != CANONICAL_SCHEMA_VERSION:
            raise SecCanonicalError("CANONICAL_CACHE_SCHEMA_MISMATCH")
        if payload.get("canonicalizer_version") != SEC_CANONICALIZER_VERSION:
            raise SecCanonicalError("CANONICAL_CACHE_CANONICALIZER_MISMATCH")
        if payload.get("issuer_id") != issuer_id:
            raise SecCanonicalError("CANONICAL_CACHE_ISSUER_MISMATCH")
        if payload.get("as_of") != as_of.isoformat():
            raise SecCanonicalError("CANONICAL_CACHE_AS_OF_MISMATCH")
        if payload.get("history_years") != history_years:
            raise SecCanonicalError("CANONICAL_CACHE_HISTORY_MISMATCH")
        if payload.get("evidence_revision_sha256") != evidence_revision_sha256:
            raise SecCanonicalError("CANONICAL_CACHE_REVISION_MISMATCH")

        snapshot = _decode_snapshot(payload)

        self.cache_hits += 1
        return snapshot
