"""Reproducible canonical beta evidence from cached adjusted price series."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from .capital_cost import BetaEvidence
from .evidence_quality import content_identity


class BetaEvidenceError(ValueError):
    """Cached price evidence cannot support a reproducible beta."""


@dataclass(frozen=True)
class BetaMethodology:
    version: str = "beta_methodology_v1"
    benchmark: str = "^GSPC"
    horizon_years: int = 5
    frequency: str = "monthly"
    price_adjustment: str = "adjusted_close"
    return_method: str = "simple_periodic"
    minimum_aligned_returns: int = 36


BETA_METHODOLOGY_V1 = BetaMethodology()


@dataclass(frozen=True)
class PriceObservation:
    period: date
    adjusted_close: float

    def __post_init__(self) -> None:
        if not isinstance(self.period, date):
            raise BetaEvidenceError("BETA_PERIOD_INVALID")
        if not math.isfinite(self.adjusted_close) or self.adjusted_close <= 0:
            raise BetaEvidenceError("BETA_PRICE_INVALID")


@dataclass(frozen=True)
class CachedPriceSeries:
    security_id: str
    ticker: str
    frequency: str
    price_adjustment: str
    observations: tuple[PriceObservation, ...]
    source_manifest_identity: str
    source_checksum: str

    def __post_init__(self) -> None:
        if not self.security_id or not self.ticker or self.frequency != "monthly":
            raise BetaEvidenceError("BETA_SERIES_IDENTITY_INVALID")
        if self.price_adjustment != "adjusted_close":
            raise BetaEvidenceError("BETA_PRICE_ADJUSTMENT_INVALID")
        if not self.source_manifest_identity or not self.source_checksum:
            raise BetaEvidenceError("BETA_SOURCE_PROVENANCE_INCOMPLETE")
        periods = tuple(item.period for item in self.observations)
        if len(periods) < 2:
            raise BetaEvidenceError("BETA_SERIES_TOO_SHORT")
        if len(set(periods)) != len(periods):
            raise BetaEvidenceError("BETA_PERIOD_DUPLICATE")
        if periods != tuple(sorted(periods)):
            raise BetaEvidenceError("BETA_PERIOD_ORDER_INVALID")

    @property
    def start(self) -> date:
        return self.observations[0].period

    @property
    def end(self) -> date:
        return self.observations[-1].period


@dataclass(frozen=True)
class CanonicalBetaEvidence:
    identity: str
    calculation_identity: str
    security_id: str
    benchmark: str
    methodology_version: str
    observation_start: date
    observation_end: date
    return_frequency: str
    price_adjustment: str
    aligned_observation_count: int
    value: float
    source_evidence_identities: tuple[str, ...]

    def as_capital_cost_evidence(self) -> BetaEvidence:
        """Adapt canonical beta evidence to the established capital-cost contract."""
        return BetaEvidence(
            self.identity,
            self.security_id,
            self.value,
            self.observation_end,
            "|".join(self.source_evidence_identities),
            "calculated_from_cached_price_series",
            self.calculation_identity,
            "deterministic_regression",
            self.benchmark,
            self.observation_start,
            self.observation_end,
            self.return_frequency,
            self.price_adjustment,
        )


def _returns(series: CachedPriceSeries) -> dict[date, float]:
    result: dict[date, float] = {}
    for previous, current in zip(series.observations[:-1], series.observations[1:], strict=True):
        periodic_return = current.adjusted_close / previous.adjusted_close - 1
        if not math.isfinite(periodic_return):
            raise BetaEvidenceError("BETA_RETURN_INVALID")
        result[current.period] = periodic_return
    return result


def canonical_beta_evidence(
    *,
    security: CachedPriceSeries,
    benchmark: CachedPriceSeries,
    methodology: BetaMethodology = BETA_METHODOLOGY_V1,
) -> CanonicalBetaEvidence:
    """Calculate beta only from aligned, immutable cached adjusted-price evidence."""
    if security.frequency != methodology.frequency or benchmark.frequency != methodology.frequency:
        raise BetaEvidenceError("BETA_FREQUENCY_MISMATCH")
    if benchmark.ticker != methodology.benchmark:
        raise BetaEvidenceError("BETA_BENCHMARK_MISMATCH")
    if (
        security.price_adjustment != methodology.price_adjustment
        or benchmark.price_adjustment != methodology.price_adjustment
    ):
        raise BetaEvidenceError("BETA_PRICE_ADJUSTMENT_MISMATCH")
    security_returns, benchmark_returns = _returns(security), _returns(benchmark)
    periods = tuple(sorted(set(security_returns) & set(benchmark_returns)))
    if not periods:
        raise BetaEvidenceError("BETA_NO_OVERLAPPING_PERIODS")
    if len(periods) < methodology.minimum_aligned_returns:
        raise BetaEvidenceError("BETA_INSUFFICIENT_OBSERVATIONS")
    security_values = tuple(security_returns[item] for item in periods)
    benchmark_values = tuple(benchmark_returns[item] for item in periods)
    benchmark_mean = sum(benchmark_values) / len(benchmark_values)
    security_mean = sum(security_values) / len(security_values)
    variance = sum((item - benchmark_mean) ** 2 for item in benchmark_values)
    if not math.isfinite(variance) or variance == 0:
        raise BetaEvidenceError("BETA_BENCHMARK_VARIANCE_ZERO")
    covariance = sum(
        (security_value - security_mean) * (benchmark_value - benchmark_mean)
        for security_value, benchmark_value in zip(security_values, benchmark_values, strict=True)
    )
    value = covariance / variance
    if not math.isfinite(value):
        raise BetaEvidenceError("BETA_VALUE_INVALID")
    source_identities = (
        security.source_manifest_identity,
        security.source_checksum,
        benchmark.source_manifest_identity,
        benchmark.source_checksum,
    )
    payload = {
        "methodology_version": methodology.version,
        "security_id": security.security_id,
        "benchmark": benchmark.security_id,
        "frequency": methodology.frequency,
        "price_adjustment": methodology.price_adjustment,
        "returns": tuple(
            (period.isoformat(), security_returns[period], benchmark_returns[period])
            for period in periods
        ),
        "source_evidence_identities": source_identities,
    }
    identity = content_identity(payload)
    return CanonicalBetaEvidence(
        identity,
        identity,
        security.security_id,
        benchmark.security_id,
        methodology.version,
        periods[0],
        periods[-1],
        methodology.frequency,
        methodology.price_adjustment,
        len(periods),
        value,
        source_identities,
    )


def write_cached_price_series(series: CachedPriceSeries, path: str | Path) -> Path:
    """Freeze a canonical monthly adjusted-price series in the market cache."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "market-price-series-v1",
        "security_id": series.security_id,
        "ticker": series.ticker,
        "frequency": series.frequency,
        "price_adjustment": series.price_adjustment,
        "observations": [
            {"period": item.period.isoformat(), "adjusted_close": item.adjusted_close}
            for item in series.observations
        ],
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def cache_price_series(
    *, root: str | Path, series: CachedPriceSeries, provider: str = "yfinance"
) -> Path:
    """Bind a frozen series into the established manifest/checksum market-cache pattern."""
    root_path = Path(root)
    cache = root_path / "data/cache/market" / provider / series.security_id.replace(":", "_")
    raw = write_cached_price_series(series, cache / "history-monthly.json")
    checksum = hashlib.sha256(raw.read_bytes()).hexdigest()
    manifest = cache / "history-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "market-price-series-manifest-v1",
                "security_id": series.security_id,
                "provider": provider,
                "raw_artifact": raw.relative_to(root_path).as_posix(),
                "raw_artifact_sha256": checksum,
                "frequency": series.frequency,
                "price_adjustment": series.price_adjustment,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest


