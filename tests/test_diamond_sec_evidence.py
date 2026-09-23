import json
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from qhapaq_finance.diamond.cache import DiamondCache
from qhapaq_finance.diamond.providers.sec_evidence import (
    SecEvidenceError,
    SecEvidenceStore,
    evidence_revision,
    filtered_companyfacts,
)
from qhapaq_finance.sec_client import SecResponse


def revenue_payload(
    *,
    amendment_filed: str,
    amendment_value: float,
    cik: int = 320193,
) -> dict[str, object]:
    return {
        "cik": cik,
        "entityName": "Apple Inc.",
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "label": "Revenue",
                    "units": {
                        "USD": [
                            {
                                "start": "2026-01-01",
                                "end": "2026-06-30",
                                "val": 100.0,
                                "accn": "0000320193-26-000001",
                                "fy": 2026,
                                "fp": "Q2",
                                "form": "10-Q",
                                "filed": "2026-08-01",
                            },
                            {
                                "start": "2026-01-01",
                                "end": "2026-06-30",
                                "val": amendment_value,
                                "accn": "0000320193-26-000002",
                                "fy": 2026,
                                "fp": "Q2",
                                "form": "10-Q/A",
                                "filed": amendment_filed,
                            },
                        ]
                    },
                }
            }
        },
    }


class FakeSecHttpClient:
    def __init__(self, responses: list[SecResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, str], frozenset[int]]] = []

    def get(
        self,
        url: str,
        *,
        request_headers: Mapping[str, str] | None = None,
        accepted_statuses: frozenset[int] = frozenset(),
    ) -> SecResponse:
        self.calls.append((url, dict(request_headers or {}), accepted_statuses))
        return self.responses.pop(0)


def test_in_scope_amendment_changes_semantic_revision() -> None:
    payload = revenue_payload(
        amendment_filed="2026-08-15",
        amendment_value=110.0,
    )
    all_facts = filtered_companyfacts(
        payload,
        source_identity="payload-a",
        as_of=date(2026, 9, 22),
    )
    original_only = tuple(item for item in all_facts if item.filing_form == "10-Q")

    assert {item.filing_form for item in all_facts} == {"10-Q", "10-Q/A"}
    assert evidence_revision(all_facts) != evidence_revision(original_only)


def test_amendment_after_as_of_is_not_historical_evidence() -> None:
    payload = revenue_payload(
        amendment_filed="2026-10-01",
        amendment_value=110.0,
    )
    facts = filtered_companyfacts(
        payload,
        source_identity="payload-a",
        as_of=date(2026, 9, 22),
    )

    assert [item.filing_form for item in facts] == ["10-Q"]


def test_fresh_manifest_performs_zero_sec_requests(tmp_path: Path) -> None:
    now = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
    payload = revenue_payload(amendment_filed="2026-08-15", amendment_value=110.0)

    client = FakeSecHttpClient([SecResponse(200, {"ETag": '"v1"'}, json.dumps(payload).encode())])
    store = SecEvidenceStore(
        root=tmp_path / "sec",
        client=client,
        legacy_cache=None,
        now=lambda: now,
    )
    first = store.resolve("0000320193", date(2026, 9, 22))

    replay = SecEvidenceStore(
        root=tmp_path / "sec",
        client=None,
        legacy_cache=None,
        now=lambda: now + timedelta(hours=1),
    )
    second = replay.resolve("0000320193", date(2026, 9, 22))

    assert first.manifest.evidence_revision_sha256 == second.manifest.evidence_revision_sha256
    assert second.facts is None
    assert replay.provider_requests == 0
    assert replay.cache_hits == 1
    assert replay.cache_misses == 0


