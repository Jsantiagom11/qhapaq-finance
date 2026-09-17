"""Canonical USD risk-free evidence from official Treasury daily par yields."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.request import urlopen

from .capital_cost import RateEvidence
from .evidence_quality import content_identity

TREASURY_DAILY_PAR_YIELD_URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv"


class RiskFreeEvidenceError(ValueError):
    """Official Treasury evidence is absent, invalid, or not reproducible."""


@dataclass(frozen=True)
class RiskFreeMethodology:
    version: str = "risk_free_methodology_v1"
    currency: str = "USD"
    source: str = "U.S. Treasury daily par yield curve"
    tenor: str = "10Y"
    published_unit: str = "percent"
    max_age_days: int = 7


RISK_FREE_METHODOLOGY_V1 = RiskFreeMethodology()


@dataclass(frozen=True)
class TreasuryObservation:
    observed_at: date
    tenor: str
    published_value: float
    published_unit: str
    retrieved_at: datetime | None

    def __post_init__(self) -> None:
        if self.tenor != "10Y":
            raise RiskFreeEvidenceError("RISK_FREE_TENOR_INVALID")
        if self.published_unit != "percent":
            raise RiskFreeEvidenceError("RISK_FREE_UNIT_INVALID")
        if not math.isfinite(self.published_value) or self.published_value < 0:
            raise RiskFreeEvidenceError("RISK_FREE_VALUE_INVALID")
        if self.retrieved_at and (
            self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None
        ):
            raise RiskFreeEvidenceError("RISK_FREE_RETRIEVAL_INVALID")


@dataclass(frozen=True)
class CachedTreasuryObservations:
    observations: tuple[TreasuryObservation, ...]
    source_manifest_identity: str
    source_checksum: str

    def __post_init__(self) -> None:
        if not self.source_manifest_identity or not self.source_checksum:
            raise RiskFreeEvidenceError("RISK_FREE_PROVENANCE_INCOMPLETE")
        dates = tuple(item.observed_at for item in self.observations)
        if not dates or len(set(dates)) != len(dates):
            raise RiskFreeEvidenceError("RISK_FREE_OBSERVATIONS_INVALID")


@dataclass(frozen=True)
class RiskFreeEvidence:
    identity: str
    methodology_version: str
    source_identity: str
    tenor: str
    observed_at: date
    evaluation_as_of: date
    published_value: float
    published_unit: str
    value: float
    source_checksum: str
    retrieved_at: datetime | None

    def as_capital_cost_evidence(self) -> RateEvidence:
        return RateEvidence(
            self.identity,
            "risk_free_rate",
            self.value,
            "decimal_rate",
            self.observed_at,
            self.source_identity,
            "official_u_s_treasury",
            self.identity,
            self.methodology_version,
            self.tenor,
        )


def cache_treasury_observations(
    *, root: str | Path, observations: tuple[TreasuryObservation, ...]
) -> Path:
    """Freeze official Treasury observations using the existing manifest/checksum pattern."""
    root_path = Path(root)
    directory = root_path / "data/cache/treasury/daily-par-yield"
    raw = directory / "treasury-observations.json"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text(
        json.dumps(
            {
                "schema_version": "treasury-daily-par-yield-v1",
                "provider": "U.S. Treasury",
                "observations": [
                    {
                        "observed_at": item.observed_at.isoformat(),
                        "tenor": item.tenor,
                        "published_value": item.published_value,
                        "published_unit": item.published_unit,
                        "retrieved_at": (
                            item.retrieved_at.isoformat() if item.retrieved_at else None
                        ),
                    }
                    for item in observations
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = directory / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "treasury-source-manifest-v1",
                "provider": "U.S. Treasury",
                "source_url": TREASURY_DAILY_PAR_YIELD_URL,
                "raw_artifact": raw.relative_to(root_path).as_posix(),
                "raw_artifact_sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest


def load_cached_treasury_observations(
    *, root: str | Path, manifest_path: str | Path
) -> CachedTreasuryObservations:
    """Load only checksum-verified official Treasury cache evidence."""
    try:
        root_path = Path(root)
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        relative = Path(manifest["raw_artifact"])
        raw = root_path / relative
        checksum = hashlib.sha256(raw.read_bytes()).hexdigest()
        payload = json.loads(raw.read_text(encoding="utf-8"))
        if (
            manifest.get("schema_version") != "treasury-source-manifest-v1"
            or manifest.get("provider") != "U.S. Treasury"
            or relative.is_absolute()
            or ".." in relative.parts
            or manifest.get("raw_artifact_sha256") != checksum
            or payload.get("schema_version") != "treasury-daily-par-yield-v1"
            or payload.get("provider") != "U.S. Treasury"
        ):
            raise ValueError
        observations = tuple(
            TreasuryObservation(
                date.fromisoformat(item["observed_at"]),
                item["tenor"],
                float(item["published_value"]),
                item["published_unit"],
                datetime.fromisoformat(item["retrieved_at"]) if item["retrieved_at"] else None,
            )
            for item in payload["observations"]
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RiskFreeEvidenceError("RISK_FREE_SOURCE_INVALID") from exc
    return CachedTreasuryObservations(observations, content_identity(manifest), checksum)


def canonical_risk_free_evidence(
    *,
    cache: CachedTreasuryObservations,
    evaluation_as_of: date,
    methodology: RiskFreeMethodology = RISK_FREE_METHODOLOGY_V1,
) -> RiskFreeEvidence:
    """Select the latest acceptable official observation, never future or interpolated."""
    candidates = tuple(item for item in cache.observations if item.observed_at <= evaluation_as_of)
    if not candidates:
        raise RiskFreeEvidenceError("RISK_FREE_OBSERVATION_UNAVAILABLE")
    selected = max(candidates, key=lambda item: item.observed_at)
    if selected.tenor != methodology.tenor:
        raise RiskFreeEvidenceError("RISK_FREE_TENOR_INVALID")
    if selected.published_unit != methodology.published_unit:
        raise RiskFreeEvidenceError("RISK_FREE_UNIT_INVALID")
    if (evaluation_as_of - selected.observed_at).days > methodology.max_age_days:
        raise RiskFreeEvidenceError("RISK_FREE_STALE")
    value = selected.published_value / 100
    if not math.isfinite(value) or value < 0:
        raise RiskFreeEvidenceError("RISK_FREE_VALUE_INVALID")
    identity = content_identity(
        {
            "methodology": methodology.version,
            "evaluation_as_of": evaluation_as_of.isoformat(),
            "observation": selected.observed_at.isoformat(),
            "published_value": selected.published_value,
            "source_manifest": cache.source_manifest_identity,
            "source_checksum": cache.source_checksum,
        }
    )
    return RiskFreeEvidence(
        identity,
        methodology.version,
        cache.source_manifest_identity,
        selected.tenor,
        selected.observed_at,
        evaluation_as_of,
        selected.published_value,
        selected.published_unit,
        value,
        cache.source_checksum,
        selected.retrieved_at,
    )


def parse_official_treasury_daily_par_yield(
    raw: bytes,
    *,
    retrieved_at: datetime | None,
) -> tuple[TreasuryObservation, ...]:
    """Parse official Treasury CSV into canonical 10Y observations."""
    try:
        reader = csv.DictReader(raw.decode("utf-8-sig").splitlines())
        return tuple(
            TreasuryObservation(
                datetime.strptime(row["Date"], "%m/%d/%Y").date(),
                "10Y",
                float(row["10 Yr"]),
                "percent",
                retrieved_at,
            )
            for row in reader
        )
    except (UnicodeDecodeError, KeyError, TypeError, ValueError, csv.Error) as exc:
        raise RiskFreeEvidenceError("RISK_FREE_SOURCE_INVALID") from exc


def fetch_official_treasury_daily_par_yield() -> bytes:
    """Bounded live acquisition entry point; parsing and promotion remain offline."""
    with urlopen(TREASURY_DAILY_PAR_YIELD_URL, timeout=30) as response:  # nosec B310
        return response.read()