def load_cached_price_series(*, root: str | Path, manifest_path: str | Path) -> CachedPriceSeries:
    """Load one checksum-verified cached series without network access."""
    root_path = Path(root)
    try:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        raw_relative = Path(manifest["raw_artifact"])
        raw = root_path / raw_relative
        checksum = hashlib.sha256(raw.read_bytes()).hexdigest()
        payload = json.loads(raw.read_text(encoding="utf-8"))
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise BetaEvidenceError("BETA_SOURCE_INVALID") from exc
    if (
        manifest.get("schema_version") != "market-price-series-manifest-v1"
        or raw_relative.is_absolute()
        or ".." in raw_relative.parts
        or manifest.get("raw_artifact_sha256") != checksum
        or payload.get("schema_version") != "market-price-series-v1"
        or payload.get("security_id") != manifest.get("security_id")
    ):
        raise BetaEvidenceError("BETA_SOURCE_INVALID")
    try:
        observations = tuple(
            PriceObservation(date.fromisoformat(item["period"]), float(item["adjusted_close"]))
            for item in payload["observations"]
        )
        return CachedPriceSeries(
            str(payload["security_id"]),
            str(payload["ticker"]),
            str(payload["frequency"]),
            str(payload["price_adjustment"]),
            observations,
            content_identity(manifest),
            checksum,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise BetaEvidenceError("BETA_SOURCE_INVALID") from exc


def cache_yfinance_price_series(
    *, root: str | Path, security_id: str, ticker: str, now: datetime | None = None
) -> Path:
    """Explicit optional acquisition of five-year monthly adjusted price evidence."""
    del now
    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("Install Qhapaq Finance with the 'data' extra") from exc
    history = yf.Ticker(ticker).history(
        period="5y", interval="1mo", auto_adjust=True, actions=False
    )
    if history.empty or "Close" not in history:
        raise BetaEvidenceError("BETA_ACQUISITION_EMPTY")
    observations = tuple(
        PriceObservation(item.to_pydatetime().date(), float(value))
        for item, value in history["Close"].dropna().items()
    )
    series = CachedPriceSeries(
        security_id,
        ticker,
        "monthly",
        "adjusted_close",
        observations,
        f"yfinance:{security_id}:{datetime.now(timezone.utc).isoformat()}",
        "pending-write",
    )
    return cache_price_series(root=root, series=series)
