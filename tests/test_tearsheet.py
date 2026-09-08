import json
import os
import shutil
import socket
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from qhapaq_finance.data import FROZEN_ECB_FX_MANIFEST, FrozenSnapshotError, file_sha256
from qhapaq_finance.tearsheet import (
    HEIGHT,
    PANELS,
    WIDTH,
    build_tearsheet_model,
    png_dimensions,
    render_tearsheet,
)

ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / FROZEN_ECB_FX_MANIFEST
DATA = MANIFEST.with_name(MANIFEST.name.removesuffix(".manifest.json") + ".csv")


def _render(output: Path, *, as_of: date | None = None) -> Path:
    return render_tearsheet(data_path=DATA, manifest_path=MANIFEST, output_path=output, as_of=as_of)


def _snapshot_copy(tmp_path: Path) -> tuple[Path, Path]:
    manifest = tmp_path / FROZEN_ECB_FX_MANIFEST
    data = manifest.with_name(manifest.name.removesuffix(".manifest.json") + ".csv")
    manifest.parent.mkdir(parents=True)
    shutil.copy2(MANIFEST, manifest)
    shutil.copy2(DATA, data)
    return data, manifest


def test_real_snapshot_renders_valid_exact_canvas(tmp_path: Path) -> None:
    output = _render(tmp_path / "tear-sheet.png")
    assert output.stat().st_size > 100_000
    assert output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert png_dimensions(output) == (WIDTH, HEIGHT) == (2400, 1350)


def test_repeated_renders_have_identical_sha256(tmp_path: Path) -> None:
    first = _render(tmp_path / "first.png")
    second = _render(tmp_path / "second.png")
    assert file_sha256(first) == file_sha256(second)


def test_typed_model_contains_required_sections_and_provenance() -> None:
    model = build_tearsheet_model(data_path=DATA, manifest_path=MANIFEST)
    assert tuple(kpi.label for kpi in model.kpis) == (
        "Spot return (ex-carry)",
        "Annualized volatility (252 obs/year)",
        "Maximum drawdown",
        "Latest ECB rate",
    )
    assert model.panels == PANELS
    assert model.provenance[1] == "9233e2547b72171b8b007e1056e09482e360a765b843330532b2a0e9a05a199e"
    assert model.provenance[2] == "424e1e1e034a25bc141933cbe7c356b0a18057469ca3b46da22bee2a98720dc4"
    assert "Source: ECB statistics." in model.provenance
    assert model.indexed_spot.iloc[0] == pytest.approx(100.0)
    assert model.drawdown.max() == pytest.approx(0.0)


def test_quote_direction_and_financial_assumptions_are_explicit() -> None:
    model = build_tearsheet_model(data_path=DATA, manifest_path=MANIFEST)
    spot_return, annualized_volatility, maximum_drawdown, latest_rate = model.kpis

    assert model.snapshot.quote_convention == "Units of each quoted currency per one euro"
    assert model.instrument_label == "EUR/USD ECB reference rate — USD per EUR"
    assert model.unit_label == "USD per EUR"
    assert spot_return.label == "Spot return (ex-carry)"
    assert spot_return.value == pytest.approx(model.rates.iloc[-1] / model.rates.iloc[0] - 1.0)
    assert annualized_volatility.value == pytest.approx(model.log_returns.std(ddof=1) * 252**0.5)
    assert maximum_drawdown.value == pytest.approx((model.rates / model.rates.cummax() - 1).min())
    assert latest_rate.value == pytest.approx(model.rates.iloc[-1])
    assert model.rolling_volatility.first_valid_index() == model.log_returns.index[62]


def test_explicit_as_of_excludes_later_observations(tmp_path: Path) -> None:
    model = build_tearsheet_model(data_path=DATA, manifest_path=MANIFEST, as_of=date(2020, 12, 31))
    assert model.rates.index[-1].date() <= date(2020, 12, 31)
    output = _render(tmp_path / "as-of.png", as_of=date(2020, 12, 31))
    assert png_dimensions(output) == (2400, 1350)


def test_insufficient_point_in_time_window_fails_explicitly() -> None:
    with pytest.raises(ValueError, match="at least 64 observations"):
        build_tearsheet_model(data_path=DATA, manifest_path=MANIFEST, as_of=date(2015, 1, 5))


def test_invalid_manifest_fails_explicitly(tmp_path: Path) -> None:
    data, manifest = _snapshot_copy(tmp_path)
    manifest.write_text("{}\n", encoding="utf-8")
    with pytest.raises(FrozenSnapshotError, match="missing required fields"):
        render_tearsheet(data_path=data, manifest_path=manifest, output_path=tmp_path / "x.png")


def test_checksum_mismatch_fails_explicitly(tmp_path: Path) -> None:
    data, manifest = _snapshot_copy(tmp_path)
    data.write_bytes(data.read_bytes().replace(b"1.2022", b"1.2023", 1))
    with pytest.raises(FrozenSnapshotError, match="checksum"):
        render_tearsheet(data_path=data, manifest_path=manifest, output_path=tmp_path / "x.png")


def test_cli_success_writes_requested_file(tmp_path: Path) -> None:
    output = tmp_path / "cli.png"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "qhapaq_finance.cli",
            "tearsheet",
            "--data",
            str(DATA),
            "--manifest",
            str(MANIFEST),
            "--output",
            str(output),
            "--as-of",
            "2026-08-31",
        ],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "MPLCONFIGDIR": str(tmp_path / "mpl")},
    )
    assert output.is_file()
    assert "dimensions=2400x1350" in result.stdout
    assert f"png_sha256={file_sha256(output)}" in result.stdout


def test_cli_invalid_input_returns_nonzero(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "qhapaq_finance.cli",
            "tearsheet",
            "--data",
            str(tmp_path / "missing.csv"),
            "--manifest",
            str(MANIFEST),
            "--output",
            str(tmp_path / "x.png"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert not (tmp_path / "x.png").exists()


@pytest.mark.parametrize("protected", [DATA, MANIFEST])
def test_source_or_manifest_overwrite_is_rejected(protected: Path) -> None:
    with pytest.raises(ValueError, match="cannot overwrite"):
        render_tearsheet(data_path=DATA, manifest_path=MANIFEST, output_path=protected)


def test_no_network_random_or_synthetic_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    def deny_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket, "create_connection", deny_network)
    model = build_tearsheet_model(data_path=DATA, manifest_path=MANIFEST)
    assert model.snapshot.primary_series == "D.USD.EUR.SP00.A"
    assert not any("synthetic" in value.lower() for value in model.provenance)


def test_manifest_is_unchanged_by_render(tmp_path: Path) -> None:
    before = json.loads(MANIFEST.read_text(encoding="utf-8"))
    _render(tmp_path / "immutable.png")
    assert json.loads(MANIFEST.read_text(encoding="utf-8")) == before
