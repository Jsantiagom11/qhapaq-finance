from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from qhapaq_finance.diamond.cache import DiamondCache
from qhapaq_finance.diamond.providers.yahoo_splits import (
    YahooSplitAdjustmentProvider,
    YahooSplitProviderError,
)

NO_SPLIT = {
    "chart": {
        "result": [{"meta": {"currency": "USD"}, "timestamp": [1789948800]}],
        "error": None,
    }
}

ONE_SPLIT = {
    "chart": {
        "result": [
            {
                "meta": {"currency": "USD"},
                "timestamp": [1789948800],
                "events": {
                    "splits": {
                        "1787356800": {
                            "date": 1787356800,
                            "numerator": 4.0,
                            "denominator": 1.0,
                            "splitRatio": "4:1",
                        }
                    }
                },
            }
        ],
        "error": None,
    }
}

START = date(2026, 6, 30)
END = date(2026, 9, 21)
AS_OF = date(2026, 9, 22)


class FakeClient:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.urls: list[str] = []

    def get_json(self, url: str) -> object:
        self.urls.append(url)
        return self.payload


def _provider(tmp_path: Path, payload: object) -> tuple[YahooSplitAdjustmentProvider, FakeClient]:
    client = FakeClient(payload)
    provider = YahooSplitAdjustmentProvider(
        client=client,
        cache=DiamondCache(tmp_path / "splits"),
    )
    return provider, client


def test_valid_no_event_response_returns_identity_factor(tmp_path: Path) -> None:
    provider, client = _provider(tmp_path, NO_SPLIT)

    coverage = provider.coverage("AAA", START, END, AS_OF)

    assert coverage is not None
    assert coverage.cumulative_factor == pytest.approx(1.0)
    assert coverage.event_dates == ()
    assert coverage.start_date == START
    assert coverage.end_date == END
    assert coverage.source_identity
    assert provider.provider_requests == 1
    assert provider.cache_misses == 1

    request = urlsplit(client.urls[0])
    query = parse_qs(request.query)
    assert request.path == "/v8/finance/chart/AAA"
    assert query == {
        "period1": [str(int(datetime(2026, 6, 30, tzinfo=timezone.utc).timestamp()))],
        "period2": [str(int(datetime(2026, 9, 22, tzinfo=timezone.utc).timestamp()))],
        "interval": ["1d"],
        "events": ["splits"],
    }


def test_one_split_returns_its_adjustment_factor(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path, ONE_SPLIT)

    coverage = provider.coverage("AAA", START, END, AS_OF)

    assert coverage is not None
    assert coverage.cumulative_factor == pytest.approx(4.0)
    assert coverage.event_dates == (date(2026, 8, 22),)


def test_two_valid_split_events_multiply_and_dates_are_sorted(tmp_path: Path) -> None:
    payload = {
        "chart": {
            "result": [
                {
                    "meta": {"currency": "USD"},
                    "timestamp": [1789948800],
                    "events": {
                        "splits": {
                            "later": {
                                "date": 1787356800,
                                "numerator": 3.0,
                                "denominator": 2.0,
                            },
                            "earlier": {
                                "date": 1784678400,
                                "numerator": 2.0,
                                "denominator": 1.0,
                            },
                        }
                    },
                }
            ],
            "error": None,
        }
    }
    provider, _ = _provider(tmp_path, payload)

    coverage = provider.coverage("AAA", START, END, AS_OF)

    assert coverage is not None
    assert coverage.cumulative_factor == pytest.approx(3.0)
    assert coverage.event_dates == tuple(sorted(coverage.event_dates))


@pytest.mark.parametrize(
    "event",
    (
        {"date": 1787356800, "numerator": "4", "denominator": 1.0},
        {"date": 1787356800, "numerator": 4.0, "denominator": 0.0},
    ),
)
def test_malformed_split_events_fail_closed(tmp_path: Path, event: object) -> None:
    payload = {
        "chart": {
            "result": [
                {
                    "meta": {"currency": "USD"},
                    "timestamp": [1789948800],
                    "events": {"splits": {"event": event}},
                }
            ],
            "error": None,
        }
    }
    provider, _ = _provider(tmp_path, payload)

    with pytest.raises(YahooSplitProviderError):
        provider.coverage("AAA", START, END, AS_OF)


def test_warm_provider_reuses_exact_interval_without_network(tmp_path: Path) -> None:
    cache = DiamondCache(tmp_path / "splits")
    live = YahooSplitAdjustmentProvider(client=FakeClient(ONE_SPLIT), cache=cache)
    expected = live.coverage("AAA", START, END, AS_OF)

    replay = YahooSplitAdjustmentProvider(client=None, cache=cache)
    actual = replay.coverage("AAA", START, END, AS_OF)

    assert actual == expected
    assert replay.provider_requests == 0
    assert replay.cache_hits == 1
    assert replay.cache_misses == 0
