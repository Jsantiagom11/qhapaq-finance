from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from qhapaq_finance.candidate_set import SnapshotStatus
from qhapaq_finance.diamond.snapshot import (
    DiamondSnapshotError,
    finalize_snapshot,
    load_complete_snapshot,
    stage_snapshot,
)

AS_OF = date(2026, 9, 22)
DATASET_IDENTITY = "a" * 64
RANKED_IDS = ("sec-cik:1:A", "sec-cik:2:B")


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
        dataset_identity=DATASET_IDENTITY,
        ranked_security_ids=RANKED_IDS,
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
            replay_dataset_identity="b" * 64,
            replay_ranked_security_ids=RANKED_IDS,
        )
    assert not (staged.root / "manifest.json").exists()

    with pytest.raises(DiamondSnapshotError, match="SNAPSHOT_REPLAY_MISMATCH"):
        finalize_snapshot(
            staged,
            replay_dataset_identity=DATASET_IDENTITY,
            replay_ranked_security_ids=tuple(reversed(RANKED_IDS)),
        )
    assert not (staged.root / "manifest.json").exists()

    manifest = finalize_snapshot(
        staged,
        replay_dataset_identity=DATASET_IDENTITY,
        replay_ranked_security_ids=RANKED_IDS,
    )

    assert manifest.status is SnapshotStatus.COMPLETE
    assert (staged.root / "manifest.json").is_file()
    assert manifest.as_ref().status is SnapshotStatus.COMPLETE


def test_snapshot_identity_excludes_absolute_paths(tmp_path: Path) -> None:
    first = _stage(tmp_path / "source-a", tmp_path / "snapshot-a")
    second = _stage(tmp_path / "source-b", tmp_path / "snapshot-b")

    assert first.snapshot_id == second.snapshot_id
    assert first.files == second.files


def test_load_verifies_context_and_every_selected_byte(tmp_path: Path) -> None:
    staged = _stage(tmp_path / "source", tmp_path / "snapshot")
    finalized = finalize_snapshot(
        staged,
        replay_dataset_identity=DATASET_IDENTITY,
        replay_ranked_security_ids=RANKED_IDS,
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
        replay_dataset_identity=DATASET_IDENTITY,
        replay_ranked_security_ids=RANKED_IDS,
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
        replay_dataset_identity=DATASET_IDENTITY,
        replay_ranked_security_ids=RANKED_IDS,
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
            dataset_identity=DATASET_IDENTITY,
            ranked_security_ids=RANKED_IDS,
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
            dataset_identity=DATASET_IDENTITY,
            ranked_security_ids=RANKED_IDS,
        )
