from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import cast

import pytest

from qhapaq_finance.market import MarketDataError, MarketSnapshot, MarketState
from qhapaq_finance.market_inputs import (
    MarketInputError,
    cache_yfinance_snapshot,
    cached_canonical_market_input,
)

ROOT = Path(__file__).parents[1]
NOW = datetime(2026, 9, 15, 16, 0, tzinfo=timezone.utc)


def _root_with_registry(tmp_path: Path) -> Path:
    domain = tmp_path / "data/domain"
    domain.mkdir(parents=True)
    shutil.copy(ROOT / "data/domain/issuers.json", domain / "issuers.json")
    return tmp_path


def _snapshot(
    *,
    price: float = 100.0,
    currency: str = "USD",
    observed_at: datetime = NOW,
) -> MarketSnapshot:
    return MarketSnapshot(
        ticker="AAPL",
        price=price,
        currency=currency,
        observed_at=observed_at,
        retrieved_at=NOW,
        source="yfinance",
        market_state=MarketState.REGULAR,
    )


def test_registered_frozen_yfinance_observation_promotes_to_canonical_market_input(
    tmp_path: Path,
) -> None:
    root = _root_with_registry(tmp_path)
    profile = cache_yfinance_snapshot(
        root=root,
        ticker="AAPL",
        max_age=timedelta(days=1),
        fetcher=lambda _ticker, *, now: _snapshot(),
        now=NOW,
    )

    market = cached_canonical_market_input(
        root=root,
        ticker="AAPL",
        profile=profile,
        evaluation_as_of=date(2026, 9, 15),
        evaluation_at=NOW,
        valuation_shares=10.0,
        expected_currency="USD",
    )

    assert market.source_kind == "canonical"
    assert market.price == 100.0
    assert market.observed_at == NOW
    assert market.currency == "USD"
    assert market.market_equity == 1_000.0
    assert market.price_fact_identity
    assert market.canonical_observation_identity
    assert market.source_manifest_identity
    assert cached_canonical_market_input(
        root=root,
        ticker="AAPL",
        profile=profile,
        evaluation_as_of=date(2026, 9, 15),
        evaluation_at=NOW,
        valuation_shares=10.0,
        expected_currency="USD",
    ) == market


@pytest.mark.parametrize(
    ("price", "observed_at"),
    ((None, NOW), (float("nan"), NOW), (100.0, datetime(2026, 9, 15, 16, 0))),
)
def test_market_cache_rejects_invalid_yfinance_observations(
    tmp_path: Path, price: float | None, observed_at: datetime
) -> None:
    root = _root_with_registry(tmp_path)
    invalid = _snapshot(price=cast(float, price), observed_at=observed_at)

    with pytest.raises(MarketDataError):
        cache_yfinance_snapshot(
            root=root,
            ticker="AAPL",
            max_age=timedelta(days=1),
            fetcher=lambda _ticker, *, now: invalid,
            now=NOW,
        )


def test_cached_market_input_fails_closed_for_currency_staleness_and_checksum(
    tmp_path: Path,
) -> None:
    root = _root_with_registry(tmp_path)
    profile = cache_yfinance_snapshot(
        root=root,
        ticker="AAPL",
        max_age=timedelta(hours=1),
        fetcher=lambda _ticker, *, now: _snapshot(observed_at=NOW - timedelta(days=2)),
        now=NOW,
    )
    kwargs = {
        "root": root,
        "ticker": "AAPL",
        "profile": profile,
        "evaluation_as_of": date(2026, 9, 15),
        "evaluation_at": NOW,
        "valuation_shares": 10.0,
    }

    with pytest.raises(MarketInputError, match="MARKET_QUALITY_FAILED"):
        cached_canonical_market_input(**kwargs)

    fresh_profile = cache_yfinance_snapshot(
        root=root,
        ticker="AAPL",
        max_age=timedelta(days=1),
        fetcher=lambda _ticker, *, now: _snapshot(),
        now=NOW,
    )
    with pytest.raises(MarketInputError, match="MARKET_CURRENCY_MISMATCH"):
        cached_canonical_market_input(
            **kwargs | {"profile": fresh_profile, "expected_currency": "EUR"}
        )

    manifest = json.loads(fresh_profile.with_name("manifest.json").read_text(encoding="utf-8"))
    raw = root / manifest["raw_artifact"]
    raw.write_text("{}", encoding="utf-8")
    with pytest.raises(MarketInputError, match="MARKET_QUALITY_FAILED"):
        cached_canonical_market_input(**kwargs | {"profile": fresh_profile})
