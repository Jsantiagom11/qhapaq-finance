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
