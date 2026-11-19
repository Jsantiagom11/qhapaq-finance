"""Dataset-level eligibility and temporal invariants for Diamond Funnel."""

from __future__ import annotations

from .contracts import FundamentalPeriodType, FundamentalRecord, Methodology


class DiamondValidationError(ValueError):
    """Raised when a screen request cannot be evaluated coherently."""


MAX_FUNDAMENTAL_AGE_DAYS = 130


def validate_record(record: FundamentalRecord) -> tuple[str, ...]:
    diagnostics: list[str] = []
    if record.methodology is not Methodology.OPERATING_COMPANY:
        diagnostics.append("UNSUPPORTED_METHODOLOGY")
    if record.fundamental_period_type is not FundamentalPeriodType.TTM:
        diagnostics.append("UNSUPPORTED_PERIOD_TYPE")
    age = (record.data_as_of - record.fundamental_period_end).days
    if age < 0 or age > MAX_FUNDAMENTAL_AGE_DAYS:
        diagnostics.append("FUNDAMENTALS_STALE")
    return tuple(diagnostics)


def record_eligible_for_scoring(record: FundamentalRecord) -> bool:
    return not validate_record(record)


def validate_dataset(records: tuple[FundamentalRecord, ...]) -> tuple[str, ...]:
    if not records:
        raise DiamondValidationError("EMPTY_DATASET")
    as_of = records[0].data_as_of
    if any(record.data_as_of != as_of for record in records[1:]):
        raise DiamondValidationError("DATA_AS_OF_MISMATCH")
    tickers = [record.ticker for record in records]
    if len(tickers) != len(set(tickers)):
        raise DiamondValidationError("DUPLICATE_TICKER")
    securities = [record.security_id for record in records]
    if len(securities) != len(set(securities)):
        raise DiamondValidationError("DUPLICATE_SECURITY_ID")
    diagnostics: set[str] = set()
    for record in records:
        diagnostics.update(validate_record(record))
    return tuple(sorted(diagnostics))
