"""Versioned canonical identity for fully assembled Diamond datasets."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import date

from .canonical_json import canonical_json_bytes, normalize_decimal
from .contracts import FundamentalObservation, FundamentalRecord

DATASET_SCHEMA_VERSION = "diamond-fundamental-dataset-v2"
DATASET_CANONICALIZER_VERSION = "fundamental-record-canonicalizer-v1"


def _date_payload(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _observation_payload(
    observation: FundamentalObservation,
) -> dict[str, object]:
    return {
        "metric_id": observation.metric_id,
        "fiscal_slot": observation.fiscal_slot.value,
        "value": normalize_decimal(observation.value),
        "period_start": _date_payload(observation.period_start),
        "period_end": observation.period_end.isoformat(),
        "period_kind": observation.period_kind.value,
        "unit_kind": observation.unit_kind.value,
        "source_provider": observation.source_provider,
        "source_identity": observation.source_identity,
        "share_class_id": observation.share_class_id,
        "adjustment_basis_id": observation.adjustment_basis_id,
    }


def _observation_sort_key(
    observation: FundamentalObservation,
) -> tuple[str, ...]:
    return (
        observation.metric_id,
        observation.fiscal_slot.value,
        _date_payload(observation.period_start) or "",
        observation.period_end.isoformat(),
        observation.period_kind.value,
        observation.unit_kind.value,
        observation.source_provider,
        observation.source_identity or "",
        observation.share_class_id or "",
        observation.adjustment_basis_id or "",
        normalize_decimal(observation.value),
    )


def _record_payload(record: FundamentalRecord) -> dict[str, object]:
    observations = tuple(
        sorted(
            record.observations,
            key=_observation_sort_key,
        )
    )

    return {
        "ticker": record.ticker,
        "security_id": record.security_id,
        "issuer_id": record.issuer_id,
        "company_name": record.company_name,
        "currency": record.currency,
        "peer_group_id": record.peer_group_id,
        "sector": record.sector,
        "industry_group": record.industry_group,
        "methodology": record.methodology.value,
        "fiscal_year_end": record.fiscal_year_end,
        "data_as_of": record.data_as_of.isoformat(),
        "fundamental_period_type": record.fundamental_period_type.value,
        "fundamental_period_end": record.fundamental_period_end.isoformat(),
        "market_age_trading_days": (
            normalize_decimal(record.market_age_trading_days)
            if record.market_age_trading_days is not None
            else None
        ),
        "provider": record.provider,
        "provider_identity": record.provider_identity,
        "observations": [_observation_payload(observation) for observation in observations],
        "evidence_diagnostics": sorted(record.evidence_diagnostics),
    }


def fundamental_dataset_payload(
    records: Sequence[FundamentalRecord],
) -> dict[str, object]:
    ordered = sorted(
        records,
        key=lambda record: (
            record.ticker,
            record.security_id,
            record.issuer_id,
        ),
    )

    return {
        "schema_version": DATASET_SCHEMA_VERSION,
        "canonicalizer_version": DATASET_CANONICALIZER_VERSION,
        "records": [_record_payload(record) for record in ordered],
    }


def dataset_identity(
    records: Sequence[FundamentalRecord],
) -> str:
    payload = fundamental_dataset_payload(records)
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
