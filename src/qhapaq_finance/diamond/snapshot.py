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
LEGACY_SNAPSHOT_CANONICALIZER_VERSION = "diamond-snapshot-canonicalizer-v1"
SNAPSHOT_CANONICALIZER_VERSION = "diamond-snapshot-canonicalizer-v2"
MANIFEST_NAME = "manifest.json"


class DiamondSnapshotError(RuntimeError):
    """A Diamond snapshot could not be sealed or verified safely."""


@dataclass(frozen=True, slots=True)
class SnapshotFile:
    relative_path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class DiamondSnapshotCoverage:
    universe_securities: int
    canonical_records: int
    rankable_records: int
    unrankable_records: int


@dataclass(frozen=True, slots=True)
class StagedDiamondSnapshot:
    root: Path
    cache_root: Path
    snapshot_id: str
    dataset_identity: str
    universe_id: str
    cutoff: date
    canonicalizer_version: str
    coverage: DiamondSnapshotCoverage
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
    canonicalizer_version: str
    coverage: DiamondSnapshotCoverage | None
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


def _coverage_payload(coverage: DiamondSnapshotCoverage) -> dict[str, int]:
    return {
        "universe_securities": coverage.universe_securities,
        "canonical_records": coverage.canonical_records,
        "rankable_records": coverage.rankable_records,
        "unrankable_records": coverage.unrankable_records,
    }


def _identity_payload(
    *,
    canonicalizer_version: str,
    dataset_identity: str,
    universe_id: str,
    cutoff: date,
    coverage: DiamondSnapshotCoverage | None,
    files: tuple[SnapshotFile, ...],
    ranked_count: int,
    ranked_order_sha256: str,
) -> dict[str, object]:
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "canonicalizer_version": canonicalizer_version,
        "dataset_identity": dataset_identity,
        "universe_id": universe_id,
        "cutoff": cutoff.isoformat(),
        "files": _files_payload(files),
        "ranked_count": ranked_count,
        "ranked_order_sha256": ranked_order_sha256,
        **({"coverage": _coverage_payload(coverage)} if coverage is not None else {}),
    }


def _snapshot_id(
    *,
    canonicalizer_version: str,
    dataset_identity: str,
    universe_id: str,
    cutoff: date,
    coverage: DiamondSnapshotCoverage | None,
    files: tuple[SnapshotFile, ...],
    ranked_count: int,
    ranked_order_sha256: str,
) -> str:
    digest = sha256_canonical_json(
        _identity_payload(
            canonicalizer_version=canonicalizer_version,
            dataset_identity=dataset_identity,
            universe_id=universe_id,
            cutoff=cutoff,
            coverage=coverage,
            files=files,
            ranked_count=ranked_count,
            ranked_order_sha256=ranked_order_sha256,
        )
    )
    return f"diamond-snapshot:{digest}"


def _run_state(
    run: FunnelRun,
    *,
    cutoff: date,
    offline_error: str,
) -> tuple[str, tuple[str, ...], DiamondSnapshotCoverage]:
    if run.metadata.provider_requests != 0 or run.metadata.cache_misses != 0:
        raise DiamondSnapshotError(offline_error)
    results = run.evaluated_results or run.results
    ranked_ids: list[str] = []
    for result in results:
        if result.data_as_of != cutoff:
            raise DiamondSnapshotError("SNAPSHOT_RUN_CONTEXT_MISMATCH")
        if result.archetypes.research_priority is None:
            continue
        if result.source_security is None:
            raise DiamondSnapshotError("SNAPSHOT_RUN_CONTEXT_MISMATCH")
        ranked_ids.append(
            _require_text(result.source_security.security_id, "SNAPSHOT_RANKED_ID_INVALID")
        )
    metadata = run.metadata
    counts = (
        metadata.universe_count,
        metadata.canonical_records,
        metadata.ranked_records,
        metadata.unranked_records,
    )
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts
    ) or (
        metadata.universe_count < metadata.canonical_records
        or metadata.canonical_records != len(results)
        or metadata.ranked_records != len(ranked_ids)
        or metadata.unranked_records != len(results) - len(ranked_ids)
    ):
        raise DiamondSnapshotError("SNAPSHOT_RUN_COVERAGE_INVALID")
    coverage = DiamondSnapshotCoverage(
        universe_securities=metadata.universe_count,
        canonical_records=metadata.canonical_records,
        rankable_records=metadata.ranked_records,
        unrankable_records=metadata.unranked_records,
    )
    return (
        _require_sha256(metadata.dataset_identity, "SNAPSHOT_DATASET_IDENTITY_INVALID"),
        tuple(ranked_ids),
        coverage,
    )


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
    source_run: FunnelRun,
) -> StagedDiamondSnapshot:
    """Copy the exact selected cache inventory without declaring completeness."""

    if not isinstance(cutoff, date):
        raise DiamondSnapshotError("SNAPSHOT_CUTOFF_INVALID")
    normalized_dataset, normalized_ranked_ids, coverage = _run_state(
        source_run,
        cutoff=cutoff,
        offline_error="SNAPSHOT_SOURCE_NOT_OFFLINE",
    )
    normalized_universe = _require_text(universe_id, "SNAPSHOT_UNIVERSE_REQUIRED")

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
        canonicalizer_version=SNAPSHOT_CANONICALIZER_VERSION,
        dataset_identity=normalized_dataset,
        universe_id=normalized_universe,
        cutoff=cutoff,
        coverage=coverage,
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
        canonicalizer_version=SNAPSHOT_CANONICALIZER_VERSION,
        coverage=coverage,
        files=files,
        ranked_security_ids=normalized_ranked_ids,
        ranked_order_sha256=ranked_order_sha256,
    )


