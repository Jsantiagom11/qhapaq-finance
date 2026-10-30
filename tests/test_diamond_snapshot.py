from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from qhapaq_finance.candidate_set import SnapshotStatus
from qhapaq_finance.diamond.canonical_json import canonical_json_bytes, sha256_canonical_json
from qhapaq_finance.diamond.contracts import SecurityRef
from qhapaq_finance.diamond.engine import DiamondResult
from qhapaq_finance.diamond.funnel import FunnelRun, FunnelRunMetadata
from qhapaq_finance.diamond.snapshot import (
    DiamondSnapshotError,
    finalize_snapshot,
    load_complete_snapshot,
    stage_snapshot,
)

AS_OF = date(2026, 9, 22)
DATASET_IDENTITY = "a" * 64
RANKED_IDS = ("sec-cik:1:A", "sec-cik:2:B")


def _replay(
    *,
    dataset_identity: str = DATASET_IDENTITY,
    ranked_ids: tuple[str, ...] = RANKED_IDS,
    universe_count: int | None = None,
    provider_requests: int = 0,
    cache_misses: int = 0,
) -> FunnelRun:
    results = tuple(
        SimpleNamespace(
            archetypes=SimpleNamespace(research_priority=1.0),
            source_security=SecurityRef(
                ticker=security_id.rsplit(":", 1)[-1],
                security_id=security_id,
                issuer_id=security_id.rsplit(":", 1)[0],
            ),
            data_as_of=AS_OF,
        )
        for security_id in ranked_ids
    )
    typed_results = cast(tuple[DiamondResult, ...], results)
    return FunnelRun(
        results=typed_results,
        metadata=FunnelRunMetadata(
            universe_count=len(results) if universe_count is None else universe_count,
            canonical_records=len(results),
            ranked_records=len(results),
            unranked_records=0,
            provider_requests=provider_requests,
            cache_hits=len(results),
            cache_misses=cache_misses,
            acquisition_seconds=0.0,
            evaluation_seconds=0.0,
            dataset_identity=dataset_identity,
        ),
        evaluated_results=typed_results,
    )


def _source(root: Path) -> tuple[Path, ...]:
    files = (
        root / "universe" / "universe.json",
        root / "sec" / "index" / "issuer.json",
        root / "sec" / "blobs" / "payload.json",
    )
    for index, path in enumerate(files):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'{{"value":{index}}}\n', encoding="utf-8")
    return files


def _stage(source: Path, snapshot: Path):
    return stage_snapshot(
        source_root=source,
        snapshot_root=snapshot,
        selected_paths=_source(source),
        universe_id="sp500",
        cutoff=AS_OF,
        source_run=_replay(),
    )


def test_stage_copies_exact_inventory_without_claiming_complete(tmp_path: Path) -> None:
    staged = _stage(tmp_path / "source", tmp_path / "snapshot")

    assert not (staged.root / "manifest.json").exists()
    assert [item.relative_path for item in staged.files] == [
        "sec/blobs/payload.json",
        "sec/index/issuer.json",
        "universe/universe.json",
    ]
    assert {
        path.relative_to(staged.cache_root).as_posix()
        for path in staged.cache_root.rglob("*")
        if path.is_file()
    } == {item.relative_path for item in staged.files}


def test_finalization_is_last_and_requires_exact_replay(tmp_path: Path) -> None:
    staged = _stage(tmp_path / "source", tmp_path / "snapshot")

    with pytest.raises(DiamondSnapshotError, match="SNAPSHOT_REPLAY_MISMATCH"):
        finalize_snapshot(
            staged,
            replay=_replay(dataset_identity="b" * 64),
        )
    assert not (staged.root / "manifest.json").exists()

    with pytest.raises(DiamondSnapshotError, match="SNAPSHOT_REPLAY_MISMATCH"):
        finalize_snapshot(
            staged,
            replay=_replay(ranked_ids=tuple(reversed(RANKED_IDS))),
        )
    assert not (staged.root / "manifest.json").exists()

    manifest = finalize_snapshot(
        staged,
        replay=_replay(),
    )

    assert manifest.status is SnapshotStatus.COMPLETE
    assert (staged.root / "manifest.json").is_file()
    assert manifest.as_ref().status is SnapshotStatus.COMPLETE


def test_snapshot_identity_excludes_absolute_paths(tmp_path: Path) -> None:
    first = _stage(tmp_path / "source-a", tmp_path / "snapshot-a")
    second = _stage(tmp_path / "source-b", tmp_path / "snapshot-b")

    assert first.snapshot_id == second.snapshot_id
    assert first.files == second.files


def test_manifest_binds_semantic_diamond_coverage(tmp_path: Path) -> None:
    source = tmp_path / "source"
    staged = stage_snapshot(
        source_root=source,
        snapshot_root=tmp_path / "snapshot",
        selected_paths=_source(source),
        universe_id="sp500",
        cutoff=AS_OF,
        source_run=_replay(universe_count=3),
    )

    manifest = finalize_snapshot(staged, replay=_replay(universe_count=3))
    document = json.loads((staged.root / "manifest.json").read_text(encoding="utf-8"))

    assert document["coverage"] == {
        "canonical_records": 2,
        "rankable_records": 2,
        "universe_securities": 3,
        "unrankable_records": 0,
    }
    assert manifest.coverage.universe_securities == 3
    assert load_complete_snapshot(staged.root) == manifest


