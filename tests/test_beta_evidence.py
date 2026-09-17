from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from qhapaq_finance.beta_evidence import (
    BetaEvidenceError,
    CachedPriceSeries,
    PriceObservation,
    cache_price_series,
    canonical_beta_evidence,
    load_cached_price_series,
)


def _period(index: int) -> date:
    return date(2020 + index // 12, index % 12 + 1, 1)


def _series(
    security_id: str, returns: list[float], *, offset: int = 0
) -> CachedPriceSeries:
    price = 100.0
    observations = [PriceObservation(_period(offset), price)]
    for index, periodic_return in enumerate(returns, start=1):
        price *= 1 + periodic_return
        observations.append(PriceObservation(_period(index + offset), price))
    return CachedPriceSeries(
        security_id=security_id,
        ticker="^GSPC" if security_id == "benchmark:^GSPC" else "ABC",
        frequency="monthly",
        price_adjustment="adjusted_close",
        observations=tuple(observations),
        source_manifest_identity=f"manifest:{security_id}",
        source_checksum=f"checksum:{security_id}",
    )


def test_aligned_monthly_series_calculates_known_beta_and_retains_lineage() -> None:
    benchmark_returns = [0.01 + index / 10_000 for index in range(40)]
    security = _series("issuer:ABC", [0.002 + 2 * value for value in benchmark_returns])
    benchmark = _series("benchmark:^GSPC", benchmark_returns)

    evidence = canonical_beta_evidence(security=security, benchmark=benchmark)

    assert evidence.value == pytest.approx(2.0)
    assert evidence.benchmark == "benchmark:^GSPC"
    assert evidence.return_frequency == "monthly"
    assert evidence.aligned_observation_count == 40
    assert evidence.source_evidence_identities == (
        "manifest:issuer:ABC",
        "checksum:issuer:ABC",
        "manifest:benchmark:^GSPC",
        "checksum:benchmark:^GSPC",
    )
    assert evidence.identity == evidence.calculation_identity
    assert evidence.as_capital_cost_evidence().methodology == "deterministic_regression"


def test_identical_returns_calculate_beta_one() -> None:
    returns = [0.01 + index / 10_000 for index in range(40)]

    assert canonical_beta_evidence(
        security=_series("issuer:ABC", returns),
        benchmark=_series("benchmark:^GSPC", returns),
    ).value == pytest.approx(1.0)


def test_insufficient_aligned_returns_fail_closed() -> None:
    returns = [0.01 + index / 10_000 for index in range(35)]

    with pytest.raises(BetaEvidenceError, match="BETA_INSUFFICIENT_OBSERVATIONS"):
        canonical_beta_evidence(
            security=_series("issuer:ABC", returns),
            benchmark=_series("benchmark:^GSPC", returns),
        )


def test_non_overlapping_periods_fail_closed() -> None:
    returns = [0.01 + index / 10_000 for index in range(40)]

    with pytest.raises(BetaEvidenceError, match="BETA_NO_OVERLAPPING_PERIODS"):
        canonical_beta_evidence(
            security=_series("issuer:ABC", returns),
            benchmark=_series("benchmark:^GSPC", returns, offset=60),
        )


def test_zero_benchmark_variance_fails_closed() -> None:
    with pytest.raises(BetaEvidenceError, match="BETA_BENCHMARK_VARIANCE_ZERO"):
        canonical_beta_evidence(
            security=_series("issuer:ABC", [0.01] * 40),
            benchmark=_series("benchmark:^GSPC", [0.0] * 40),
        )


def test_non_finite_and_duplicate_observations_fail_closed() -> None:
    with pytest.raises(BetaEvidenceError, match="BETA_PRICE_INVALID"):
        PriceObservation(_period(0), float("nan"))
    with pytest.raises(BetaEvidenceError, match="BETA_PERIOD_DUPLICATE"):
        CachedPriceSeries(
            security_id="issuer:ABC",
            ticker="ABC",
            frequency="monthly",
            price_adjustment="adjusted_close",
            observations=(PriceObservation(_period(0), 100), PriceObservation(_period(0), 101)),
            source_manifest_identity="manifest:issuer:ABC",
            source_checksum="checksum:issuer:ABC",
        )
    with pytest.raises(BetaEvidenceError, match="BETA_RETURN_INVALID"):
        canonical_beta_evidence(
            security=CachedPriceSeries(
                "issuer:ABC",
                "ABC",
                "monthly",
                "adjusted_close",
                (PriceObservation(_period(0), 1e-308), PriceObservation(_period(1), 1e308)),
                "manifest:issuer:ABC",
                "checksum:issuer:ABC",
            ),
            benchmark=_series("benchmark:^GSPC", [0.01 + index / 10_000 for index in range(40)]),
        )


def test_replay_is_deterministic() -> None:
    returns = [0.01 + index / 10_000 for index in range(40)]
    security = _series("issuer:ABC", returns)
    benchmark = _series("benchmark:^GSPC", returns)

    first = canonical_beta_evidence(security=security, benchmark=benchmark)
    second = canonical_beta_evidence(security=security, benchmark=benchmark)

    assert first == second
    assert first.identity == second.calculation_identity


def test_checksum_verified_cache_round_trip_retains_source_provenance(tmp_path: Path) -> None:
    returns = [0.01 + index / 10_000 for index in range(40)]
    security_manifest = cache_price_series(root=tmp_path, series=_series("issuer:ABC", returns))
    benchmark_manifest = cache_price_series(
        root=tmp_path, series=_series("benchmark:^GSPC", returns)
    )

    evidence = canonical_beta_evidence(
        security=load_cached_price_series(root=tmp_path, manifest_path=security_manifest),
        benchmark=load_cached_price_series(root=tmp_path, manifest_path=benchmark_manifest),
    )

    assert evidence.value == pytest.approx(1.0)
    assert len(evidence.source_evidence_identities) == 4
    assert all(evidence.source_evidence_identities)

    raw = security_manifest.with_name("history-monthly.json")
    raw.write_text("{}", encoding="utf-8")
    with pytest.raises(BetaEvidenceError, match="BETA_SOURCE_INVALID"):
        load_cached_price_series(root=tmp_path, manifest_path=security_manifest)
