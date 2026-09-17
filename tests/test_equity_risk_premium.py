from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from qhapaq_finance.equity_risk_premium import (
    EquityRiskPremiumError,
    SternErpObservation,
    cache_stern_erp_observations,
    canonical_equity_risk_premium,
    load_cached_stern_erp_observations,
)

NOW = datetime(2026, 9, 15, tzinfo=timezone.utc)


def _observation(day: date = date(2026, 8, 31), value: float = 4.5) -> SternErpObservation:
    return SternErpObservation(day, "United States", "S&P 500 implied ERP", value, "percent", NOW)


def test_canonical_erp_normalizes_selects_and_adapts(tmp_path: Path) -> None:
    manifest = cache_stern_erp_observations(
        root=tmp_path, observations=(_observation(date(2026, 7, 31), 4.4), _observation())
    )
    cache = load_cached_stern_erp_observations(root=tmp_path, manifest_path=manifest)
    first = canonical_equity_risk_premium(cache=cache, evaluation_as_of=date(2026, 9, 15))
    second = canonical_equity_risk_premium(cache=cache, evaluation_as_of=date(2026, 9, 15))

    assert first.value == pytest.approx(0.045)
    assert first.observed_at == date(2026, 8, 31)
    assert first.identity == second.identity
    assert first.as_capital_cost_evidence().metric == "equity_risk_premium"
    assert first.source_checksum


@pytest.mark.parametrize(
    ("observations", "as_of", "error"),
    [
        ((_observation(date(2026, 10, 31)),), date(2026, 9, 15), "ERP_OBSERVATION_UNAVAILABLE"),
        ((_observation(date(2026, 6, 1)),), date(2026, 9, 15), "ERP_STALE"),
    ],
)
def test_unacceptable_observations_fail_closed(
    tmp_path: Path, observations: tuple[SternErpObservation, ...], as_of: date, error: str
) -> None:
    manifest = cache_stern_erp_observations(root=tmp_path, observations=observations)
    with pytest.raises(EquityRiskPremiumError, match=error):
        canonical_equity_risk_premium(
            cache=load_cached_stern_erp_observations(root=tmp_path, manifest_path=manifest),
            evaluation_as_of=as_of,
        )


@pytest.mark.parametrize(
    "market,series,unit,value",
    (
        ("Canada", "S&P 500 implied ERP", "percent", 4.5),
        ("United States", "bad", "percent", 4.5),
        ("United States", "S&P 500 implied ERP", "decimal", 4.5),
        ("United States", "S&P 500 implied ERP", "percent", float("nan")),
    ),
)
def test_invalid_source_fields_fail_closed(
    market: str, series: str, unit: str, value: float
) -> None:
    with pytest.raises(EquityRiskPremiumError):
        SternErpObservation(date(2026, 8, 31), market, series, value, unit, NOW)


def test_checksum_mismatch_fails_closed(tmp_path: Path) -> None:
    manifest = cache_stern_erp_observations(root=tmp_path, observations=(_observation(),))
    manifest.with_name("stern-erp-observations.json").write_text("{}", encoding="utf-8")
    with pytest.raises(EquityRiskPremiumError, match="ERP_SOURCE_INVALID"):
        load_cached_stern_erp_observations(root=tmp_path, manifest_path=manifest)