def test_refresh_bypasses_ttl_and_refetches_unconditionally(tmp_path: Path) -> None:
    now = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
    original = revenue_payload(
        amendment_filed="2026-08-15",
        amendment_value=110.0,
    )
    amended = revenue_payload(
        amendment_filed="2026-08-20",
        amendment_value=111.0,
    )
    seed_client = FakeSecHttpClient(
        [SecResponse(200, {"ETag": '"v1"'}, json.dumps(original).encode())]
    )
    first = SecEvidenceStore(
        root=tmp_path / "sec",
        client=seed_client,
        legacy_cache=None,
        now=lambda: now,
    ).resolve("0000320193", date(2026, 9, 22))

    refresh_client = FakeSecHttpClient(
        [SecResponse(200, {"ETag": '"v2"'}, json.dumps(amended).encode())]
    )
    refreshed = SecEvidenceStore(
        root=tmp_path / "sec",
        client=refresh_client,
        legacy_cache=None,
        now=lambda: now + timedelta(hours=1),
    ).resolve("0000320193", date(2026, 9, 22), refresh=True)

    assert refresh_client.calls == [
        (
            "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
            {},
            frozenset(),
        )
    ]
    assert first.manifest.evidence_revision_sha256 != (refreshed.manifest.evidence_revision_sha256)
    assert refreshed.facts is not None


def test_stale_manifest_with_etag_304_preserves_revision(tmp_path: Path) -> None:
    base = datetime(2026, 9, 22, 0, tzinfo=timezone.utc)
    payload = revenue_payload(amendment_filed="2026-08-15", amendment_value=110.0)

    seed_client = FakeSecHttpClient(
        [SecResponse(200, {"ETag": '"v1"'}, json.dumps(payload).encode())]
    )
    SecEvidenceStore(
        root=tmp_path / "sec",
        client=seed_client,
        legacy_cache=None,
        now=lambda: base,
    ).resolve("0000320193", date(2026, 9, 22))

    revalidate = FakeSecHttpClient([SecResponse(304, {"ETag": '"v1"'}, b"")])
    store = SecEvidenceStore(
        root=tmp_path / "sec",
        client=revalidate,
        legacy_cache=None,
        now=lambda: base + timedelta(hours=7),
    )
    resolved = store.resolve("0000320193", date(2026, 9, 22))

    assert revalidate.calls[0][1] == {"If-None-Match": '"v1"'}
    assert revalidate.calls[0][2] == frozenset({304})
    assert resolved.facts is None
    assert store.provider_requests == 1


def test_stale_manifest_uses_last_modified_when_etag_missing(tmp_path: Path) -> None:
    base = datetime(2026, 9, 22, 0, tzinfo=timezone.utc)
    payload = revenue_payload(amendment_filed="2026-08-15", amendment_value=110.0)

    seed = FakeSecHttpClient(
        [
            SecResponse(
                200,
                {"Last-Modified": "Tue, 22 Sep 2026 00:00:00 GMT"},
                json.dumps(payload).encode(),
            )
        ]
    )
    SecEvidenceStore(
        root=tmp_path / "sec",
        client=seed,
        legacy_cache=None,
        now=lambda: base,
    ).resolve("0000320193", date(2026, 9, 22))

    revalidate = FakeSecHttpClient([SecResponse(304, {}, b"")])
    store = SecEvidenceStore(
        root=tmp_path / "sec",
        client=revalidate,
        legacy_cache=None,
        now=lambda: base + timedelta(hours=7),
    )
    store.resolve("0000320193", date(2026, 9, 22))

    assert revalidate.calls[0][1] == {"If-Modified-Since": "Tue, 22 Sep 2026 00:00:00 GMT"}
    assert revalidate.calls[0][2] == frozenset({304})


def test_stale_manifest_without_validators_refetches_unconditionally(
    tmp_path: Path,
) -> None:
    base = datetime(2026, 9, 22, 0, tzinfo=timezone.utc)

    first_payload = revenue_payload(
        amendment_filed="2026-08-15",
        amendment_value=110.0,
    )
    second_payload = revenue_payload(
        amendment_filed="2026-08-20",
        amendment_value=111.0,
    )

    seed = FakeSecHttpClient([SecResponse(200, {}, json.dumps(first_payload).encode())])
    first = SecEvidenceStore(
        root=tmp_path / "sec",
        client=seed,
        legacy_cache=None,
        now=lambda: base,
    ).resolve("0000320193", date(2026, 9, 22))

    refresh = FakeSecHttpClient([SecResponse(200, {}, json.dumps(second_payload).encode())])
    second = SecEvidenceStore(
        root=tmp_path / "sec",
        client=refresh,
        legacy_cache=None,
        now=lambda: base + timedelta(hours=7),
    ).resolve("0000320193", date(2026, 9, 22))

    assert refresh.calls[0][1] == {}
    assert first.manifest.evidence_revision_sha256 != second.manifest.evidence_revision_sha256


