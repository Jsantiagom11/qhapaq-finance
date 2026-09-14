from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from qhapaq_finance.analysis import CompanyIdentity
from qhapaq_finance.evidence_orchestration import (
    AcquisitionCoordinator,
    EvidenceInventory,
    EvidenceItem,
    EvidencePlan,
    EvidencePlanner,
    EvidenceRequirement,
    EvidenceState,
    FreshnessPolicy,
)
from qhapaq_finance.sec_acquisition import StagedSecResource

IDENTITY = CompanyIdentity("ACME", None, None, "Acme", None, None, "0000000123", None)


def _requirement(identifier: str = "facts") -> EvidenceRequirement:
    return EvidenceRequirement(
        identifier,
        "FAKE",
        "COMPANY_FACTS",
        IDENTITY,
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000123.json",
        (),
        (),
        FreshnessPolicy(7),
        True,
    )


def _stage(
    root: Path, requirement: EvidenceRequirement, fetched_at: datetime, content: bytes = b"ok"
) -> None:
    directory = root / "data/raw/sec"
    directory.mkdir(parents=True, exist_ok=True)
    checksum = hashlib.sha256(content).hexdigest()
    (directory / f"{checksum}.bin").write_bytes(content)
    (directory / f"{checksum}.json").write_text(
        json.dumps(
            {
                "source_url": requirement.source_url,
                "sha256": checksum,
                "fetched_at": fetched_at.isoformat().replace("+00:00", "Z"),
            }
        ),
        encoding="utf-8",
    )


def test_inventory_reports_missing_stale_staged_and_invalid_without_network(tmp_path: Path) -> None:
    requirement = _requirement()
    inventory = EvidenceInventory(tmp_path)
    now = datetime(2026, 9, 11, tzinfo=timezone.utc)
    assert inventory.inspect(requirement, now=now).state is EvidenceState.MISSING
    _stage(tmp_path, requirement, now - timedelta(days=8))
    assert inventory.inspect(requirement, now=now).state is EvidenceState.STALE
    for path in (tmp_path / "data/raw/sec").iterdir():
        path.unlink()
    _stage(tmp_path, requirement, now)
    assert inventory.inspect(requirement, now=now).state is EvidenceState.STAGED
    metadata = next((tmp_path / "data/raw/sec").glob("*.json"))
    metadata.write_text(json.dumps({"source_url": requirement.source_url}), encoding="utf-8")
    assert inventory.inspect(requirement, now=now).state is EvidenceState.INVALID


def test_trusted_requirement_is_available_without_promoting_staged_bytes(tmp_path: Path) -> None:
    trusted = tmp_path / "data/research/acme/financial-evidence.json"
    trusted.parent.mkdir(parents=True)
    trusted.write_text("{}", encoding="utf-8")
    planner = EvidencePlanner(tmp_path)
    plan = planner.plan(IDENTITY, trusted_path="data/research/acme/financial-evidence.json")
    assert plan.items[0].state is EvidenceState.AVAILABLE
    assert plan.critical_ready


class FakeProvider:
    name = "FAKE"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[str] = []

    def acquire(self, requirement: EvidenceRequirement) -> StagedSecResource:
        self.calls.append(requirement.identifier)
        if self.fail:
            raise ValueError("malformed response")
        return StagedSecResource(Path("data/raw/sec/staged.bin"), Path("staged.json"), "abc", 3)


def test_coordinator_handles_partial_and_provider_failures_without_promotion() -> None:
    missing = EvidenceItem(_requirement("one"), EvidenceState.MISSING, "absent", None)
    stale = EvidenceItem(_requirement("two"), EvidenceState.STALE, "old", None)
    provider = FakeProvider()
    plan = AcquisitionCoordinator({"FAKE": provider}).acquire(EvidencePlan("v1", (missing, stale)))
    assert [item.state for item in plan.items] == [EvidenceState.STAGED, EvidenceState.STAGED]
    assert provider.calls == ["one", "two"]
    failed = AcquisitionCoordinator({"FAKE": FakeProvider(fail=True)}).acquire(
        EvidencePlan("v1", (missing,))
    )
    assert failed.items[0].state is EvidenceState.BLOCKED
    assert failed.items[0].artifact_path is None
