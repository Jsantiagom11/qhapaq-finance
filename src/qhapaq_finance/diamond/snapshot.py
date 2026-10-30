"""Immutable, content-addressed snapshots for offline Diamond replay."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from qhapaq_finance.candidate_set import (
    DiamondSnapshotRef,
    SnapshotStatus,
)

from .canonical_json import canonical_json_bytes, sha256_canonical_json
from .funnel import FunnelRun

SNAPSHOT_SCHEMA_VERSION = "diamond-snapshot-v1"
SNAPSHOT_CANONICALIZER_VERSION = "diamond-snapshot-canonicalizer-v1"
MANIFEST_NAME = "manifest.json"


class DiamondSnapshotError(RuntimeError):
    """A Diamond snapshot could not be sealed or verified safely."""


@dataclass(frozen=True, slots=True)
class SnapshotFile:
    relative_path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class StagedDiamondSnapshot:
    root: Path
    cache_root: Path
    snapshot_id: str
    dataset_identity: str
    universe_id: str
    cutoff: date
    files: tuple[SnapshotFile, ...]
    ranked_security_ids: tuple[str, ...]
    ranked_order_sha256: str


@dataclass(frozen=True, slots=True)
class DiamondSnapshotManifest:
    root: Path
    snapshot_id: str
    dataset_identity: str
    universe_id: str
    cutoff: date
    status: SnapshotStatus
    files: tuple[SnapshotFile, ...]
    ranked_count: int
    ranked_order_sha256: str

    @property
    def cache_root(self) -> Path:
        return self.root / "cache"

    def as_ref(self) -> DiamondSnapshotRef:
        return DiamondSnapshotRef(
            snapshot_id=self.snapshot_id,
            dataset_identity=self.dataset_identity,
            universe_id=self.universe_id,
            cutoff=self.cutoff,
            status=self.status,
        )


def _require_sha256(value: str, code: str) -> str:
    normalized = value.strip()
    if len(normalized) != 64 or normalized.lower() != normalized:
        raise DiamondSnapshotError(code)
    try:
        bytes.fromhex(normalized)
    except ValueError as exc:
        raise DiamondSnapshotError(code) from exc
    return normalized


def _require_text(value: str, code: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise DiamondSnapshotError(code)
    return normalized


def _file_sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
    except OSError as exc:
        raise DiamondSnapshotError("SNAPSHOT_FILE_UNREADABLE") from exc
    return digest.hexdigest(), size


def _files_payload(files: tuple[SnapshotFile, ...]) -> list[dict[str, object]]:
    return [
        {
            "relative_path": item.relative_path,
            "size_bytes": item.size_bytes,
            "sha256": item.sha256,
        }
        for item in files
    ]


def _identity_payload(
    *,
    dataset_identity: str,
    universe_id: str,
    cutoff: date,
    files: tuple[SnapshotFile, ...],
    ranked_count: int,
    ranked_order_sha256: str,
) -> dict[str, object]:
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "canonicalizer_version": SNAPSHOT_CANONICALIZER_VERSION,
        "dataset_identity": dataset_identity,
        "universe_id": universe_id,
        "cutoff": cutoff.isoformat(),
        "files": _files_payload(files),
        "ranked_count": ranked_count,
        "ranked_order_sha256": ranked_order_sha256,
    }


def _snapshot_id(
    *,
    dataset_identity: str,
    universe_id: str,
    cutoff: date,
    files: tuple[SnapshotFile, ...],
    ranked_count: int,
    ranked_order_sha256: str,
) -> str:
    digest = sha256_canonical_json(
        _identity_payload(
            dataset_identity=dataset_identity,
            universe_id=universe_id,
            cutoff=cutoff,
            files=files,
            ranked_count=ranked_count,
            ranked_order_sha256=ranked_order_sha256,
        )
    )
    return f"diamond-snapshot:{digest}"


def _atomic_write(target: Path, content: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _copy_verified(source: Path, target: Path) -> SnapshotFile:
    descriptor, temporary = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    digest = hashlib.sha256()
    size = 0
    try:
        with os.fdopen(descriptor, "wb") as target_stream, source.open("rb") as source_stream:
            for chunk in iter(lambda: source_stream.read(1024 * 1024), b""):
                target_stream.write(chunk)
                digest.update(chunk)
                size += len(chunk)
            target_stream.flush()
            os.fsync(target_stream.fileno())
        os.replace(temporary, target)
    except BaseException as exc:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        if isinstance(exc, OSError):
            raise DiamondSnapshotError("SNAPSHOT_SOURCE_PATH_INVALID") from exc
        raise
    target.chmod(0o444)
    target_sha256, target_size = _file_sha256(target)
    if target_size != size or target_sha256 != digest.hexdigest():
        raise DiamondSnapshotError("SNAPSHOT_COPY_MISMATCH")
    return SnapshotFile(
        relative_path="",
        size_bytes=size,
        sha256=digest.hexdigest(),
    )


def _inventory(cache_root: Path) -> set[str]:
    return {
        path.relative_to(cache_root).as_posix() for path in cache_root.rglob("*") if path.is_file()
    }


def _verify_inventory(
    cache_root: Path,
    files: tuple[SnapshotFile, ...],
) -> None:
    expected = {item.relative_path for item in files}
    if _inventory(cache_root) != expected:
        raise DiamondSnapshotError("SNAPSHOT_TAMPERED")
    for item in files:
        path = cache_root / item.relative_path
        if path.is_symlink():
            raise DiamondSnapshotError("SNAPSHOT_TAMPERED")
        sha256, size = _file_sha256(path)
        if sha256 != item.sha256 or size != item.size_bytes:
            raise DiamondSnapshotError("SNAPSHOT_TAMPERED")


def stage_snapshot(
    *,
    source_root: Path,
    snapshot_root: Path,
    selected_paths: tuple[Path, ...],
    universe_id: str,
    cutoff: date,
    dataset_identity: str,
    ranked_security_ids: tuple[str, ...],
) -> StagedDiamondSnapshot:
    """Copy the exact selected cache inventory without declaring completeness."""

    if not isinstance(cutoff, date):
        raise DiamondSnapshotError("SNAPSHOT_CUTOFF_INVALID")
    normalized_dataset = _require_sha256(
        dataset_identity,
        "SNAPSHOT_DATASET_IDENTITY_INVALID",
    )
    normalized_universe = _require_text(universe_id, "SNAPSHOT_UNIVERSE_REQUIRED")
    normalized_ranked_ids = tuple(
        _require_text(item, "SNAPSHOT_RANKED_ID_INVALID") for item in ranked_security_ids
    )

    source = Path(source_root).resolve()
    root = Path(snapshot_root).resolve()
    manifest_path = root / MANIFEST_NAME
    if manifest_path.exists():
        raise DiamondSnapshotError("SNAPSHOT_ALREADY_COMPLETE")
    cache_root = root / "cache"
    cache_root.mkdir(parents=True, exist_ok=True)

    relative_sources: dict[str, Path] = {}
    for selected in selected_paths:
        candidate = Path(selected)
        if not candidate.is_absolute() or candidate.is_symlink():
            raise DiamondSnapshotError("SNAPSHOT_SOURCE_PATH_INVALID")
        try:
            resolved = candidate.resolve(strict=True)
            relative = resolved.relative_to(source)
        except (OSError, ValueError) as exc:
            raise DiamondSnapshotError("SNAPSHOT_SOURCE_PATH_INVALID") from exc
        if not resolved.is_file() or resolved.is_symlink():
            raise DiamondSnapshotError("SNAPSHOT_SOURCE_PATH_INVALID")
        relative_sources[relative.as_posix()] = resolved
    if not relative_sources:
        raise DiamondSnapshotError("SNAPSHOT_SOURCE_EMPTY")

    copied: list[SnapshotFile] = []
    for relative_path, source_path in sorted(relative_sources.items()):
        target = cache_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.parent.resolve().relative_to(cache_root)
        except ValueError as exc:
            raise DiamondSnapshotError("SNAPSHOT_TARGET_PATH_INVALID") from exc
        copied_file = _copy_verified(source_path, target)
        copied.append(
            SnapshotFile(
                relative_path=relative_path,
                size_bytes=copied_file.size_bytes,
                sha256=copied_file.sha256,
            )
        )

    files = tuple(copied)
    if _inventory(cache_root) != {item.relative_path for item in files}:
        raise DiamondSnapshotError("SNAPSHOT_STAGING_DIRTY")
    ranked_order_sha256 = sha256_canonical_json(list(normalized_ranked_ids))
    snapshot_id = _snapshot_id(
        dataset_identity=normalized_dataset,
        universe_id=normalized_universe,
        cutoff=cutoff,
        files=files,
        ranked_count=len(normalized_ranked_ids),
        ranked_order_sha256=ranked_order_sha256,
    )
    return StagedDiamondSnapshot(
        root=root,
        cache_root=cache_root,
        snapshot_id=snapshot_id,
        dataset_identity=normalized_dataset,
        universe_id=normalized_universe,
        cutoff=cutoff,
        files=files,
        ranked_security_ids=normalized_ranked_ids,
        ranked_order_sha256=ranked_order_sha256,
    )


def _manifest_document(manifest: DiamondSnapshotManifest) -> dict[str, object]:
    return {
        **_identity_payload(
            dataset_identity=manifest.dataset_identity,
            universe_id=manifest.universe_id,
            cutoff=manifest.cutoff,
            files=manifest.files,
            ranked_count=manifest.ranked_count,
            ranked_order_sha256=manifest.ranked_order_sha256,
        ),
        "snapshot_id": manifest.snapshot_id,
        "status": manifest.status.value,
    }


def finalize_snapshot(
    staged: StagedDiamondSnapshot,
    *,
    replay: FunnelRun,
) -> DiamondSnapshotManifest:
    """Atomically transition a staged snapshot to COMPLETE after exact replay."""

    if (staged.root / MANIFEST_NAME).exists():
        raise DiamondSnapshotError("SNAPSHOT_ALREADY_COMPLETE")
    if replay.metadata.provider_requests != 0 or replay.metadata.cache_misses != 0:
        raise DiamondSnapshotError("SNAPSHOT_REPLAY_NOT_OFFLINE")
    replay_results = replay.evaluated_results or replay.results
    replay_ranked_ids: list[str] = []
    for result in replay_results:
        if result.data_as_of != staged.cutoff:
            raise DiamondSnapshotError("SNAPSHOT_REPLAY_MISMATCH")
        if result.archetypes.research_priority is None:
            continue
        if result.source_security is None:
            raise DiamondSnapshotError("SNAPSHOT_REPLAY_MISMATCH")
        replay_ranked_ids.append(result.source_security.security_id)
    if (
        replay.metadata.dataset_identity != staged.dataset_identity
        or replay.metadata.ranked_records != len(replay_ranked_ids)
        or tuple(replay_ranked_ids) != staged.ranked_security_ids
    ):
        raise DiamondSnapshotError("SNAPSHOT_REPLAY_MISMATCH")
    _verify_inventory(staged.cache_root, staged.files)

    manifest = DiamondSnapshotManifest(
        root=staged.root,
        snapshot_id=staged.snapshot_id,
        dataset_identity=staged.dataset_identity,
        universe_id=staged.universe_id,
        cutoff=staged.cutoff,
        status=SnapshotStatus.COMPLETE,
        files=staged.files,
        ranked_count=len(staged.ranked_security_ids),
        ranked_order_sha256=staged.ranked_order_sha256,
    )
    manifest_path = staged.root / MANIFEST_NAME
    _atomic_write(
        manifest_path,
        canonical_json_bytes(_manifest_document(manifest)) + b"\n",
    )
    manifest_path.chmod(0o444)
    return manifest


def _decode_manifest(root: Path, payload: object) -> DiamondSnapshotManifest:
    if not isinstance(payload, dict):
        raise DiamondSnapshotError("SNAPSHOT_TAMPERED")
    try:
        files_raw = payload["files"]
        if not isinstance(files_raw, list):
            raise DiamondSnapshotError("SNAPSHOT_TAMPERED")
        files = tuple(
            SnapshotFile(
                relative_path=str(item["relative_path"]),
                size_bytes=int(item["size_bytes"]),
                sha256=_require_sha256(str(item["sha256"]), "SNAPSHOT_TAMPERED"),
            )
            for item in files_raw
            if isinstance(item, dict)
        )
        if len(files) != len(files_raw):
            raise DiamondSnapshotError("SNAPSHOT_TAMPERED")
        manifest = DiamondSnapshotManifest(
            root=root,
            snapshot_id=str(payload["snapshot_id"]),
            dataset_identity=_require_sha256(
                str(payload["dataset_identity"]),
                "SNAPSHOT_TAMPERED",
            ),
            universe_id=_require_text(str(payload["universe_id"]), "SNAPSHOT_TAMPERED"),
            cutoff=date.fromisoformat(str(payload["cutoff"])),
            status=SnapshotStatus(str(payload["status"])),
            files=files,
            ranked_count=int(payload["ranked_count"]),
            ranked_order_sha256=_require_sha256(
                str(payload["ranked_order_sha256"]),
                "SNAPSHOT_TAMPERED",
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DiamondSnapshotError("SNAPSHOT_TAMPERED") from exc
    if payload.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        raise DiamondSnapshotError("SNAPSHOT_TAMPERED")
    if payload.get("canonicalizer_version") != SNAPSHOT_CANONICALIZER_VERSION:
        raise DiamondSnapshotError("SNAPSHOT_TAMPERED")
    if manifest.status is not SnapshotStatus.COMPLETE:
        raise DiamondSnapshotError("SNAPSHOT_INCOMPLETE")
    if manifest.ranked_count < 0 or not manifest.files:
        raise DiamondSnapshotError("SNAPSHOT_TAMPERED")
    relative_paths = [item.relative_path for item in manifest.files]
    if relative_paths != sorted(relative_paths) or len(relative_paths) != len(set(relative_paths)):
        raise DiamondSnapshotError("SNAPSHOT_TAMPERED")
    for item in manifest.files:
        path = Path(item.relative_path)
        if (
            not item.relative_path
            or path.is_absolute()
            or ".." in path.parts
            or "." in path.parts
            or item.size_bytes < 0
        ):
            raise DiamondSnapshotError("SNAPSHOT_TAMPERED")
    expected_id = _snapshot_id(
        dataset_identity=manifest.dataset_identity,
        universe_id=manifest.universe_id,
        cutoff=manifest.cutoff,
        files=manifest.files,
        ranked_count=manifest.ranked_count,
        ranked_order_sha256=manifest.ranked_order_sha256,
    )
    if manifest.snapshot_id != expected_id:
        raise DiamondSnapshotError("SNAPSHOT_TAMPERED")
    return manifest


def load_complete_snapshot(
    snapshot_root: Path,
    *,
    universe_id: str | None = None,
    cutoff: date | None = None,
    dataset_identity: str | None = None,
) -> DiamondSnapshotManifest:
    """Load a COMPLETE snapshot and verify its context and exact byte inventory."""

    root = Path(snapshot_root).resolve()
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.exists():
        raise DiamondSnapshotError("SNAPSHOT_INCOMPLETE")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DiamondSnapshotError("SNAPSHOT_TAMPERED") from exc
    manifest = _decode_manifest(root, payload)
    if (
        (universe_id is not None and universe_id != manifest.universe_id)
        or (cutoff is not None and cutoff != manifest.cutoff)
        or (dataset_identity is not None and dataset_identity != manifest.dataset_identity)
    ):
        raise DiamondSnapshotError("SNAPSHOT_CONTEXT_MISMATCH")
    _verify_inventory(manifest.cache_root, manifest.files)
    return manifest


__all__ = [
    "DiamondSnapshotError",
    "DiamondSnapshotManifest",
    "SnapshotFile",
    "StagedDiamondSnapshot",
    "finalize_snapshot",
    "load_complete_snapshot",
    "stage_snapshot",
]
