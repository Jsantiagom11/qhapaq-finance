"""Deterministic research tear sheet for the verified frozen ECB FX snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.dates import AutoDateLocator, ConciseDateFormatter
from matplotlib.figure import Figure
from matplotlib.ticker import PercentFormatter

from .data import FROZEN_ECB_FX_MANIFEST, FrozenFxSnapshot, load_frozen_fx_snapshot

WIDTH = 2400
HEIGHT = 1350
DPI = 120
PRIMARY_SERIES = "D.USD.EUR.SP00.A"
INSTRUMENT_LABEL = "EUR/USD ECB reference rate — USD per EUR"
PANELS = (
    "Indexed spot-rate performance (start = 100)",
    "Drawdown",
    "Rolling 63-observation annualized volatility",
    "Daily log-return distribution",
)


@dataclass(frozen=True)
class TearSheetKpi:
    label: str
    value: float
    display: str


@dataclass(frozen=True)
class TearSheetModel:
    snapshot: FrozenFxSnapshot
    instrument_label: str
    unit_label: str
    kpis: tuple[TearSheetKpi, ...]
    panels: tuple[str, ...]
    provenance: tuple[str, ...]
    rates: pd.Series
    log_returns: pd.Series
    indexed_spot: pd.Series
    drawdown: pd.Series
    rolling_volatility: pd.Series


def _repository_root(manifest_path: Path) -> Path:
    resolved = manifest_path.resolve()
    expected_parts = FROZEN_ECB_FX_MANIFEST.parts
    if tuple(resolved.parts[-len(expected_parts) :]) != expected_parts:
        raise ValueError("manifest must use the repository frozen ECB path")
    return resolved.parents[len(expected_parts) - 1]


def _source_path_for_manifest(manifest_path: Path) -> Path:
    suffix = ".manifest.json"
    if not manifest_path.name.endswith(suffix):
        raise ValueError("manifest filename must end with .manifest.json")
    return manifest_path.with_name(manifest_path.name.removesuffix(suffix) + ".csv")


def build_tearsheet_model(
    *, data_path: Path, manifest_path: Path, as_of: date | None = None
) -> TearSheetModel:
    """Build validated calculations and labels without rendering pixels."""
    data_file = data_path.resolve()
    manifest_file = manifest_path.resolve()
    if data_file != _source_path_for_manifest(manifest_file):
        raise ValueError("data_path must be the artifact adjacent to the supplied manifest")
    snapshot = load_frozen_fx_snapshot(
        manifest_file,
        repository_root=_repository_root(manifest_file),
        as_of=as_of,
    )
    if snapshot.primary_series != PRIMARY_SERIES:
        raise ValueError(f"expected primary series {PRIMARY_SERIES}")
    selected = snapshot.observations.loc[
        snapshot.observations["series_id"] == snapshot.primary_series
    ]
    rates = pd.Series(
        selected["value"].to_numpy(dtype=float),
        index=pd.DatetimeIndex(selected["observation_date"]),
        name="USD per EUR",
    )
    if len(rates) < 64:
        raise ValueError("primary series requires at least 64 observations")
    log_returns = rates.map(np.log).diff().dropna()
    indexed = rates / rates.iloc[0] * 100.0
    drawdown = rates / rates.cummax() - 1.0
    rolling_volatility = log_returns.rolling(63).std(ddof=1) * np.sqrt(252)
    spot_return = float(rates.iloc[-1] / rates.iloc[0] - 1.0)
    annualized_volatility = float(log_returns.std(ddof=1) * np.sqrt(252))
    maximum_drawdown = float(drawdown.min())
    latest_rate = float(rates.iloc[-1])
    kpis = (
        TearSheetKpi("Spot return (ex-carry)", spot_return, f"{spot_return:+.1%}"),
        TearSheetKpi(
            "Annualized volatility (252 obs/year)",
            annualized_volatility,
            f"{annualized_volatility:.1%}",
        ),
        TearSheetKpi("Maximum drawdown", maximum_drawdown, f"{maximum_drawdown:.1%}"),
        TearSheetKpi("Latest ECB rate", latest_rate, f"{latest_rate:.4f} USD per EUR"),
    )
    provenance = (
        data_file.name,
        snapshot.data_sha256,
        snapshot.manifest_sha256,
        snapshot.effective_as_of.isoformat(),
        f"{rates.index[0].date().isoformat()} to {rates.index[-1].date().isoformat()}",
        "Source: ECB statistics.",
        "Research only — not investment advice",
    )
    return TearSheetModel(
        snapshot=snapshot,
        instrument_label=INSTRUMENT_LABEL,
        unit_label="USD per EUR",
        kpis=kpis,
        panels=PANELS,
        provenance=provenance,
        rates=rates,
        log_returns=log_returns,
        indexed_spot=indexed,
        drawdown=drawdown,
        rolling_volatility=rolling_volatility,
    )


def _style_axis(axis: Any, title: str) -> None:
    axis.set_facecolor("#0B1220")
    axis.set_title(title, loc="left", color="#F4F7FB", fontsize=12, weight="bold", pad=12)
    axis.tick_params(colors="#9FB0C5", labelsize=8)
    axis.grid(color="#26364D", linewidth=0.7, alpha=0.55)
    for spine in axis.spines.values():
        spine.set_color("#26364D")
    locator = AutoDateLocator(minticks=4, maxticks=8)
    axis.xaxis.set_major_locator(locator)
    axis.xaxis.set_major_formatter(ConciseDateFormatter(locator))


def _figure(model: TearSheetModel) -> Figure:
    background = "#08111F"
    card = "#101D2F"
    text = "#F4F7FB"
    muted = "#9FB0C5"
    cyan = "#35C2E8"
    amber = "#F2A93B"
    with matplotlib.rc_context(
        {
            "font.family": "DejaVu Sans",
            "figure.facecolor": background,
            "savefig.facecolor": background,
            "axes.unicode_minus": True,
            "pdf.use14corefonts": False,
        }
    ):
        figure = Figure(figsize=(WIDTH / DPI, HEIGHT / DPI), dpi=DPI, facecolor=background)
        FigureCanvasAgg(figure)
        grid = figure.add_gridspec(
            18, 24, left=0.045, right=0.965, top=0.94, bottom=0.14, hspace=2.0, wspace=1.5
        )
        figure.text(0.045, 0.965, "Qhapaq Finance", color=text, fontsize=22, weight="bold")
        figure.text(0.205, 0.965, "Research Tear Sheet", color=cyan, fontsize=13, weight="bold")
        figure.text(0.045, 0.927, "EUR/USD ECB reference rate", color=text, fontsize=14)
        figure.text(0.045, 0.904, "USD per EUR", color=muted, fontsize=9)
        snapshot = model.snapshot
        header_detail = (
            f"Effective as-of {snapshot.effective_as_of.isoformat()}  ·  Actual window "
            f"{snapshot.actual_start.isoformat()} — {snapshot.actual_end.isoformat()}  ·  "
            f"{snapshot.observation_count:,} validated observations (all series)"
        )
        figure.text(0.965, 0.927, header_detail, color=muted, fontsize=8.5, ha="right")

        for index, kpi in enumerate(model.kpis):
            start = index * 6
            axis = figure.add_subplot(grid[1:4, start : start + 5])
            axis.set_facecolor(card)
            axis.set_xticks([])
            axis.set_yticks([])
            for spine in axis.spines.values():
                spine.set_color("#26364D")
            axis.text(0.06, 0.75, kpi.label, color=muted, fontsize=8.5, weight="bold")
            axis.text(0.06, 0.34, kpi.display, color=text, fontsize=19, weight="bold")

        spot_axis = figure.add_subplot(grid[5:11, 0:15])
        _style_axis(spot_axis, model.panels[0])
        spot_axis.plot(model.indexed_spot.index, model.indexed_spot, color=cyan, linewidth=1.8)
        spot_axis.axhline(100, color=muted, linewidth=0.8, alpha=0.65)
        spot_axis.set_ylabel("Index level", color=muted, fontsize=8)
        spot_axis.set_ylim(bottom=min(95.0, float(model.indexed_spot.min()) * 0.97))

        drawdown_axis = figure.add_subplot(grid[12:17, 0:15])
        _style_axis(drawdown_axis, model.panels[1])
        drawdown_axis.fill_between(
            model.drawdown.index, model.drawdown, 0, color=amber, alpha=0.42, linewidth=0
        )
        drawdown_axis.plot(model.drawdown.index, model.drawdown, color=amber, linewidth=1.2)
        drawdown_axis.axhline(0, color=muted, linewidth=0.8)
        drawdown_axis.set_ylim(min(-0.01, float(model.drawdown.min()) * 1.08), 0.002)
        drawdown_axis.yaxis.set_major_formatter(PercentFormatter(1))

        volatility_axis = figure.add_subplot(grid[5:11, 16:24])
        _style_axis(volatility_axis, model.panels[2])
        volatility_axis.plot(
            model.rolling_volatility.index,
            model.rolling_volatility,
            color=cyan,
            linewidth=1.4,
        )
        volatility_axis.yaxis.set_major_formatter(PercentFormatter(1))
        volatility_axis.set_ylabel("Annualized volatility", color=muted, fontsize=8)

        histogram_axis = figure.add_subplot(grid[12:17, 16:24])
        histogram_axis.set_facecolor("#0B1220")
        histogram_axis.set_title(
            model.panels[3], loc="left", color=text, fontsize=12, weight="bold", pad=12
        )
        histogram_axis.hist(
            model.log_returns,
            bins=32,
            color=cyan,
            edgecolor=background,
            linewidth=0.5,
            alpha=0.85,
        )
        histogram_axis.axvline(0, color=amber, linewidth=1.0)
        histogram_axis.xaxis.set_major_formatter(PercentFormatter(1))
        histogram_axis.tick_params(colors=muted, labelsize=8)
        histogram_axis.grid(axis="y", color="#26364D", linewidth=0.7, alpha=0.55)
        histogram_axis.set_xlabel("Daily log return", color=muted, fontsize=8)
        histogram_axis.set_ylabel("Observations", color=muted, fontsize=8)
        for spine in histogram_axis.spines.values():
            spine.set_color("#26364D")

        source_name, data_sha, manifest_sha, effective, window, attribution, disclaimer = (
            model.provenance
        )
        figure.text(0.045, 0.09, f"Artifact: {source_name}", color=muted, fontsize=7.5)
        figure.text(0.045, 0.07, f"Artifact SHA-256: {data_sha}", color=muted, fontsize=7.5)
        figure.text(0.045, 0.05, f"Manifest SHA-256: {manifest_sha}", color=muted, fontsize=7.5)
        figure.text(
            0.965,
            0.09,
            f"Effective as-of: {effective}  ·  Analysis window: {window}",
            color=muted,
            fontsize=7.5,
            ha="right",
        )
        figure.text(0.965, 0.07, attribution, color=text, fontsize=8, ha="right", weight="bold")
        figure.text(0.965, 0.05, disclaimer, color=amber, fontsize=8, ha="right", weight="bold")
        return figure


def png_dimensions(path: Path) -> tuple[int, int]:
    """Read PNG dimensions from the validated signature and IHDR chunk."""
    header = path.read_bytes()[:24]
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ValueError("output is not a valid PNG")
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


def render_tearsheet(
    *,
    data_path: Path,
    manifest_path: Path,
    output_path: Path,
    as_of: date | None = None,
) -> Path:
    """Render the verified ECB tear sheet and validate its exact canvas dimensions."""
    source = data_path.resolve()
    manifest = manifest_path.resolve()
    output = output_path.resolve()
    if output in {source, manifest}:
        raise ValueError("output_path cannot overwrite the source CSV or manifest")
    model = build_tearsheet_model(data_path=source, manifest_path=manifest, as_of=as_of)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure = _figure(model)
    try:
        figure.savefig(
            output,
            format="png",
            dpi=DPI,
            metadata={
                "Software": "Qhapaq Finance",
                "Title": "Verified ECB FX Research Tear Sheet",
                "Description": "Deterministic analysis of a byte-frozen ECB reference-rate series",
            },
        )
    finally:
        figure.clear()
    if png_dimensions(output) != (WIDTH, HEIGHT):
        raise ValueError(f"rendered PNG must be {WIDTH} x {HEIGHT} pixels")
    return output
