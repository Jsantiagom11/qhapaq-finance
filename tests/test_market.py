from datetime import datetime, timedelta, timezone

import pytest

from qhapaq_finance.market import (
    Freshness,
    FreshnessPolicy,
    MarketDataError,
    MarketSnapshot,
    MarketState,
    classify_freshness,
    load_market_snapshot,
    snapshot_age,
    write_market_snapshot,
)


def _snapshot(*, observed_at: datetime, retrieved_at: datetime) -> MarketSnapshot:
    return MarketSnapshot(
        ticker="nvda",
        price=230.36,
        currency="USD",
        observed_at=observed_at,
        retrieved_at=retrieved_at,
        source="fixture",
        market_state=MarketState.CLOSED,
        previous_close=228.10,
        market_cap=5_500_000_000_000.0,
    )


def test_snapshot_round_trip_preserves_observation_identity(tmp_path) -> None:
    observed = datetime(2026, 9, 4, 20, 0, tzinfo=timezone.utc)
    retrieved = datetime(2026, 9, 7, 3, 0, tzinfo=timezone.utc)
    snapshot = _snapshot(observed_at=observed, retrieved_at=retrieved)

    output = write_market_snapshot(snapshot, tmp_path / "nvda.json")
    loaded = load_market_snapshot(output)

    assert loaded.ticker == "NVDA"
    assert loaded.price == pytest.approx(230.36)
    assert loaded.market_cap == pytest.approx(5_500_000_000_000.0)
    assert loaded.observed_at == observed
    assert loaded.retrieved_at == retrieved
    assert loaded.market_state is MarketState.CLOSED
    assert loaded.change_from_previous_close == pytest.approx(230.36 / 228.10 - 1)


def test_freshness_uses_market_observation_not_retrieval_time() -> None:
    now = datetime(2026, 9, 7, 22, 0, tzinfo=timezone.utc)
    snapshot = _snapshot(
        observed_at=now - timedelta(hours=73),
        retrieved_at=now - timedelta(seconds=5),
    )

    assert (
        classify_freshness(snapshot, policy=FreshnessPolicy(max_age=timedelta(hours=36)), now=now)
        is Freshness.STALE
    )
    assert snapshot_age(snapshot, now=now) == timedelta(hours=73)


def test_freshness_policy_is_use_case_specific() -> None:
    now = datetime(2026, 9, 7, 22, 0, tzinfo=timezone.utc)
    snapshot = _snapshot(
        observed_at=now - timedelta(minutes=20),
        retrieved_at=now - timedelta(minutes=1),
    )

    assert (
        classify_freshness(snapshot, policy=FreshnessPolicy(max_age=timedelta(minutes=5)), now=now)
        is Freshness.STALE
    )
    assert (
        classify_freshness(snapshot, policy=FreshnessPolicy(max_age=timedelta(hours=1)), now=now)
        is Freshness.FRESH
    )


def test_future_observation_is_explicit() -> None:
    now = datetime(2026, 9, 7, 22, 0, tzinfo=timezone.utc)
    snapshot = _snapshot(
        observed_at=now + timedelta(minutes=10),
        retrieved_at=now,
    )
    assert (
        classify_freshness(snapshot, policy=FreshnessPolicy(max_age=timedelta(hours=1)), now=now)
        is Freshness.FUTURE
    )


def test_naive_timestamp_fails() -> None:
    with pytest.raises(MarketDataError, match="timezone-aware"):
        classify_freshness(
            _snapshot(
                observed_at=datetime(2026, 9, 7, 22, 0),
                retrieved_at=datetime(2026, 9, 7, 22, 0, tzinfo=timezone.utc),
            ),
            policy=FreshnessPolicy(max_age=timedelta(hours=1)),
        )
