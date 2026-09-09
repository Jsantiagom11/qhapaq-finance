"""Offline, period-aware filing evidence for valuation research cases.

This module deliberately contains no acquisition code.  Acquisition may refresh the
JSON snapshot, but valuation only consumes its checked-in, checksum-bound facts.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path


class EvidenceError(ValueError):
    """Raised when a frozen evidence snapshot is internally inconsistent."""


class EvidenceKind(str, Enum):
    FACT = "FACT"
    DERIVED = "DERIVED"
    ASSUMPTION = "ASSUMPTION"


class PeriodKind(str, Enum):
    DURATION = "DURATION"
    INSTANT = "INSTANT"


@dataclass(frozen=True)
class FilingRef:
    accession_number: str
    filing_type: str
    filing_date: date
    local_path: Path
    sha256: str


@dataclass(frozen=True)
class FinancialFact:
    id: str
    concept: str
    value: float
    unit: str
    kind: EvidenceKind
    period_kind: PeriodKind
    period_start: date | None
    period_end: date
    fiscal_year: int
    fiscal_period: str
    filing: FilingRef
    locator: str
    method: str

    def __post_init__(self) -> None:
        if self.kind is not EvidenceKind.FACT:
            raise EvidenceError("FinancialFact must be classified FACT")
        if self.period_kind is PeriodKind.DURATION and self.period_start is None:
            raise EvidenceError("duration facts require period_start")
        if self.period_kind is PeriodKind.INSTANT and self.period_start is not None:
            raise EvidenceError("instant facts cannot have period_start")


@dataclass(frozen=True)
class DerivedFact:
    id: str
    concept: str
    value: float
    unit: str
    inputs: tuple[str, ...]
    formula: str
    period_end: date
    kind: EvidenceKind = EvidenceKind.DERIVED


def reconstruct_ttm(
    *, annual: FinancialFact, prior_ytd: FinancialFact, current_ytd: FinancialFact, identifier: str
) -> DerivedFact:
    """Construct TTM = FY - comparable prior YTD + current YTD.

    This rejects the common error of adding overlapping YTD durations or mixing a
    balance-sheet instant into a duration calculation.
    """
    items = (annual, prior_ytd, current_ytd)
    if any(item.period_kind is not PeriodKind.DURATION for item in items):
        raise EvidenceError("TTM reconstruction requires duration facts")
    if annual.fiscal_period != "FY" or prior_ytd.fiscal_period != current_ytd.fiscal_period:
        raise EvidenceError("TTM requires annual and comparable YTD periods")
    if any(item.period_start is None for item in items):
        raise EvidenceError("TTM duration facts require starts")
    assert prior_ytd.period_start is not None
    assert current_ytd.period_start is not None
    prior_days = prior_ytd.period_end - prior_ytd.period_start
    current_days = current_ytd.period_end - current_ytd.period_start
    if prior_days != current_days:
        raise EvidenceError("TTM YTD periods are not comparable")
    return DerivedFact(
        identifier,
        annual.concept,
        annual.value - prior_ytd.value + current_ytd.value,
        annual.unit,
        tuple(item.id for item in items),
        "FY - prior comparable YTD + current YTD",
        current_ytd.period_end,
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_facts(
    path: str | Path, repository_root: str | Path = ".", *, as_of: date
) -> dict[str, FinancialFact]:
    """Load local fact evidence and enforce artifact integrity and no-look-ahead."""
    root = Path(repository_root).resolve()
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != "0.2" or payload.get("as_of") != as_of.isoformat():
        raise EvidenceError("unsupported evidence snapshot or as-of date")
    filings: dict[str, FilingRef] = {}
    for raw in payload.get("filings", []):
        filing_date = date.fromisoformat(raw["filing_date"])
        if filing_date > as_of:
            raise EvidenceError("filing is after research as-of date")
        relative = Path(raw["local_path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise EvidenceError("unsafe filing path")
        local = root / relative
        if not local.is_file() or sha256(local) != raw["sha256"]:
            raise EvidenceError("filing checksum mismatch")
        filings[raw["id"]] = FilingRef(
            raw["accession_number"], raw["filing_type"], filing_date, local, raw["sha256"]
        )
    result: dict[str, FinancialFact] = {}
    for raw in payload.get("facts", []):
        if raw.get("classification") != "FACT":
            raise EvidenceError("sourced financial records must be FACT")
        filing = filings[raw["filing_id"]]
        period_kind = PeriodKind(raw["period_kind"])
        start = date.fromisoformat(raw["period_start"]) if raw.get("period_start") else None
        fact = FinancialFact(
            raw["id"],
            raw["concept"],
            float(raw["value"]),
            raw["unit"],
            EvidenceKind.FACT,
            period_kind,
            start,
            date.fromisoformat(raw["period_end"]),
            int(raw["fiscal_year"]),
            raw["fiscal_period"],
            filing,
            raw["locator"],
            raw["method"],
        )
        if fact.id in result:
            raise EvidenceError("duplicate fact id")
        result[fact.id] = fact
    return result
