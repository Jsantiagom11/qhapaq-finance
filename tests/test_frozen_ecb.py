import json
import shutil
import socket
from datetime import date
from pathlib import Path

import pytest

from qhapaq_finance.data import (
    FROZEN_ECB_FX_MANIFEST,
    FrozenSnapshotError,
    file_sha256,
    load_frozen_fx_snapshot,
)

REPOSITORY_ROOT = Path(__file__).parents[1]
MANIFEST = REPOSITORY_ROOT / FROZEN_ECB_FX_MANIFEST
ARTIFACT_RELATIVE = Path("data/frozen/ecb/exr_daily_eur_reference_rates_2015-01-01_2026-08-31.csv")
EXPECTED_SERIES = (
    "D.CHF.EUR.SP00.A",
    "D.GBP.EUR.SP00.A",
    "D.JPY.EUR.SP00.A",
    "D.USD.EUR.SP00.A",
)


def _sandbox(tmp_path: Path) -> tuple[Path, Path]:
    manifest = tmp_path / FROZEN_ECB_FX_MANIFEST
    artifact = tmp_path / ARTIFACT_RELATIVE
    manifest.parent.mkdir(parents=True)
    shutil.copy2(MANIFEST, manifest)
    shutil.copy2(REPOSITORY_ROOT / ARTIFACT_RELATIVE, artifact)
    return manifest, artifact


def _manifest_payload(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_manifest(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _refresh_artifact_identity(manifest: Path, artifact: Path) -> None:
    payload = _manifest_payload(manifest)
    identity = payload["artifact"]
    assert isinstance(identity, dict)
    identity["byte_count"] = artifact.stat().st_size
    identity["sha256"] = file_sha256(artifact)
    _write_manifest(manifest, payload)


def test_committed_artifact_and_manifest_are_deterministic() -> None:
    payload = _manifest_payload(MANIFEST)
    identity = payload["artifact"]
    assert isinstance(identity, dict)
    artifact = REPOSITORY_ROOT / ARTIFACT_RELATIVE
    assert artifact.stat().st_size == identity["byte_count"] == 2_541_412
    assert file_sha256(artifact) == identity["sha256"]
    assert (
        MANIFEST.read_text(encoding="utf-8") == json.dumps(payload, indent=2, sort_keys=True) + "\n"
    )


def test_valid_snapshot_loads_all_series_in_deterministic_order() -> None:
    snapshot = load_frozen_fx_snapshot(repository_root=REPOSITORY_ROOT)
    assert snapshot.dataset_id == "ecb-exr-daily-eur-reference-rates-2015-01-01_2026-08-31"
    assert snapshot.series_ids == EXPECTED_SERIES
    assert snapshot.observation_count == 11_940
    ordered = snapshot.observations[["series_id", "observation_date"]]
    assert ordered.equals(
        ordered.sort_values(list(ordered.columns), kind="stable").reset_index(drop=True)
    )
    assert snapshot.price_panel.columns.tolist() == ["CHF", "GBP", "JPY", "USD"]


def test_default_as_of_is_derived_from_validated_data() -> None:
    snapshot = load_frozen_fx_snapshot(repository_root=REPOSITORY_ROOT)
    assert snapshot.effective_as_of == snapshot.actual_end == date(2026, 8, 31)


def test_explicit_as_of_excludes_later_observations() -> None:
    snapshot = load_frozen_fx_snapshot(repository_root=REPOSITORY_ROOT, as_of="2020-12-31")
    assert snapshot.effective_as_of == date(2020, 12, 31)
    assert snapshot.observations["observation_date"].max() <= snapshot.effective_as_of
    assert snapshot.observation_count < 11_940


def test_missing_artifact_fails_explicitly(tmp_path: Path) -> None:
    manifest, artifact = _sandbox(tmp_path)
    artifact.unlink()
    with pytest.raises(FileNotFoundError, match="artifact not found"):
        load_frozen_fx_snapshot(manifest, repository_root=tmp_path)


def test_missing_manifest_fails_explicitly(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="manifest not found"):
        load_frozen_fx_snapshot(tmp_path / "missing.json", repository_root=tmp_path)


def test_incomplete_manifest_fails_explicitly(tmp_path: Path) -> None:
    manifest, _ = _sandbox(tmp_path)
    _write_manifest(manifest, {"schema_version": "1.0"})
    with pytest.raises(FrozenSnapshotError, match="missing required fields"):
        load_frozen_fx_snapshot(manifest, repository_root=tmp_path)


def test_checksum_mismatch_fails_before_parsing(tmp_path: Path) -> None:
    manifest, artifact = _sandbox(tmp_path)
    artifact.write_bytes(artifact.read_bytes().replace(b"1.2022", b"1.2023", 1))
    with pytest.raises(FrozenSnapshotError, match="checksum"):
        load_frozen_fx_snapshot(manifest, repository_root=tmp_path)


def test_malformed_date_fails_explicitly(tmp_path: Path) -> None:
    manifest, artifact = _sandbox(tmp_path)
    content = artifact.read_bytes().replace(b"2015-01-02", b"2015/01/02", 1)
    artifact.write_bytes(content)
    _refresh_artifact_identity(manifest, artifact)
    with pytest.raises(FrozenSnapshotError, match="malformed dates"):
        load_frozen_fx_snapshot(manifest, repository_root=tmp_path)


def test_duplicate_observation_fails_explicitly(tmp_path: Path) -> None:
    manifest, artifact = _sandbox(tmp_path)
    content = artifact.read_bytes().replace(b"2015-01-05", b"2015-01-02", 1)
    artifact.write_bytes(content)
    _refresh_artifact_identity(manifest, artifact)
    with pytest.raises(FrozenSnapshotError, match="duplicate"):
        load_frozen_fx_snapshot(manifest, repository_root=tmp_path)


def test_empty_effective_window_fails_explicitly() -> None:
    with pytest.raises(FrozenSnapshotError, match="empty observation window"):
        load_frozen_fx_snapshot(repository_root=REPOSITORY_ROOT, as_of="2014-12-31")


def test_loader_has_no_network_or_fallback_path(monkeypatch: pytest.MonkeyPatch) -> None:
    def deny_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket, "create_connection", deny_network)
    snapshot = load_frozen_fx_snapshot(repository_root=REPOSITORY_ROOT)
    assert snapshot.observation_count == 11_940
