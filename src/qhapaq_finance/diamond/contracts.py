"""Provider-neutral immutable contracts for the Diamond Funnel discovery layer."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from qhapaq_finance.string_enum import StringEnum


class DiamondContractError(ValueError):
    """Raised when canonical Diamond Funnel input violates its contract."""


class Methodology(StringEnum):
    OPERATING_COMPANY = "OPERATING_COMPANY"
    UNSUPPORTED_FINANCIAL = "UNSUPPORTED_FINANCIAL"
    UNSUPPORTED_INSURER = "UNSUPPORTED_INSURER"
    UNSUPPORTED_REIT = "UNSUPPORTED_REIT"
    UNKNOWN = "UNKNOWN"


class FundamentalPeriodType(StringEnum):
    TTM = "TTM"


class FiscalSlot(StringEnum):
    TTM = "TTM"
    FY1 = "FY1"
    FY2 = "FY2"
    FY3 = "FY3"
    FY4 = "FY4"
    FY5 = "FY5"
    LATEST = "LATEST"


class PeriodKind(StringEnum):
    DURATION = "duration"
    INSTANT = "instant"


class UnitKind(StringEnum):
    CURRENCY = "currency"
    SHARES = "shares"
    RATIO = "ratio"


def _text(value: str, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DiamondContractError(code)
    return value.strip()


def _optional_text(value: str | None, code: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise DiamondContractError(code)
    return value.strip()


def _finite_number(value: float, code: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DiamondContractError(code)
    number = float(value)
    if not math.isfinite(number):
        raise DiamondContractError(code)
    return number


@dataclass(frozen=True, slots=True)
class SecurityRef:
    ticker: str
    security_id: str
    issuer_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "ticker", _text(self.ticker, "TICKER_REQUIRED").upper())
        object.__setattr__(self, "security_id", _text(self.security_id, "SECURITY_ID_REQUIRED"))
        object.__setattr__(self, "issuer_id", _text(self.issuer_id, "ISSUER_ID_REQUIRED"))


@dataclass(frozen=True, slots=True)
class FundamentalObservation:
    metric_id: str
    fiscal_slot: FiscalSlot
    value: float
    period_start: date | None
    period_end: date
    period_kind: PeriodKind
    unit_kind: UnitKind
    source_provider: str
    source_identity: str | None = None
    share_class_id: str | None = None
    adjustment_basis_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "metric_id", _text(self.metric_id, "METRIC_ID_REQUIRED"))
        object.__setattr__(self, "value", _finite_number(self.value, "OBSERVATION_NOT_FINITE"))
        object.__setattr__(
            self,
            "source_provider",
            _text(self.source_provider, "SOURCE_PROVIDER_REQUIRED"),
        )
        object.__setattr__(
            self,
            "source_identity",
            _optional_text(self.source_identity, "SOURCE_IDENTITY_INVALID"),
        )
        object.__setattr__(
            self,
            "share_class_id",
            _optional_text(self.share_class_id, "SHARE_CLASS_ID_INVALID"),
        )
        object.__setattr__(
            self,
            "adjustment_basis_id",
            _optional_text(self.adjustment_basis_id, "ADJUSTMENT_BASIS_ID_INVALID"),
        )
        if self.period_start is not None and self.period_start > self.period_end:
            raise DiamondContractError("PERIOD_WINDOW_INVALID")
        if self.unit_kind is not UnitKind.SHARES and (
            self.share_class_id is not None or self.adjustment_basis_id is not None
        ):
            raise DiamondContractError("SHARE_METADATA_ON_NON_SHARE_OBSERVATION")


@dataclass(frozen=True, slots=True)
class FundamentalRecord:
    ticker: str
    security_id: str
    issuer_id: str
    company_name: str
    currency: str
    peer_group_id: str
    sector: str | None
    industry_group: str | None
    methodology: Methodology
    fiscal_year_end: str | None
    data_as_of: date
    fundamental_period_type: FundamentalPeriodType
    fundamental_period_end: date
    market_age_trading_days: int | None
    provider: str
    provider_identity: str | None
    observations: tuple[FundamentalObservation, ...]
    evidence_diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "ticker", _text(self.ticker, "TICKER_REQUIRED").upper())
        object.__setattr__(self, "security_id", _text(self.security_id, "SECURITY_ID_REQUIRED"))
        object.__setattr__(self, "issuer_id", _text(self.issuer_id, "ISSUER_ID_REQUIRED"))
        object.__setattr__(self, "company_name", _text(self.company_name, "COMPANY_NAME_REQUIRED"))
        object.__setattr__(self, "currency", _text(self.currency, "CURRENCY_REQUIRED").upper())
        object.__setattr__(
            self, "peer_group_id", _text(self.peer_group_id, "PEER_GROUP_ID_REQUIRED")
        )
        object.__setattr__(self, "sector", _optional_text(self.sector, "SECTOR_INVALID"))
        object.__setattr__(
            self,
            "industry_group",
            _optional_text(self.industry_group, "INDUSTRY_GROUP_INVALID"),
        )
        object.__setattr__(
            self,
            "fiscal_year_end",
            _optional_text(self.fiscal_year_end, "FISCAL_YEAR_END_INVALID"),
        )
        object.__setattr__(self, "provider", _text(self.provider, "PROVIDER_REQUIRED"))
        object.__setattr__(
            self,
            "provider_identity",
            _optional_text(self.provider_identity, "PROVIDER_IDENTITY_INVALID"),
        )
        object.__setattr__(
            self,
            "evidence_diagnostics",
            tuple(_text(item, "EVIDENCE_DIAGNOSTIC_INVALID") for item in self.evidence_diagnostics),
        )
        if self.fundamental_period_end > self.data_as_of:
            raise DiamondContractError("FUNDAMENTAL_PERIOD_AFTER_DATA_AS_OF")
        if self.market_age_trading_days is not None:
            if (
                isinstance(self.market_age_trading_days, bool)
                or not isinstance(self.market_age_trading_days, int)
                or self.market_age_trading_days < 0
            ):
                raise DiamondContractError("MARKET_AGE_TRADING_DAYS_INVALID")
        seen: set[tuple[str, FiscalSlot]] = set()
        for observation in self.observations:
            key = (observation.metric_id, observation.fiscal_slot)
            if key in seen:
                raise DiamondContractError("DUPLICATE_METRIC_SLOT")
            seen.add(key)