def test_loader_retains_canonicalizer_v1_snapshot_compatibility(tmp_path: Path) -> None:
    staged = _stage(tmp_path / "source", tmp_path / "snapshot")
    finalize_snapshot(staged, replay=_replay())
    manifest_path = staged.root / "manifest.json"
    manifest_path.chmod(0o644)
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document.pop("coverage")
    document["canonicalizer_version"] = "diamond-snapshot-canonicalizer-v1"
    identity = {
        key: value for key, value in document.items() if key not in {"snapshot_id", "status"}
    }
    document["snapshot_id"] = f"diamond-snapshot:{sha256_canonical_json(identity)}"
    manifest_path.write_bytes(canonical_json_bytes(document) + b"\n")

    loaded = load_complete_snapshot(staged.root)

    assert loaded.canonicalizer_version == "diamond-snapshot-canonicalizer-v1"
    assert loaded.coverage is None


def test_finalization_rejects_semantic_coverage_drift(tmp_path: Path) -> None:
    source = tmp_path / "source"
    staged = stage_snapshot(
        source_root=source,
        snapshot_root=tmp_path / "snapshot",
        selected_paths=_source(source),
        universe_id="sp500",
        cutoff=AS_OF,
        source_run=_replay(universe_count=3),
    )

    with pytest.raises(DiamondSnapshotError, match="SNAPSHOT_REPLAY_MISMATCH"):
        finalize_snapshot(staged, replay=_replay(universe_count=4))

    assert not (staged.root / "manifest.json").exists()


@pytest.mark.parametrize(
    ("provider_requests", "cache_misses"),
    ((1, 0), (0, 1)),
)
def test_finalization_rejects_non_offline_replay_metadata(
    tmp_path: Path,
    provider_requests: int,
    cache_misses: int,
) -> None:
    staged = _stage(tmp_path / "source", tmp_path / "snapshot")

    with pytest.raises(DiamondSnapshotError, match="SNAPSHOT_REPLAY_NOT_OFFLINE"):
        finalize_snapshot(
            staged,
            replay=_replay(
                provider_requests=provider_requests,
                cache_misses=cache_misses,
            ),
        )

    assert not (staged.root / "manifest.json").exists()


def test_load_verifies_context_and_every_selected_byte(tmp_path: Path) -> None:
    staged = _stage(tmp_path / "source", tmp_path / "snapshot")
    finalized = finalize_snapshot(
        staged,
        replay=_replay(),
    )

    loaded = load_complete_snapshot(
        staged.root,
        universe_id="sp500",
        cutoff=AS_OF,
        dataset_identity=DATASET_IDENTITY,
    )
    assert loaded == finalized

    with pytest.raises(DiamondSnapshotError, match="SNAPSHOT_CONTEXT_MISMATCH"):
        load_complete_snapshot(staged.root, universe_id="other")
    with pytest.raises(DiamondSnapshotError, match="SNAPSHOT_CONTEXT_MISMATCH"):
        load_complete_snapshot(staged.root, cutoff=date(2026, 9, 21))

    selected = staged.cache_root / staged.files[0].relative_path
    selected.chmod(0o644)
    selected.write_bytes(selected.read_bytes() + b"x")
    with pytest.raises(DiamondSnapshotError, match="SNAPSHOT_TAMPERED"):
        load_complete_snapshot(staged.root)


def test_extra_file_and_manifest_mutation_fail_closed(tmp_path: Path) -> None:
    staged = _stage(tmp_path / "source", tmp_path / "snapshot")
    finalize_snapshot(
        staged,
        replay=_replay(),
    )

    extra = staged.cache_root / "unexpected.json"
    extra.write_text("{}\n", encoding="utf-8")
    with pytest.raises(DiamondSnapshotError, match="SNAPSHOT_TAMPERED"):
        load_complete_snapshot(staged.root)
    extra.unlink()

    manifest_path = staged.root / "manifest.json"
    manifest_path.chmod(0o644)
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8").replace(
            DATASET_IDENTITY,
            "b" * 64,
        ),
        encoding="utf-8",
    )
    with pytest.raises(DiamondSnapshotError, match="SNAPSHOT_TAMPERED"):
        load_complete_snapshot(staged.root)


def test_complete_snapshot_is_reusable_but_cannot_be_resealed(tmp_path: Path) -> None:
    source = tmp_path / "source"
    staged = _stage(source, tmp_path / "snapshot")
    manifest = finalize_snapshot(
        staged,
        replay=_replay(),
    )

    assert load_complete_snapshot(staged.root) == manifest
    assert load_complete_snapshot(staged.root) == manifest
    with pytest.raises(DiamondSnapshotError, match="SNAPSHOT_ALREADY_COMPLETE"):
        stage_snapshot(
            source_root=source,
            snapshot_root=staged.root,
            selected_paths=_source(source),
            universe_id="sp500",
            cutoff=AS_OF,
            source_run=_replay(),
        )


def test_selected_path_must_be_a_file_inside_source_root(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}\n", encoding="utf-8")

    with pytest.raises(DiamondSnapshotError, match="SNAPSHOT_SOURCE_PATH_INVALID"):
        stage_snapshot(
            source_root=source,
            snapshot_root=tmp_path / "snapshot",
            selected_paths=(outside,),
            universe_id="sp500",
            cutoff=AS_OF,
            source_run=_replay(),
        )
