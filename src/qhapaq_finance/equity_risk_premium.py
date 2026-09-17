"""Canonical U.S. implied ERP evidence from checksum-bound NYU Stern artifacts."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.request import urlopen

from .capital_cost import RateEvidence
from .evidence_quality import content_identity

STERN_IMPLIED_ERP_URL = "https://pages.stern.nyu.edu/~adamodar/pc/implprem/ERPbymonth.xls"


class EquityRiskPremiumError(ValueError):
    pass


@dataclass(frozen=True)
class EquityRiskPremiumMethodology:
    version: str = "equity_risk_premium_methodology_v1"
    market: str = "United States"
    series: str = "S&P 500 implied ERP"
    max_age_days: int = 62


ERP_METHODOLOGY_V1 = EquityRiskPremiumMethodology()


@dataclass(frozen=True)
class SternErpObservation:
    observed_at: date
    market: str
    series: str
    published_value: float
    published_unit: str
    retrieved_at: datetime | None

    def __post_init__(self) -> None:
        if self.market != "United States" or self.series != "S&P 500 implied ERP":
            raise EquityRiskPremiumError("ERP_SOURCE_INVALID")
        if self.published_unit != "percent":
            raise EquityRiskPremiumError("ERP_UNIT_INVALID")
        if not math.isfinite(self.published_value) or self.published_value < 0:
            raise EquityRiskPremiumError("ERP_VALUE_INVALID")


@dataclass(frozen=True)
class CachedSternErpObservations:
    observations: tuple[SternErpObservation, ...]
    source_manifest_identity: str
    source_checksum: str

    def __post_init__(self) -> None:
        if not self.observations or len({item.observed_at for item in self.observations}) != len(
            self.observations
        ):
            raise EquityRiskPremiumError("ERP_OBSERVATIONS_INVALID")


@dataclass(frozen=True)
class EquityRiskPremiumEvidence:
    identity: str
    methodology_version: str
    market: str
    series: str
    observed_at: date
    evaluation_as_of: date
    published_value: float
    published_unit: str
    value: float
    source_artifact_identity: str
    source_checksum: str
    retrieved_at: datetime | None

    def as_capital_cost_evidence(self) -> RateEvidence:
        return RateEvidence(
            self.identity,
            "equity_risk_premium",
            self.value,
            "decimal_rate",
            self.observed_at,
            self.source_artifact_identity,
            "nyu_stern_damodaran",
            self.identity,
            self.methodology_version,
        )


def cache_stern_erp_observations(
    *, root: str | Path, observations: tuple[SternErpObservation, ...]
) -> Path:
    root_path = Path(root)
    directory = root_path / "data/cache/erp/nyu-stern"
    directory.mkdir(parents=True, exist_ok=True)
    raw = directory / "stern-erp-observations.json"
    raw.write_text(
        json.dumps(
            {
                "schema_version": "stern-implied-erp-v1",
                "provider": "NYU Stern / Aswath Damodaran",
                "observations": [
                    {
                        "observed_at": x.observed_at.isoformat(),
                        "market": x.market,
                        "series": x.series,
                        "published_value": x.published_value,
                        "published_unit": x.published_unit,
                        "retrieved_at": x.retrieved_at.isoformat() if x.retrieved_at else None,
                    }
                    for x in observations
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    manifest = directory / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "stern-erp-manifest-v1",
                "provider": "NYU Stern / Aswath Damodaran",
                "source_url": STERN_IMPLIED_ERP_URL,
                "raw_artifact": raw.relative_to(root_path).as_posix(),
                "raw_artifact_sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return manifest


def load_cached_stern_erp_observations(
    *, root: str | Path, manifest_path: str | Path
) -> CachedSternErpObservations:
    try:
        root_path = Path(root)
        manifest = json.loads(Path(manifest_path).read_text())
        relative = Path(manifest["raw_artifact"])
        raw = root_path / relative
        checksum = hashlib.sha256(raw.read_bytes()).hexdigest()
        payload = json.loads(raw.read_text())
        if (
            manifest.get("schema_version") != "stern-erp-manifest-v1"
            or manifest.get("provider") != "NYU Stern / Aswath Damodaran"
            or relative.is_absolute()
            or ".." in relative.parts
            or manifest.get("raw_artifact_sha256") != checksum
            or payload.get("schema_version") != "stern-implied-erp-v1"
        ):
            raise ValueError
        observations = tuple(
            SternErpObservation(
                date.fromisoformat(x["observed_at"]),
                x["market"],
                x["series"],
                float(x["published_value"]),
                x["published_unit"],
                datetime.fromisoformat(x["retrieved_at"]) if x["retrieved_at"] else None,
            )
            for x in payload["observations"]
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise EquityRiskPremiumError("ERP_SOURCE_INVALID") from exc
    return CachedSternErpObservations(observations, content_identity(manifest), checksum)


def canonical_equity_risk_premium(
    *,
    cache: CachedSternErpObservations,
    evaluation_as_of: date,
    methodology: EquityRiskPremiumMethodology = ERP_METHODOLOGY_V1,
) -> EquityRiskPremiumEvidence:
    candidates = tuple(x for x in cache.observations if x.observed_at <= evaluation_as_of)
    if not candidates:
        raise EquityRiskPremiumError("ERP_OBSERVATION_UNAVAILABLE")
    selected = max(candidates, key=lambda x: x.observed_at)
    if (evaluation_as_of - selected.observed_at).days > methodology.max_age_days:
        raise EquityRiskPremiumError("ERP_STALE")
    value = selected.published_value / 100
    identity = content_identity(
        {
            "methodology": methodology.version,
            "as_of": evaluation_as_of.isoformat(),
            "observation": selected.observed_at.isoformat(),
            "value": selected.published_value,
            "source": cache.source_manifest_identity,
            "checksum": cache.source_checksum,
        }
    )
    return EquityRiskPremiumEvidence(
        identity,
        methodology.version,
        selected.market,
        selected.series,
        selected.observed_at,
        evaluation_as_of,
        selected.published_value,
        selected.published_unit,
        value,
        cache.source_manifest_identity,
        cache.source_checksum,
        selected.retrieved_at,
    )


def fetch_stern_implied_erp_artifact() -> bytes:
    with urlopen(STERN_IMPLIED_ERP_URL, timeout=30) as response:
        return response.read()  # nosec B310
