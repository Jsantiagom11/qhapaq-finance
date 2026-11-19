from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

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
from qhapaq_finance.sec_client import SecResponse
from qhapaq_finance.sec_evidence_provider import StructuredSecProvider

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


def test_planner_accepts_a_validated_local_sec_corpus_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = CompanyIdentity("ACME", "acme:ACME", "acme", "Acme", None, None, "0000000123", None)

    class Corpus:
        def evidence(self, company: CompanyIdentity) -> object:
            assert company == identity
            return object()

    monkeypatch.setattr("qhapaq_finance.local_sec_corpus.LocalSecCorpus", lambda root: Corpus())
    plan = EvidencePlanner(tmp_path).plan(identity)

    assert plan.critical_ready
    assert {item.requirement.artifact_kind for item in plan.items} == {
        "SEC_COMPANY_FACTS",
        "SEC_SUBMISSIONS",
        "SEC_LATEST_10K_METADATA",
        "SEC_LATEST_10Q_METADATA",
    }
    assert {item.state for item in plan.items} == {EvidenceState.VERIFIED}


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


class RecordingSecClient:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def get(self, url: str) -> SecResponse:
        self.urls.append(url)
        if "/submissions/" in url:
            payload = {
                "cik": 123,
                "tickers": ["ACME"],
                "filings": {
                    "recent": {
                        "accessionNumber": [
                            "0000000123-26-000003",
                            "0000000123-26-000002",
                            "0000000123-25-000001",
                        ],
                        "form": ["10-Q", "10-K/A", "10-K"],
                        "filingDate": ["2026-07-30", "2026-03-01", "2026-02-01"],
                        "reportDate": ["2026-06-30", "2025-12-31", "2025-12-31"],
                        "primaryDocument": ["q2.htm", "annual-amendment.htm", "annual.htm"],
                    }
                },
            }
        else:
            payload = {"cik": 123, "entityName": "Acme", "facts": {}}
        return SecResponse(200, {"Content-Type": "application/json"}, json.dumps(payload).encode())


def test_structured_sec_fast_path_fetches_each_entity_once(tmp_path: Path) -> None:
    client = RecordingSecClient()

    bundle = StructuredSecProvider(client, tmp_path / "staging").acquire_fast_path(IDENTITY)

    assert client.urls == [
        "https://data.sec.gov/submissions/CIK0000000123.json",
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000123.json",
    ]
    assert bundle.companyfacts["entityName"] == "Acme"
    assert bundle.submissions.staged.raw_path.is_file()
    assert bundle.companyfacts_staged.raw_path.is_file()


def test_structured_sec_fast_path_bundle_prevents_payload_mutation(tmp_path: Path) -> None:
    bundle = StructuredSecProvider(RecordingSecClient(), tmp_path / "staging").acquire_fast_path(
        IDENTITY
    )

    filings = bundle.submissions.payload["filings"]
    assert isinstance(filings, Mapping)
    recent = filings["recent"]
    assert isinstance(recent, Mapping)
    accession_numbers = recent["accessionNumber"]
    assert isinstance(accession_numbers, tuple)
    with pytest.raises(TypeError):
        accession_numbers[0] = "0000000123-00-000000"  # type: ignore[index]


def test_filing_discovery_reuses_prefetched_submissions_without_http(tmp_path: Path) -> None:
    client = RecordingSecClient()
    provider = StructuredSecProvider(client, tmp_path / "staging")
    bundle = provider.acquire_fast_path(IDENTITY)
    calls_after_fast_path = tuple(client.urls)

    annual = provider.original_filing(bundle.submissions, "10-K")
    quarter = provider.original_filing(bundle.submissions, "10-Q")

    assert tuple(client.urls) == calls_after_fast_path
    assert annual.accession == "0000000123-25-000001"
    assert annual.primary_document == "annual.htm"
    assert quarter.accession == "0000000123-26-000003"
