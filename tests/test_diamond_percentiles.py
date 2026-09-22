from __future__ import annotations

from datetime import date, timedelta

import pytest

from qhapaq_finance.diamond.percentiles import (
    Direction,
    FeatureDefinition,
    PercentilePolicy,
    compute_percentiles,
    empirical_percentile,
    linear_winsor_bounds,
)

try:
    from tests.diamond_helpers import rich_record
except ModuleNotFoundError:
    from diamond_helpers import rich_record


def test_winsorization_uses_explicit_linear_quantiles_for_eight_values() -> None:
    values = (0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 100.0)
    lower, upper = linear_winsor_bounds(values, PercentilePolicy())
    assert lower == pytest.approx(0.35)
    assert upper == pytest.approx(67.10)


def test_percentile_ties_receive_average_rank() -> None:
    values = (10.0, 20.0, 20.0, 40.0)
    assert empirical_percentile(values, 20.0, Direction.HIGHER_IS_BETTER) == pytest.approx(50.0)


def test_lower_is_better_is_exact_inverse() -> None:
    values = (1.0, 2.0, 3.0, 4.0)
    high = empirical_percentile(values, 3.0, Direction.HIGHER_IS_BETTER)
    low = empirical_percentile(values, 3.0, Direction.LOWER_IS_BETTER)
    assert high + low == pytest.approx(100.0)


def test_feature_requires_eight_finite_observations_even_with_twenty_peers() -> None:
    records = tuple(rich_record(f"T{i:02d}") for i in range(20))
    values = {
        record.ticker: {"feature": float(i) if i < 7 else None} for i, record in enumerate(records)
    }
    result = compute_percentiles(
        records,
        values,
        (FeatureDefinition("feature", Direction.HIGHER_IS_BETTER),),
    )["T00"]["feature"]
    assert result.percentile is None
    assert "INSUFFICIENT_PEER_OBSERVATIONS" in result.diagnostics


def test_peer_group_falls_back_to_eligible_universe_below_twenty() -> None:
    records = tuple(rich_record(f"A{i:02d}", peer_group_id="A") for i in range(19)) + tuple(
        rich_record(f"B{i:02d}", peer_group_id="B") for i in range(20)
    )
    values = {record.ticker: {"feature": float(i)} for i, record in enumerate(records)}
    result = compute_percentiles(
        records,
        values,
        (FeatureDefinition("feature", Direction.HIGHER_IS_BETTER),),
    )["A00"]["feature"]
    assert result.peer_scope == "ELIGIBLE_UNIVERSE"
    assert result.peer_count == 39


def test_peer_period_spread_over_ninety_two_days_fails_closed() -> None:
    # Keep both endpoints individually fresh while making the peer spread 93 days.
    base = date(2026, 9, 1)
    records = tuple(
        rich_record(
            f"T{i:02d}",
            period_end=base - timedelta(days=93 if i == 0 else 0),
        )
        for i in range(20)
    )
    values = {record.ticker: {"feature": float(i)} for i, record in enumerate(records)}
    result = compute_percentiles(
        records,
        values,
        (FeatureDefinition("feature", Direction.HIGHER_IS_BETTER),),
    )["T01"]["feature"]
    assert result.percentile is None
    assert "PEER_PERIOD_MISALIGNED" in result.diagnostics


def test_peer_period_spread_between_forty_six_and_ninety_two_warns_but_scores() -> None:
    base = date(2026, 6, 30)
    records = tuple(
        rich_record(
            f"T{i:02d}",
            period_end=base - timedelta(days=46 if i == 0 else 0),
        )
        for i in range(20)
    )
    values = {record.ticker: {"feature": float(i)} for i, record in enumerate(records)}
    result = compute_percentiles(
        records,
        values,
        (FeatureDefinition("feature", Direction.HIGHER_IS_BETTER),),
    )["T01"]["feature"]
    assert result.percentile is not None
    assert "PEER_PERIOD_DRIFT" in result.diagnostics
