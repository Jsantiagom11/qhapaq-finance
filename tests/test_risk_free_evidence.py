from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from qhapaq_finance.risk_free_evidence import (
    RiskFreeEvidenceError,
    TreasuryObservation,
    cache_treasury_observations,
    canonical_risk_free_evidence,
    load_cached_treasury_observations,
)

NOW = datetime(2026, 9, 15, tzinfo=timezone.utc)


def _observation(day: date = date(2026, 9, 14), value: float = 4.25) -> TreasuryObservation:
    return TreasuryObservation(day, "10Y", value, "percent", NOW)


def test_canonical_treasury_rate_normalizes_and_adapts_to_capital_cost(tmp_path: Path) -> None:
    manifest = cache_treasury_observations(root=tmp_path, observations=(_observation(),))
    evidence = canonical_risk_free_evidence(
        cache=load_cached_treasury_observations(root=tmp_path, manifest_path=manifest),
        evaluation_as_of=date(2026, 9, 15),
    )

    assert evidence.value == pytest.approx(0.0425)
    assert evidence.published_value == 4.25
    assert evidence.published_unit == "percent"
    assert evidence.tenor == "10Y"
    assert evidence.as_capital_cost_evidence().metric == "risk_free_rate"
    assert evidence.source_checksum


def test_latest_observation_on_or_before_as_of_is_selected_and_replay_is_stable(
    tmp_path: Path,
) -> None:
    manifest = cache_treasury_observations(
        root=tmp_path,
        observations=(_observation(date(2026, 9, 11), 4.1), _observation(date(2026, 9, 14), 4.2)),
    )
    cache = load_cached_treasury_observations(root=tmp_path, manifest_path=manifest)

    first = canonical_risk_free_evidence(cache=cache, evaluation_as_of=date(2026, 9, 15))
    second = canonical_risk_free_evidence(cache=cache, evaluation_as_of=date(2026, 9, 15))

    assert first.observed_at == date(2026, 9, 14)
    assert first.identity == second.identity


@pytest.mark.parametrize(
    ("observations", "as_of", "error"),
    [
        (
            (_observation(date(2026, 9, 16)),),
            date(2026, 9, 15),
            "RISK_FREE_OBSERVATION_UNAVAILABLE",
        ),
        ((_observation(date(2026, 9, 1)),), date(2026, 9, 15), "RISK_FREE_STALE"),
    ],
)
def test_unacceptable_treasury_observations_fail_closed(
    tmp_path: Path, observations: tuple[TreasuryObservation, ...], as_of: date, error: str
) -> None:
    manifest = cache_treasury_observations(root=tmp_path, observations=observations)
    with pytest.raises(RiskFreeEvidenceError, match=error):
        canonical_risk_free_evidence(
            cache=load_cached_treasury_observations(root=tmp_path, manifest_path=manifest),
            evaluation_as_of=as_of,
        )


@pytest.mark.parametrize(
    "unit,value", (("decimal", 4.25), ("percent", -1.0), ("percent", float("nan")))
)
def test_invalid_published_units_and_values_fail_closed(unit: str, value: float) -> None:
    with pytest.raises(RiskFreeEvidenceError):
        TreasuryObservation(date(2026, 9, 14), "10Y", value, unit, NOW)


def test_wrong_tenor_fails_closed() -> None:
    with pytest.raises(RiskFreeEvidenceError, match="RISK_FREE_TENOR_INVALID"):
        TreasuryObservation(date(2026, 9, 14), "2Y", 4.25, "percent", NOW)


def test_checksum_mismatch_fails_closed(tmp_path: Path) -> None:
    manifest = cache_treasury_observations(root=tmp_path, observations=(_observation(),))
    manifest.with_name("treasury-observations.json").write_text("{}", encoding="utf-8")

    with pytest.raises(RiskFreeEvidenceError, match="RISK_FREE_SOURCE_INVALID"):
        load_cached_treasury_observations(root=tmp_path, manifest_path=manifest)


def test_official_treasury_csv_is_parsed_into_canonical_observations() -> None:
    import qhapaq_finance.risk_free_evidence as risk_free

    raw = (
        b"Date,1 Mo,2 Mo,3 Mo,6 Mo,1 Yr,2 Yr,3 Yr,5 Yr,7 Yr,10 Yr,20 Yr,30 Yr\n"
        b"09/14/2026,4.10,4.11,4.12,4.13,4.14,4.15,4.16,4.17,4.18,4.25,4.50,4.60\n"
        b"09/15/2026,4.09,4.10,4.11,4.12,4.13,4.14,4.15,4.16,4.17,4.24,4.49,4.59\n"
    )

    retrieved_at = datetime(2026, 9, 16, tzinfo=timezone.utc)

    observations = risk_free.parse_official_treasury_daily_par_yield(
        raw,
        retrieved_at=retrieved_at,
    )

    assert observations == (
        TreasuryObservation(
            date(2026, 9, 14),
            "10Y",
            4.25,
            "percent",
            retrieved_at,
        ),
        TreasuryObservation(
            date(2026, 9, 15),
            "10Y",
            4.24,
            "percent",
            retrieved_at,
        ),
    )


def test_invalid_official_treasury_csv_fails_closed() -> None:
    import qhapaq_finance.risk_free_evidence as risk_free

    raw = b"Date,2 Yr,5 Yr\n09/15/2026,4.14,4.16\n"

    with pytest.raises(RiskFreeEvidenceError, match="RISK_FREE_SOURCE_INVALID"):
        risk_free.parse_official_treasury_daily_par_yield(
            raw,
            retrieved_at=NOW,
        )
