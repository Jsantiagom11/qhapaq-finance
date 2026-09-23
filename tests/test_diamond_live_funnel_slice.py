from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from qhapaq_finance.diamond.cache import DiamondCache, DiamondCacheError
from qhapaq_finance.diamond.funnel import run_funnel
from qhapaq_finance.diamond.providers.fmp import FmpProvider
from qhapaq_finance.diamond.providers.local import LocalJsonProvider


def test_cache_round_trip_and_corruption_detection(tmp_path: Path) -> None:
    cache = DiamondCache(tmp_path)

    stored = cache.store(
        "income-statement-bulk?period=FY&year=2025",
        provider="fmp",
        data_as_of=date(2026, 9, 21),
        payload=[{"symbol": "AAPL", "revenue": 1}],
    )

    loaded = cache.load("income-statement-bulk?period=FY&year=2025")
    assert loaded is not None
    assert loaded.payload == [{"symbol": "AAPL", "revenue": 1}]
    assert loaded.payload_sha256 == stored.payload_sha256

    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1

    raw = json.loads(files[0].read_text(encoding="utf-8"))
    raw["payload"][0]["revenue"] = 2
    files[0].write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(DiamondCacheError):
        cache.load("income-statement-bulk?period=FY&year=2025")


def test_fmp_universe_maps_sp500_members() -> None:
    class Client:
        def get_json(self, endpoint: str, params=None):
            assert endpoint == "sp500-constituent"
            return [
                {
                    "symbol": "AAPL",
                    "name": "Apple Inc.",
                    "sector": "Technology",
                    "subSector": "Technology Hardware",
                },
                {
                    "symbol": "BRK.B",
                    "name": "Berkshire Hathaway",
                    "sector": "Financial Services",
                    "subSector": "Insurance",
                },
            ]

    provider = FmpProvider(client=Client())
    securities = provider.universe("sp500", date(2026, 9, 21))

    assert [item.ticker for item in securities] == ["AAPL", "BRK.B"]
    assert securities[0].security_id == "fmp:AAPL"
    assert securities[0].issuer_id == "fmp:AAPL"


def test_run_funnel_uses_existing_diamond_engine() -> None:
    provider = LocalJsonProvider(Path("tests/fixtures/diamond/minimal-universe.json"))

    run = run_funnel(
        provider,
        universe_id=provider.universe_id,
        as_of=provider.data_as_of,
        depth=5,
    )

    assert len(run.results) == 5
    assert run.results[0].ticker == "T19"
    assert run.results[0].archetypes.research_priority == pytest.approx(86.25)
    assert run.metadata.universe_count == 22
    assert run.metadata.canonical_records == 22
    assert run.metadata.ranked_records == 20
    assert run.metadata.unranked_records == 2
    assert run.metadata.dataset_identity


def test_provider_record_order_does_not_change_funnel_identity() -> None:
    source = LocalJsonProvider(Path("tests/fixtures/diamond/minimal-universe.json"))
    securities = source.universe(
        source.universe_id,
        source.data_as_of,
    )
    records = source.fundamentals(
        securities,
        source.data_as_of,
    )

    class OrderedProvider:
        provider_requests = 0
        cache_hits = 0
        cache_misses = 0

        def __init__(self, security_order, record_order) -> None:
            self._securities = security_order
            self._records = record_order

        def universe(self, universe_id: str, as_of: date):
            assert universe_id == source.universe_id
            assert as_of == source.data_as_of
            return self._securities

        def fundamentals(
            self,
            securities,
            as_of: date,
            history_years: int = 5,
        ):
            assert securities == self._securities
            assert as_of == source.data_as_of
            assert history_years == 5
            return self._records

    forward = run_funnel(
        OrderedProvider(securities, records),
        universe_id=source.universe_id,
        as_of=source.data_as_of,
        depth=10,
    )
    reversed_run = run_funnel(
        OrderedProvider(
            tuple(reversed(securities)),
            tuple(reversed(records)),
        ),
        universe_id=source.universe_id,
        as_of=source.data_as_of,
        depth=10,
    )

    assert forward.metadata.dataset_identity == reversed_run.metadata.dataset_identity
    assert [item.ticker for item in forward.results] == [
        item.ticker for item in reversed_run.results
    ]
