import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import pandas as pd

FROZEN_ECB_FX_MANIFEST = Path(
    "data/frozen/ecb/exr_daily_eur_reference_rates_2015-01-01_2026-08-31.manifest.json"
)


class FrozenSnapshotError(ValueError):
    """Raised when a frozen dataset does not match its declared evidence."""


@dataclass(frozen=True)
class FrozenFxSnapshot:
    """Checksum-validated, point-in-time ECB FX observations and metadata."""

    dataset_id: str
    data_sha256: str
    manifest_sha256: str
    requested_start: date
    requested_end: date
    actual_start: date
    actual_end: date
    effective_as_of: date
    series_ids: tuple[str, ...]
    primary_series: str
    quote_convention: str
    attribution: str
    observations: pd.DataFrame

    @property
    def observation_count(self) -> int:
        return len(self.observations)

    @property
    def price_panel(self) -> pd.DataFrame:
        """Return observations as a date-by-currency panel for downstream research."""
        return self.observations.pivot(index="observation_date", columns="currency", values="value")


def file_sha256(path: str | Path) -> str:
    """Return the SHA-256 identity of an artifact's exact bytes."""
    digest = sha256()
    with Path(path).open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FrozenSnapshotError(f"manifest field {field!r} must be an object")
    return value


def _require_string(mapping: dict[str, Any], field: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value:
        raise FrozenSnapshotError(f"manifest field {field!r} must be a non-empty string")
    return value


def _iso_date(value: Any, field: str) -> date:
    if not isinstance(value, str):
        raise FrozenSnapshotError(f"{field} must be an ISO date")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise FrozenSnapshotError(f"{field} must be a valid ISO date") from exc
    if parsed.isoformat() != value:
        raise FrozenSnapshotError(f"{field} must use YYYY-MM-DD")
    return parsed


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"frozen ECB manifest not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FrozenSnapshotError(f"invalid frozen ECB manifest: {path}") from exc
    manifest = _require_mapping(payload, "root")
    required = {
        "actual_window",
        "artifact",
        "dataset_id",
        "frequency",
        "observation_count",
        "primary_series",
        "provenance",
        "quote_convention",
        "requested_window",
        "schema_version",
        "series",
    }
    missing = required - manifest.keys()
    if missing:
        raise FrozenSnapshotError(f"manifest is missing required fields: {sorted(missing)}")
    if manifest["schema_version"] != "1.0":
        raise FrozenSnapshotError("unsupported frozen ECB manifest schema_version")
    return manifest


def _resolve_artifact(repository_root: Path, manifest: dict[str, Any]) -> tuple[Path, str, int]:
    artifact = _require_mapping(manifest["artifact"], "artifact")
    relative = Path(_require_string(artifact, "path"))
    if relative.is_absolute() or ".." in relative.parts:
        raise FrozenSnapshotError("artifact path must be repository-relative and cannot traverse")
    artifact_path = repository_root / relative
    if not artifact_path.is_file():
        raise FileNotFoundError(f"frozen ECB artifact not found: {artifact_path}")
    expected_bytes = artifact.get("byte_count")
    if (
        not isinstance(expected_bytes, int)
        or isinstance(expected_bytes, bool)
        or expected_bytes < 1
    ):
        raise FrozenSnapshotError("artifact byte_count must be a positive integer")
    if artifact_path.stat().st_size != expected_bytes:
        raise FrozenSnapshotError("frozen ECB artifact byte count does not match manifest")
    expected_sha = _require_string(artifact, "sha256")
    if len(expected_sha) != 64 or any(
        character not in "0123456789abcdef" for character in expected_sha
    ):
        raise FrozenSnapshotError("artifact sha256 must be a lowercase SHA-256 digest")
    if file_sha256(artifact_path) != expected_sha:
        raise FrozenSnapshotError("frozen ECB artifact checksum does not match manifest")
    if artifact.get("source_bytes") != "unmodified":
        raise FrozenSnapshotError("manifest must declare source_bytes as unmodified")
    return artifact_path, expected_sha, expected_bytes


def _declared_series(manifest: dict[str, Any]) -> tuple[tuple[str, ...], dict[str, int]]:
    raw_series = manifest["series"]
    if not isinstance(raw_series, list) or not raw_series:
        raise FrozenSnapshotError("manifest series must be a non-empty array")
    identifiers: list[str] = []
    counts: dict[str, int] = {}
    for position, raw in enumerate(raw_series):
        item = _require_mapping(raw, f"series[{position}]")
        series_id = _require_string(item, "series_id")
        currency = _require_string(item, "currency")
        count = item.get("observation_count")
        if series_id != f"D.{currency}.EUR.SP00.A":
            raise FrozenSnapshotError(f"series {series_id!r} has inconsistent ECB dimensions")
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise FrozenSnapshotError(f"series {series_id!r} has invalid observation_count")
        if series_id in counts:
            raise FrozenSnapshotError(f"duplicate manifest series: {series_id}")
        identifiers.append(series_id)
        counts[series_id] = count
    if identifiers != sorted(identifiers):
        raise FrozenSnapshotError("manifest series must be sorted by series_id")
    return tuple(identifiers), counts


def load_frozen_fx_snapshot(
    manifest_path: str | Path = FROZEN_ECB_FX_MANIFEST,
    *,
    repository_root: str | Path = ".",
    as_of: str | date | None = None,
) -> FrozenFxSnapshot:
    """Load the byte-verified ECB snapshot without network access or fallback data."""
    root = Path(repository_root).resolve()
    manifest_file = Path(manifest_path)
    if not manifest_file.is_absolute():
        manifest_file = root / manifest_file
    manifest = _load_manifest(manifest_file)
    artifact_path, data_sha, _ = _resolve_artifact(root, manifest)
    series_ids, declared_counts = _declared_series(manifest)

    requested = _require_mapping(manifest["requested_window"], "requested_window")
    actual = _require_mapping(manifest["actual_window"], "actual_window")
    requested_start = _iso_date(requested.get("start"), "requested_window.start")
    requested_end = _iso_date(requested.get("end"), "requested_window.end")
    actual_start = _iso_date(actual.get("start"), "actual_window.start")
    actual_end = _iso_date(actual.get("end"), "actual_window.end")
    if not requested_start <= actual_start <= actual_end <= requested_end:
        raise FrozenSnapshotError("actual observation window is outside the requested window")

    quote = _require_mapping(manifest["quote_convention"], "quote_convention")
    if quote.get("base_currency") != "EUR":
        raise FrozenSnapshotError("quote convention must declare EUR as base_currency")
    description = _require_string(quote, "description")
    provenance = _require_mapping(manifest["provenance"], "provenance")
    attribution = _require_string(provenance, "attribution")

    required_columns = {
        "KEY",
        "FREQ",
        "CURRENCY",
        "CURRENCY_DENOM",
        "EXR_TYPE",
        "EXR_SUFFIX",
        "TIME_PERIOD",
        "OBS_VALUE",
    }
    try:
        raw = pd.read_csv(artifact_path, dtype=str, keep_default_na=False)
    except (UnicodeDecodeError, pd.errors.ParserError) as exc:
        raise FrozenSnapshotError("frozen ECB artifact is not valid CSV") from exc
    if not required_columns <= set(raw.columns):
        raise FrozenSnapshotError("frozen ECB artifact is missing required columns")
    raw["series_id"] = raw["KEY"].str.removeprefix("EXR.")
    if set(raw["series_id"]) != set(series_ids):
        raise FrozenSnapshotError("artifact series do not exactly match the manifest")
    dimension_ok = (
        raw["KEY"].eq("EXR." + raw["series_id"])
        & raw["FREQ"].eq("D")
        & raw["CURRENCY_DENOM"].eq("EUR")
        & raw["EXR_TYPE"].eq("SP00")
        & raw["EXR_SUFFIX"].eq("A")
        & raw["series_id"].eq("D." + raw["CURRENCY"] + ".EUR.SP00.A")
    )
    if not dimension_ok.all():
        raise FrozenSnapshotError("artifact contains inconsistent ECB series dimensions")

    try:
        parsed_dates = raw["TIME_PERIOD"].map(
            lambda value: datetime.strptime(value, "%Y-%m-%d").date()
        )
        values = raw["OBS_VALUE"].map(float)
    except ValueError as exc:
        raise FrozenSnapshotError("artifact contains malformed dates or numeric values") from exc
    if any(
        parsed.isoformat() != source
        for parsed, source in zip(parsed_dates, raw["TIME_PERIOD"], strict=True)
    ):
        raise FrozenSnapshotError("artifact dates must use strict YYYY-MM-DD format")
    if not values.map(lambda value: math.isfinite(value) and value > 0).all():
        raise FrozenSnapshotError("artifact values must be finite and positive")
    if (
        raw.assign(observation_date=parsed_dates)
        .duplicated(["series_id", "observation_date"])
        .any()
    ):
        raise FrozenSnapshotError("artifact contains duplicate series/date observations")
    if min(parsed_dates) != actual_start or max(parsed_dates) != actual_end:
        raise FrozenSnapshotError("artifact observation window does not match manifest")
    if any(value < requested_start or value > requested_end for value in parsed_dates):
        raise FrozenSnapshotError("artifact contains observations outside the requested window")
    actual_counts = raw.groupby("series_id", sort=True).size().to_dict()
    if actual_counts != declared_counts or len(raw) != manifest.get("observation_count"):
        raise FrozenSnapshotError("artifact observation counts do not match manifest")

    effective_as_of = (
        actual_end
        if as_of is None
        else _iso_date(as_of, "as_of")
        if isinstance(as_of, str)
        else as_of
    )
    if not isinstance(effective_as_of, date):
        raise FrozenSnapshotError("as_of must be an ISO date or date")
    observations = pd.DataFrame(
        {
            "series_id": raw["series_id"],
            "currency": raw["CURRENCY"],
            "observation_date": parsed_dates,
            "value": values.astype(float),
        }
    )
    observations = observations.loc[observations["observation_date"] <= effective_as_of]
    observations = observations.sort_values(
        ["series_id", "observation_date"], kind="stable"
    ).reset_index(drop=True)
    if observations.empty:
        raise FrozenSnapshotError("effective as_of produces an empty observation window")
    primary = _require_string(manifest, "primary_series")
    if primary not in series_ids:
        raise FrozenSnapshotError("primary_series must be one of the declared series")
    return FrozenFxSnapshot(
        dataset_id=_require_string(manifest, "dataset_id"),
        data_sha256=data_sha,
        manifest_sha256=file_sha256(manifest_file),
        requested_start=requested_start,
        requested_end=requested_end,
        actual_start=actual_start,
        actual_end=actual_end,
        effective_as_of=effective_as_of,
        series_ids=series_ids,
        primary_series=primary,
        quote_convention=description,
        attribution=attribution,
        observations=observations,
    )


def validate_prices(prices: pd.DataFrame) -> pd.DataFrame:
    """Return a clean price panel without silently filling missing observations."""
    if not isinstance(prices.index, pd.DatetimeIndex):
        raise TypeError("prices must use a DatetimeIndex")
    if prices.empty or prices.shape[1] < 2:
        raise ValueError("prices must contain at least two assets")
    if prices.index.has_duplicates or not prices.index.is_monotonic_increasing:
        raise ValueError("price index must be unique and increasing")
    clean = prices.astype(float).dropna(how="all")
    if (clean <= 0).any().any():
        raise ValueError("prices must be positive")
    return clean


def download_adjusted_close(
    tickers: Iterable[str], start: str, end: str | None = None
) -> pd.DataFrame:
    """Download adjusted prices. Network data is deliberately isolated here."""
    try:
        # yfinance does not publish typing metadata.
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("Install Qhapaq Finance with the 'data' extra") from exc

    symbols = list(dict.fromkeys(tickers))
    if len(symbols) < 2:
        raise ValueError("provide at least two unique tickers")
    raw = yf.download(symbols, start=start, end=end, auto_adjust=True, progress=False)
    if raw.empty:
        raise RuntimeError("the data provider returned no observations")
    close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
    close.columns = symbols if len(symbols) == close.shape[1] else close.columns
    return validate_prices(close)