def _manifest_document(manifest: DiamondSnapshotManifest) -> dict[str, object]:
    return {
        **_identity_payload(
            canonicalizer_version=manifest.canonicalizer_version,
            dataset_identity=manifest.dataset_identity,
            universe_id=manifest.universe_id,
            cutoff=manifest.cutoff,
            coverage=manifest.coverage,
            files=manifest.files,
            ranked_count=manifest.ranked_count,
            ranked_order_sha256=manifest.ranked_order_sha256,
        ),
        "snapshot_id": manifest.snapshot_id,
        "status": manifest.status.value,
    }


def _decode_coverage(payload: object) -> DiamondSnapshotCoverage:
    if not isinstance(payload, dict):
        raise DiamondSnapshotError("SNAPSHOT_TAMPERED")
    names = (
        "universe_securities",
        "canonical_records",
        "rankable_records",
        "unrankable_records",
    )
    if set(payload) != set(names) or any(isinstance(payload[name], bool) for name in names):
        raise DiamondSnapshotError("SNAPSHOT_TAMPERED")
    try:
        coverage = DiamondSnapshotCoverage(
            universe_securities=int(payload["universe_securities"]),
            canonical_records=int(payload["canonical_records"]),
            rankable_records=int(payload["rankable_records"]),
            unrankable_records=int(payload["unrankable_records"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DiamondSnapshotError("SNAPSHOT_TAMPERED") from exc
    counts = tuple(_coverage_payload(coverage).values())
    if any(value < 0 for value in counts) or (
        coverage.universe_securities < coverage.canonical_records
        or coverage.canonical_records != coverage.rankable_records + coverage.unrankable_records
    ):
        raise DiamondSnapshotError("SNAPSHOT_TAMPERED")
    return coverage


def finalize_snapshot(
    staged: StagedDiamondSnapshot,
    *,
    replay: FunnelRun,
) -> DiamondSnapshotManifest:
    """Atomically transition a staged snapshot to COMPLETE after exact replay."""

    if (staged.root / MANIFEST_NAME).exists():
        raise DiamondSnapshotError("SNAPSHOT_ALREADY_COMPLETE")
    replay_dataset_identity, replay_ranked_ids, replay_coverage = _run_state(
        replay,
        cutoff=staged.cutoff,
        offline_error="SNAPSHOT_REPLAY_NOT_OFFLINE",
    )
    if (
        replay_dataset_identity != staged.dataset_identity
        or replay_coverage != staged.coverage
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
        canonicalizer_version=staged.canonicalizer_version,
        coverage=staged.coverage,
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
        canonicalizer_version = str(payload["canonicalizer_version"])
        if canonicalizer_version == SNAPSHOT_CANONICALIZER_VERSION:
            coverage: DiamondSnapshotCoverage | None = _decode_coverage(payload.get("coverage"))
        elif canonicalizer_version == LEGACY_SNAPSHOT_CANONICALIZER_VERSION:
            if "coverage" in payload:
                raise DiamondSnapshotError("SNAPSHOT_TAMPERED")
            coverage = None
        else:
            raise DiamondSnapshotError("SNAPSHOT_TAMPERED")
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
            canonicalizer_version=canonicalizer_version,
            coverage=coverage,
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
        canonicalizer_version=manifest.canonicalizer_version,
        dataset_identity=manifest.dataset_identity,
        universe_id=manifest.universe_id,
        cutoff=manifest.cutoff,
        coverage=manifest.coverage,
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
    "DiamondSnapshotCoverage",
    "DiamondSnapshotError",
    "DiamondSnapshotManifest",
    "SnapshotFile",
    "StagedDiamondSnapshot",
    "finalize_snapshot",
    "load_complete_snapshot",
    "stage_snapshot",
]
