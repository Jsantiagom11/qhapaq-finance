from datetime import date

import pytest

from qhapaq_finance.diamond.providers.market import (
    MarketQuote,
    SplitCoverage,
    derive_safe_market_cap,
)


def quote(
    *,
    market_cap: float | None = None,
    observed_on: date = date(2026, 9, 21),
) -> MarketQuote:
    return MarketQuote("AAA", 10.0, observed_on, "USD", market_cap, "market-test", "quote-sha")


def test_direct_provider_market_cap_is_accepted() -> None:
    decision = derive_safe_market_cap(
        quote=quote(market_cap=250.0),
        shares=17.0,
        shares_observed_on=date(2026, 6, 30),
        split_coverage=None,
    )

    assert decision.market_cap == pytest.approx(250.0)
    assert decision.diagnostic is None


def test_same_date_price_and_shares_can_derive_market_cap() -> None:
    decision = derive_safe_market_cap(
        quote=quote(observed_on=date(2026, 9, 21)),
        shares=17.0,
        shares_observed_on=date(2026, 9, 21),
        split_coverage=None,
    )

    assert decision.market_cap == pytest.approx(170.0)
    assert decision.diagnostic is None


def test_split_covered_interval_adjusts_shares() -> None:
    coverage = SplitCoverage(
        ticker="AAA",
        start_date=date(2026, 6, 30),
        end_date=date(2026, 9, 21),
        cumulative_factor=4.0,
        source_provider="yahoo-finance",
        source_identity="split-sha",
        event_dates=(date(2026, 8, 15),),
    )
    decision = derive_safe_market_cap(
        quote=quote(),
        shares=17.0,
        shares_observed_on=date(2026, 6, 30),
        split_coverage=coverage,
    )

    assert decision.market_cap == pytest.approx(680.0)
    assert decision.diagnostic is None


def test_unverified_interval_withholds_market_cap() -> None:
    decision = derive_safe_market_cap(
        quote=quote(),
        shares=17.0,
        shares_observed_on=date(2026, 6, 30),
        split_coverage=None,
    )

    assert decision.market_cap is None
    assert decision.diagnostic == "MARKET_CAP_SPLIT_UNVERIFIED"


def test_recent_shares_have_no_unverified_grace_window() -> None:
    decision = derive_safe_market_cap(
        quote=quote(),
        shares=17.0,
        shares_observed_on=date(2026, 9, 20),
        split_coverage=None,
    )

    assert decision.market_cap is None
    assert decision.diagnostic == "MARKET_CAP_SPLIT_UNVERIFIED"


def test_same_day_split_basis_is_not_assumed_safe() -> None:
    coverage = SplitCoverage(
        ticker="AAA",
        start_date=date(2026, 6, 30),
        end_date=date(2026, 9, 21),
        cumulative_factor=4.0,
        source_provider="yahoo-finance",
        source_identity="split-sha",
        event_dates=(date(2026, 6, 30),),
    )
    decision = derive_safe_market_cap(
        quote=quote(),
        shares=17.0,
        shares_observed_on=date(2026, 6, 30),
        split_coverage=coverage,
    )

    assert decision.market_cap is None
    assert decision.diagnostic == "MARKET_CAP_SPLIT_UNVERIFIED"


def test_shares_after_quote_yield_temporal_mismatch() -> None:
    decision = derive_safe_market_cap(
        quote=quote(),
        shares=17.0,
        shares_observed_on=date(2026, 9, 22),
        split_coverage=None,
    )

    assert decision.market_cap is None
    assert decision.diagnostic == "MARKET_CAP_TEMPORAL_MISMATCH"


def test_missing_shares_withholds_market_cap_without_split_diagnostic() -> None:
    decision = derive_safe_market_cap(
        quote=quote(),
        shares=None,
        shares_observed_on=None,
        split_coverage=None,
    )

    assert decision.market_cap is None
    assert decision.diagnostic is None


def test_coverage_must_match_the_complete_interval_and_ticker() -> None:
    coverage = SplitCoverage(
        ticker="BBB",
        start_date=date(2026, 7, 1),
        end_date=date(2026, 9, 21),
        cumulative_factor=4.0,
        source_provider="yahoo-finance",
        source_identity="split-sha",
    )

    decision = derive_safe_market_cap(
        quote=quote(),
        shares=17.0,
        shares_observed_on=date(2026, 6, 30),
        split_coverage=coverage,
    )

    assert decision.market_cap is None
    assert decision.diagnostic == "MARKET_CAP_SPLIT_UNVERIFIED"