def test_wrong_cik_fails_closed(tmp_path: Path) -> None:
    payload = revenue_payload(
        amendment_filed="2026-08-15",
        amendment_value=110.0,
        cik=789019,
    )
    client = FakeSecHttpClient([SecResponse(200, {}, json.dumps(payload).encode())])
    store = SecEvidenceStore(
        root=tmp_path / "sec",
        client=client,
        legacy_cache=None,
        now=lambda: datetime(2026, 9, 22, 12, tzinfo=timezone.utc),
    )

    with pytest.raises(SecEvidenceError, match="SEC_CIK_MISMATCH"):
        store.resolve("0000320193", date(2026, 9, 22))


def test_corrupt_blob_checksum_fails_closed(tmp_path: Path) -> None:
    now = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
    payload = revenue_payload(amendment_filed="2026-08-15", amendment_value=110.0)

    client = FakeSecHttpClient([SecResponse(200, {}, json.dumps(payload).encode())])
    store = SecEvidenceStore(
        root=tmp_path / "sec",
        client=client,
        legacy_cache=None,
        now=lambda: now,
    )
    resolved = store.resolve("0000320193", date(2026, 9, 22))

    blob = tmp_path / "sec" / "blobs" / resolved.manifest.blob_name
    blob.write_text('{"tampered":true}\n', encoding="utf-8")

    replay = SecEvidenceStore(
        root=tmp_path / "sec",
        client=None,
        legacy_cache=None,
        now=lambda: now + timedelta(hours=1),
    )

    with pytest.raises(SecEvidenceError, match="SEC_BLOB_CHECKSUM_MISMATCH"):
        replay.load_facts(resolved.manifest)


def test_valid_legacy_cache_is_migrated_without_network(tmp_path: Path) -> None:
    identity = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"
    legacy = DiamondCache(tmp_path / "sec")
    legacy.store(
        identity,
        provider="sec-companyfacts",
        data_as_of=date(2026, 9, 22),
        payload=revenue_payload(amendment_filed="2026-08-15", amendment_value=110.0),
    )

    store = SecEvidenceStore(
        root=tmp_path / "sec",
        client=None,
        legacy_cache=legacy,
        now=lambda: datetime(2026, 9, 22, 12, tzinfo=timezone.utc),
    )
    resolved = store.resolve("0000320193", date(2026, 9, 22))

    assert resolved.facts is not None
    assert resolved.manifest.data_as_of == date(2026, 9, 22)
    assert store.provider_requests == 0


def test_legacy_cache_wrong_as_of_is_not_migrated(tmp_path: Path) -> None:
    identity = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"
    legacy = DiamondCache(tmp_path / "sec")
    legacy.store(
        identity,
        provider="sec-companyfacts",
        data_as_of=date(2026, 9, 21),
        payload=revenue_payload(amendment_filed="2026-08-15", amendment_value=110.0),
    )

    replacement = revenue_payload(
        amendment_filed="2026-08-20",
        amendment_value=111.0,
    )
    client = FakeSecHttpClient([SecResponse(200, {}, json.dumps(replacement).encode())])
    store = SecEvidenceStore(
        root=tmp_path / "sec",
        client=client,
        legacy_cache=legacy,
        now=lambda: datetime(2026, 9, 22, 12, tzinfo=timezone.utc),
    )

    resolved = store.resolve("0000320193", date(2026, 9, 22))

    assert len(client.calls) == 1
    assert resolved.manifest.data_as_of == date(2026, 9, 22)
