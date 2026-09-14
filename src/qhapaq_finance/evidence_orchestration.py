"""Generic evidence planning, local inspection, and staging-only acquisition."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from .sec_acquisition import StagedSecResource, fetch_to_staging
from .sec_client import SecClient

if TYPE_CHECKING:
    from .analysis import CompanyIdentity


class EvidenceState(str, Enum):
    AVAILABLE = "AVAILABLE"
    MISSING = "MISSING"
    STALE = "STALE"
    STAGED = "STAGED"
    VERIFIED = "VERIFIED"
    INVALID = "INVALID"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class FreshnessPolicy:
    max_age_days: int | None = None


@dataclass(frozen=True)
class EvidenceRequirement:
    identifier: str
    provider: str
    artifact_kind: str
    company: CompanyIdentity
    source_url: str | None
    forms: tuple[str, ...]
    fiscal_periods: tuple[str, ...]
    freshness: FreshnessPolicy
    critical: bool
    trusted_path: Path | None = None


@dataclass(frozen=True)
class EvidenceItem:
    requirement: EvidenceRequirement
    state: EvidenceState
    reason: str | None
    artifact_path: Path | None


@dataclass(frozen=True)
class EvidencePlan:
    schema_version: str
    items: tuple[EvidenceItem, ...]

    @property
    def critical_ready(self) -> bool:
        return all(
            not item.requirement.critical
            or item.state in {EvidenceState.AVAILABLE, EvidenceState.VERIFIED}
            for item in self.items
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "critical_ready": self.critical_ready,
            "items": [
                {
                    "identifier": item.requirement.identifier,
                    "provider": item.requirement.provider,
                    "artifact_kind": item.requirement.artifact_kind,
                    "source_url": item.requirement.source_url,
                    "forms": list(item.requirement.forms),
                    "fiscal_periods": list(item.requirement.fiscal_periods),
                    "critical": item.requirement.critical,
                    "state": item.state.value,
                    "reason": item.reason,
                }
                for item in self.items
            ],
        }


class AcquisitionProvider(Protocol):
    name: str

    def acquire(self, requirement: EvidenceRequirement) -> StagedSecResource: ...


class SecProvider:
    """SEC-only provider that can write only through the staging primitive."""

    name = "SEC"

    def __init__(self, client: SecClient, staging_root: str | Path = "data/raw") -> None:
        self.client = client
        self.staging_root = Path(staging_root)

    def acquire(self, requirement: EvidenceRequirement) -> StagedSecResource:
        if requirement.source_url is None:
            raise ValueError("SEC requirement has no source URL")
        return fetch_to_staging(
            self.client,
            requirement.source_url,
            self.staging_root,
            source_metadata={
                "requirement_id": requirement.identifier,
                "cik": requirement.company.cik or "",
            },
        )


class EvidenceInventory:
    """Read local trusted/staged artifacts only; it never calls a provider."""

    def __init__(self, repository_root: str | Path = ".") -> None:
        self.root = Path(repository_root)

    def inspect(self, requirement: EvidenceRequirement, *, now: datetime) -> EvidenceItem:
        if requirement.trusted_path is not None:
            path = self.root / requirement.trusted_path
            return (
                EvidenceItem(requirement, EvidenceState.AVAILABLE, None, path)
                if path.is_file()
                else EvidenceItem(
                    requirement, EvidenceState.MISSING, "trusted artifact is absent", None
                )
            )
        for metadata_path in sorted((self.root / "data/raw/sec").glob("*.json")):
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                if metadata.get("source_url") != requirement.source_url:
                    continue
                raw_path = metadata_path.with_suffix(".bin")
                content = raw_path.read_bytes()
                if metadata.get("sha256") != hashlib.sha256(content).hexdigest():
                    return EvidenceItem(
                        requirement, EvidenceState.INVALID, "staged checksum mismatch", raw_path
                    )
                fetched = datetime.fromisoformat(str(metadata["fetched_at"]).replace("Z", "+00:00"))
                if (
                    requirement.freshness.max_age_days is not None
                    and (now - fetched).days > requirement.freshness.max_age_days
                ):
                    return EvidenceItem(
                        requirement, EvidenceState.STALE, "staged artifact is stale", raw_path
                    )
                return EvidenceItem(
                    requirement, EvidenceState.STAGED, "awaiting verification", raw_path
                )
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                return EvidenceItem(
                    requirement, EvidenceState.INVALID, "invalid staged metadata", None
                )
        return EvidenceItem(requirement, EvidenceState.MISSING, "no local artifact", None)


class EvidencePlanner:
    """Create generic requirements; it has no acquisition or valuation dependency."""

    def __init__(
        self, repository_root: str | Path = ".", *, inventory: EvidenceInventory | None = None
    ) -> None:
        self.root = Path(repository_root)
        self.inventory = inventory or EvidenceInventory(self.root)

    def plan(
        self,
        company: CompanyIdentity,
        *,
        trusted_path: str | Path | None = None,
        now: datetime | None = None,
    ) -> EvidencePlan:
        if trusted_path is not None:
            requirement = EvidenceRequirement(
                "canonical-financial-evidence",
                "LOCAL",
                "CANONICAL_FINANCIAL_EVIDENCE",
                company,
                None,
                (),
                (),
                FreshnessPolicy(),
                True,
                Path(trusted_path),
            )
        elif company.cik is None:
            requirement = EvidenceRequirement(
                "company-facts",
                "SEC",
                "SEC_COMPANY_FACTS",
                company,
                None,
                (),
                (),
                FreshnessPolicy(7),
                True,
            )
        else:
            requirements = (
                EvidenceRequirement(
                    "company-facts",
                    "SEC",
                    "SEC_COMPANY_FACTS",
                    company,
                    f"https://data.sec.gov/api/xbrl/companyfacts/CIK{company.cik}.json",
                    (),
                    (),
                    FreshnessPolicy(7),
                    True,
                ),
                EvidenceRequirement(
                    "submissions",
                    "SEC",
                    "SEC_SUBMISSIONS",
                    company,
                    f"https://data.sec.gov/submissions/CIK{company.cik}.json",
                    (),
                    (),
                    FreshnessPolicy(7),
                    True,
                ),
                EvidenceRequirement(
                    "latest-10k",
                    "SEC",
                    "SEC_LATEST_10K_METADATA",
                    company,
                    None,
                    ("10-K",),
                    (),
                    FreshnessPolicy(7),
                    True,
                ),
                EvidenceRequirement(
                    "latest-10q",
                    "SEC",
                    "SEC_LATEST_10Q_METADATA",
                    company,
                    None,
                    ("10-Q",),
                    (),
                    FreshnessPolicy(7),
                    True,
                ),
            )
            current = now or datetime.now(timezone.utc)
            return EvidencePlan(
                "evidence-plan-v1",
                tuple(self.inventory.inspect(item, now=current) for item in requirements),
            )
        item = self.inventory.inspect(requirement, now=now or datetime.now(timezone.utc))
        return EvidencePlan("evidence-plan-v1", (item,))


class AcquisitionCoordinator:
    """Acquire unresolved requirements to staging only; promotion is deliberately absent."""

    def __init__(self, providers: Mapping[str, AcquisitionProvider]) -> None:
        self.providers = dict(providers)

    def acquire(self, plan: EvidencePlan) -> EvidencePlan:
        items: list[EvidenceItem] = []
        for item in plan.items:
            if item.state not in {EvidenceState.MISSING, EvidenceState.STALE}:
                items.append(item)
                continue
            provider = self.providers.get(item.requirement.provider)
            if provider is None:
                items.append(
                    EvidenceItem(
                        item.requirement, EvidenceState.BLOCKED, "provider unavailable", None
                    )
                )
                continue
            try:
                staged = provider.acquire(item.requirement)
            except (OSError, ValueError, RuntimeError):
                items.append(
                    EvidenceItem(
                        item.requirement, EvidenceState.BLOCKED, "provider acquisition failed", None
                    )
                )
                continue
            items.append(
                EvidenceItem(
                    item.requirement, EvidenceState.STAGED, "awaiting verification", staged.raw_path
                )
            )
        return EvidencePlan(plan.schema_version, tuple(items))
