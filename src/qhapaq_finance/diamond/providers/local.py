"""Strict offline JSON adapter for canonical Diamond Funnel fixtures."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from ..contracts import (
    FiscalSlot,
    FundamentalObservation,
    FundamentalPeriodType,
    FundamentalRecord,
    Methodology,
    PeriodKind,
    SecurityRef,
    UnitKind,
)


class LocalProviderError(ValueError):
    """Raised when local canonical provider input is malformed or incoherent."""


def _date(value: object, field: str) -> date:
    if not isinstance(value, str):
        raise LocalProviderError(f"{field}: ISO_DATE_REQUIRED")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise LocalProviderError(f"{field}: ISO_DATE_INVALID") from exc
    if parsed.isoformat() != value:
        raise LocalProviderError(f"{field}: ISO_DATE_INVALID")
    return parsed


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LocalProviderError(f"{field}: TEXT_REQUIRED")
    return value.strip()


def _optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _text(value, field)


def _numeric(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LocalProviderError(f"{field}: NUMBER_REQUIRED")
    return float(value)


class LocalJsonProvider:
    """Load one fully canonical, provider-neutral offline dataset."""

    SCHEMA_VERSION = "diamond-fundamentals-v1"

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LocalProviderError("LOCAL_PROVIDER_UNREADABLE") from exc
        if not isinstance(raw, dict):
            raise LocalProviderError("ROOT_OBJECT_REQUIRED")
        if raw.get("schema_version") != self.SCHEMA_VERSION:
            raise LocalProviderError("SCHEMA_VERSION_UNSUPPORTED")
        self.universe_id = _text(raw.get("universe_id"), "universe_id")
        self.data_as_of = _date(raw.get("data_as_of"), "data_as_of")
        records_raw = raw.get("records")
        if not isinstance(records_raw, list):
            raise LocalProviderError("records: ARRAY_REQUIRED")
        self._records = tuple(
            self._parse_record(item, index) for index, item in enumerate(records_raw)
        )
        tickers = [record.ticker for record in self._records]
        security_ids = [record.security_id for record in self._records]
        if len(tickers) != len(set(tickers)):
            raise LocalProviderError("DUPLICATE_TICKER")
        if len(security_ids) != len(set(security_ids)):
            raise LocalProviderError("DUPLICATE_SECURITY_ID")
        if any(record.data_as_of != self.data_as_of for record in self._records):
            raise LocalProviderError("DATA_AS_OF_MISMATCH")

    def _parse_record(self, raw: object, index: int) -> FundamentalRecord:
        if not isinstance(raw, dict):
            raise LocalProviderError(f"records[{index}]: OBJECT_REQUIRED")
        observations_raw = raw.get("observations")
        if not isinstance(observations_raw, list):
            raise LocalProviderError(f"records[{index}].observations: ARRAY_REQUIRED")
        observations = tuple(
            self._parse_observation(item, index, obs_index)
            for obs_index, item in enumerate(observations_raw)
        )
        try:
            return FundamentalRecord(
                ticker=_text(raw.get("ticker"), f"records[{index}].ticker"),
                security_id=_text(raw.get("security_id"), f"records[{index}].security_id"),
                issuer_id=_text(raw.get("issuer_id"), f"records[{index}].issuer_id"),
                company_name=_text(raw.get("company_name"), f"records[{index}].company_name"),
                currency=_text(raw.get("currency"), f"records[{index}].currency"),
                peer_group_id=_text(raw.get("peer_group_id"), f"records[{index}].peer_group_id"),
                sector=_optional_text(raw.get("sector"), f"records[{index}].sector"),
                industry_group=_optional_text(
                    raw.get("industry_group"), f"records[{index}].industry_group"
                ),
                methodology=Methodology(
                    _text(raw.get("methodology"), f"records[{index}].methodology")
                ),
                fiscal_year_end=_optional_text(
                    raw.get("fiscal_year_end"), f"records[{index}].fiscal_year_end"
                ),
                data_as_of=_date(raw.get("data_as_of"), f"records[{index}].data_as_of"),
                fundamental_period_type=FundamentalPeriodType(
                    _text(
                        raw.get("fundamental_period_type"),
                        f"records[{index}].fundamental_period_type",
                    )
                ),
                fundamental_period_end=_date(
                    raw.get("fundamental_period_end"),
                    f"records[{index}].fundamental_period_end",
                ),
                market_age_trading_days=self._optional_nonnegative_int(
                    raw.get("market_age_trading_days"),
                    f"records[{index}].market_age_trading_days",
                ),
                provider=_text(raw.get("provider"), f"records[{index}].provider"),
                provider_identity=_optional_text(
                    raw.get("provider_identity"), f"records[{index}].provider_identity"
                ),
                observations=observations,
            )
        except (ValueError, TypeError) as exc:
            if isinstance(exc, LocalProviderError):
                raise
            raise LocalProviderError(f"records[{index}]: CONTRACT_INVALID: {exc}") from exc

    @staticmethod
    def _optional_nonnegative_int(value: object, field: str) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise LocalProviderError(f"{field}: NONNEGATIVE_INTEGER_REQUIRED")
        return value

    def _parse_observation(
        self, raw: object, record_index: int, observation_index: int
    ) -> FundamentalObservation:
        prefix = f"records[{record_index}].observations[{observation_index}]"
        if not isinstance(raw, dict):
            raise LocalProviderError(f"{prefix}: OBJECT_REQUIRED")
        period_start_raw = raw.get("period_start")
        period_start = (
            None if period_start_raw is None else _date(period_start_raw, f"{prefix}.period_start")
        )
        try:
            return FundamentalObservation(
                metric_id=_text(raw.get("metric_id"), f"{prefix}.metric_id"),
                fiscal_slot=FiscalSlot(_text(raw.get("fiscal_slot"), f"{prefix}.fiscal_slot")),
                value=_numeric(raw.get("value"), f"{prefix}.value"),
                period_start=period_start,
                period_end=_date(raw.get("period_end"), f"{prefix}.period_end"),
                period_kind=PeriodKind(_text(raw.get("period_kind"), f"{prefix}.period_kind")),
                unit_kind=UnitKind(_text(raw.get("unit_kind"), f"{prefix}.unit_kind")),
                source_provider=_text(raw.get("source_provider"), f"{prefix}.source_provider"),
                source_identity=_optional_text(
                    raw.get("source_identity"), f"{prefix}.source_identity"
                ),
                share_class_id=_optional_text(
                    raw.get("share_class_id"), f"{prefix}.share_class_id"
                ),
                adjustment_basis_id=_optional_text(
                    raw.get("adjustment_basis_id"), f"{prefix}.adjustment_basis_id"
                ),
            )
        except (ValueError, TypeError) as exc:
            if isinstance(exc, LocalProviderError):
                raise
            raise LocalProviderError(f"{prefix}: CONTRACT_INVALID: {exc}") from exc

    def records(self) -> tuple[FundamentalRecord, ...]:
        return self._records

    def universe(self, universe_id: str, as_of: date) -> tuple[SecurityRef, ...]:
        if universe_id != self.universe_id:
            raise LocalProviderError("UNIVERSE_ID_MISMATCH")
        if as_of != self.data_as_of:
            raise LocalProviderError("DATA_AS_OF_MISMATCH")
        return tuple(
            SecurityRef(item.ticker, item.security_id, item.issuer_id) for item in self._records
        )

    def fundamentals(
        self,
        securities: tuple[SecurityRef, ...],
        as_of: date,
        history_years: int = 5,
    ) -> tuple[FundamentalRecord, ...]:
        if as_of != self.data_as_of:
            raise LocalProviderError("DATA_AS_OF_MISMATCH")
        if (
            isinstance(history_years, bool)
            or not isinstance(history_years, int)
            or not 1 <= history_years <= 5
        ):
            raise LocalProviderError("HISTORY_YEARS_INVALID")
        by_security = {item.security_id: item for item in self._records}
        result: list[FundamentalRecord] = []
        for security in securities:
            record = by_security.get(security.security_id)
            if (
                record is None
                or record.ticker != security.ticker
                or record.issuer_id != security.issuer_id
            ):
                raise LocalProviderError("SECURITY_IDENTITY_MISMATCH")
            result.append(record)
        return tuple(result)
