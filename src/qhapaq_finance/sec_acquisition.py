"""Explicit, review-gated acquisition of SEC resources into staging only."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .sec_client import SecClient, SecResponse

_ACCESSION_PATTERN = re.compile(r"(?<!\d)(\d{10}-\d{2}-\d{6}|\d{18})(?!\d)")
_IDENTITY_HEADERS = ("etag", "last-modified", "content-disposition", "x-amz-version-id")


class ImmutableArtifactConflictError(RuntimeError):
    """An immutable artifact path already contains different or invalid bytes."""


@dataclass(frozen=True, slots=True)
class StagedSecResource:
    """An immutable decoded SEC entity body and its acquisition sidecar."""

    raw_path: Path
    metadata_path: Path
    sha256: str
    byte_size: int


def fetch_to_staging(
    client: SecClient,
    source_url: str,
    staging_root: str | Path,
    *,
    now: Callable[[], datetime] | None = None,
    source_metadata: Mapping[str, str] | None = None,
) -> StagedSecResource:
    """Fetch an SEC URL through ``client`` and stage immutable decoded entity bytes.

    This function deliberately has no access to trusted evidence directories and
    performs neither verification nor promotion. Existing staged artifacts are
    never replaced.
    """
    parsed = urlsplit(source_url)
    host = parsed.hostname
    if parsed.scheme not in {"http", "https"} or host is None or not _is_sec_host(host):
        raise ValueError("source_url must be an absolute SEC HTTP(S) URL")

    response = client.get(source_url)
    return stage_sec_response(
        source_url,
        response,
        staging_root,
        now=now,
        source_metadata=source_metadata,
    )


def stage_sec_response(
    source_url: str,
    response: SecResponse,
    staging_root: str | Path,
    *,
    now: Callable[[], datetime] | None = None,
    source_metadata: Mapping[str, str] | None = None,
) -> StagedSecResource:
    """Atomically stage a decoded SEC entity body without promotion.

    Staged artifact checksums identify decoded entity bodies, not transfer-coded
    bytes.  ``SecResponse.content`` remains available for transport diagnostics.
    """
    parsed = urlsplit(source_url)
    host = parsed.hostname
    if parsed.scheme not in {"http", "https"} or host is None or not _is_sec_host(host):
        raise ValueError("source_url must be an absolute SEC HTTP(S) URL")
    content = response.decoded_content
    checksum = hashlib.sha256(content).hexdigest()
    staged_at = (now or (lambda: datetime.now(timezone.utc)))().astimezone(timezone.utc)
    destination = Path(staging_root) / "sec"
    raw_path = destination / f"{checksum}.bin"
    metadata_path = destination / f"{checksum}.json"
    metadata = _metadata(
        source_url=source_url,
        host=host,
        response_status=response.status_code,
        response_headers=response.headers,
        checksum=checksum,
        byte_size=len(content),
        fetched_at=staged_at,
        source_metadata=source_metadata,
    )

    _write_new_atomically(raw_path, content)
    try:
        _write_metadata_atomically(metadata_path, metadata)
    except Exception:
        # The raw bytes remain an untrusted staged artifact; never replace or
        # delete a possible pre-existing artifact while handling an error.
        raise
    return StagedSecResource(raw_path, metadata_path, checksum, len(content))


def _is_sec_host(host: str) -> bool:
    normalized = host.rstrip(".").lower()
    return normalized == "sec.gov" or normalized.endswith(".sec.gov")


def _metadata(
    *,
    source_url: str,
    host: str,
    response_status: int,
    response_headers: Mapping[str, str],
    checksum: str,
    byte_size: int,
    fetched_at: datetime,
    source_metadata: Mapping[str, str] | None,
) -> dict[str, Any]:
    headers = {name.lower(): value for name, value in response_headers.items()}
    accession = _ACCESSION_PATTERN.search(source_url)
    sec_source: dict[str, str] = {"authority": "SEC", "host": host}
    if accession is not None:
        sec_source["accession_number"] = accession.group(1)
    for name in _IDENTITY_HEADERS:
        if value := headers.get(name):
            sec_source[name] = value
    if source_metadata:
        sec_source.update({f"declared_{key}": value for key, value in source_metadata.items()})
    return {
        "schema_version": "sec-acquisition-v1",
        "state": "STAGED",
        "source_url": source_url,
        "fetched_at": fetched_at.isoformat().replace("+00:00", "Z"),
        "http_status": response_status,
        "content_type": headers.get("content-type"),
        "artifact_representation": "decoded-entity-body",
        "sha256": checksum,
        "byte_size": byte_size,
        "sec_source": sec_source,
    }


def _write_new_atomically(path: Path, content: bytes) -> None:
    """Atomically publish immutable bytes, reusing an identical artifact.

    ``link`` is the publication primitive: it either creates the destination
    atomically or reports that a concurrent/prior publisher got there first.
    The latter is verified after the fact, never pre-checked.
    """
    expected_checksum = hashlib.sha256(content).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            try:
                actual_checksum = _file_sha256(path)
            except OSError as read_exc:
                raise ImmutableArtifactConflictError(
                    f"unable to verify existing immutable artifact: {path}"
                ) from read_exc
            if actual_checksum != expected_checksum:
                raise ImmutableArtifactConflictError(
                    f"immutable artifact checksum conflict at {path}: "
                    f"expected {expected_checksum}, found {actual_checksum}"
                ) from exc
    finally:
        temporary.unlink(missing_ok=True)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_metadata_atomically(path: Path, metadata: dict[str, Any]) -> None:
    """Publish source identity metadata while retaining the first event time.

    ``fetched_at`` describes an acquisition event rather than the immutable
    content identity.  Keeping the first sidecar makes repeated acquisition of
    unchanged bytes stable, while every other metadata field remains strict.
    """
    content = (json.dumps(metadata, sort_keys=True, separators=(",", ":")) + "\n").encode()
    try:
        _write_new_atomically(path, content)
    except ImmutableArtifactConflictError as exc:
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as read_exc:
            raise ImmutableArtifactConflictError(
                f"invalid existing immutable metadata: {path}"
            ) from read_exc
        if not isinstance(existing, dict):
            raise ImmutableArtifactConflictError(
                f"invalid existing immutable metadata: {path}"
            ) from None
        existing.pop("fetched_at", None)
        expected = dict(metadata)
        expected.pop("fetched_at", None)
        if existing != expected:
            raise exc
