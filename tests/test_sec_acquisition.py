from __future__ import annotations

import gzip
import hashlib
import json
import threading
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

import pytest

import qhapaq_finance.sec_acquisition as sec_acquisition
from qhapaq_finance.sec_acquisition import fetch_to_staging
from qhapaq_finance.sec_client import SecClient, SecResponse, _reset_process_rate_limiter_for_tests
from qhapaq_finance.sec_config import SecConfig


class RecordingTransport:
    def __init__(self, response: SecResponse) -> None:
        self.response = response
        self.urls: list[str] = []

    def __call__(
        self, url: str, headers: Mapping[str, str], connect_timeout: float, read_timeout: float
    ) -> SecResponse:
        del headers, connect_timeout, read_timeout
        self.urls.append(url)
        return self.response


@pytest.fixture(autouse=True)
def reset_process_rate_limiter() -> None:
    _reset_process_rate_limiter_for_tests()
    yield
    _reset_process_rate_limiter_for_tests()


def _client(transport: RecordingTransport) -> SecClient:
    return SecClient(SecConfig("Qhapaq Finance", "ops@example.com", 10), transport=transport)


def test_fetch_stages_decoded_sec_response_and_complete_metadata(tmp_path: Path) -> None:
    content = b"SEC filing bytes"
    url = "https://www.sec.gov/Archives/edgar/data/804328/000080432826000086/report.htm"
    transport = RecordingTransport(
        SecResponse(200, {"Content-Type": "text/html", "ETag": "version-1"}, content)
    )

    staged = fetch_to_staging(
        _client(transport),
        url,
        tmp_path / "data/raw",
        now=lambda: datetime(2026, 9, 11, 12, 30, tzinfo=timezone.utc),
        source_metadata={"issuer_id": "qualcomm-incorporated"},
    )

    assert transport.urls == [url]
    assert staged.raw_path.read_bytes() == content
    metadata = json.loads(staged.metadata_path.read_text())
    assert metadata == {
        "byte_size": len(content),
        "artifact_representation": "decoded-entity-body",
        "content_type": "text/html",
        "fetched_at": "2026-09-11T12:30:00Z",
        "http_status": 200,
        "schema_version": "sec-acquisition-v1",
        "sec_source": {
            "accession_number": "000080432826000086",
            "authority": "SEC",
            "declared_issuer_id": "qualcomm-incorporated",
            "etag": "version-1",
            "host": "www.sec.gov",
        },
        "sha256": staged.sha256,
        "source_url": url,
        "state": "STAGED",
    }


def test_fetch_checksums_decoded_gzip_entity_body(tmp_path: Path) -> None:
    entity = b"SEC filing entity body"
    response = SecResponse(200, {"Content-Encoding": "gzip"}, gzip.compress(entity, mtime=0))

    staged = fetch_to_staging(
        _client(RecordingTransport(response)),
        "https://www.sec.gov/Archives/edgar/data/1/000000000000000001/file.htm",
        tmp_path / "data/raw",
    )

    assert staged.raw_path.read_bytes() == entity
    assert staged.sha256 == hashlib.sha256(entity).hexdigest()


def test_fetch_refuses_non_sec_urls_without_calling_transport(tmp_path: Path) -> None:
    transport = RecordingTransport(SecResponse(200, {}, b"unexpected"))

    with pytest.raises(ValueError, match="SEC HTTP"):
        fetch_to_staging(_client(transport), "https://example.com/file", tmp_path / "data/raw")

    assert transport.urls == []


def test_fetch_reuses_existing_identical_staged_artifact(tmp_path: Path) -> None:
    content = b"same bytes"
    url = "https://www.sec.gov/Archives/edgar/data/1/000000000000000001/file.htm"
    first = fetch_to_staging(
        _client(RecordingTransport(SecResponse(200, {}, content))), url, tmp_path / "data/raw"
    )

    repeated = fetch_to_staging(
        _client(RecordingTransport(SecResponse(200, {}, content))), url, tmp_path / "data/raw"
    )

    assert first.raw_path.read_bytes() == content
    assert repeated == first


def test_atomic_write_rejects_corrupt_existing_content(tmp_path: Path) -> None:
    path = tmp_path / "artifact.bin"
    path.write_bytes(b"corrupt")

    with pytest.raises(sec_acquisition.ImmutableArtifactConflictError, match="checksum conflict"):
        sec_acquisition._write_new_atomically(path, b"expected")

    assert path.read_bytes() == b"corrupt"


def test_atomic_write_concurrent_identical_writers_leaves_no_temps(tmp_path: Path) -> None:
    path = tmp_path / "artifact.bin"
    barrier = threading.Barrier(2)
    failures: list[BaseException] = []

    def writer() -> None:
        try:
            barrier.wait()
            sec_acquisition._write_new_atomically(path, b"same concurrent bytes")
        except BaseException as exc:  # pragma: no cover - assertion below reports it
            failures.append(exc)

    threads = [threading.Thread(target=writer), threading.Thread(target=writer)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []
    assert path.read_bytes() == b"same concurrent bytes"
    assert list(tmp_path.glob(".artifact.bin.*")) == []


def test_interrupted_atomic_stage_write_publishes_no_partial_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = RecordingTransport(SecResponse(200, {}, b"interrupted"))

    def interrupted_link(source: Path, target: Path) -> None:
        del source, target
        raise OSError("interrupted")

    monkeypatch.setattr(sec_acquisition.os, "link", interrupted_link)
    with pytest.raises(OSError, match="interrupted"):
        fetch_to_staging(
            _client(transport),
            "https://www.sec.gov/Archives/edgar/data/1/000000000000000001/file.htm",
            tmp_path / "data/raw",
        )

    assert list((tmp_path / "data/raw/sec").glob("*")) == []
