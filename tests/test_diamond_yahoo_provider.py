from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from qhapaq_finance.diamond.cache import DiamondCache
from qhapaq_finance.diamond.providers.yahoo import YahooBatchMarketProvider


class FakeClient:
    def __init__(self) -> None:
        self.requests = 0

    def get_json(self, url: str) -> object:
        query = parse_qs(urlsplit(url).query)
        assert query["symbols"] == ["AAPL,BRK-B"]
        assert query["range"] == ["5d"]
        assert query["interval"] == ["1d"]
        self.requests += 1
        aapl_time = int(datetime(2026, 9, 21, 20, tzinfo=timezone.utc).timestamp())
        brk_time = int(datetime(2026, 9, 18, 20, tzinfo=timezone.utc).timestamp())
        return {
            "spark": {
                "result": [
                    {
                        "symbol": "AAPL",
                        "response": [
                            {
                                "meta": {"currency": "USD"},
                                "timestamp": [aapl_time],
                                "indicators": {"quote": [{"close": [250.0]}]},
                            }
                        ],
                    },
                    {
                        "symbol": "BRK-B",
                        "response": [
                            {
                                "meta": {"currency": "USD"},
                                "timestamp": [brk_time],
                                "indicators": {"quote": [{"close": [500.0]}]},
                            }
                        ],
                    },
                ],
                "error": None,
            }
        }


def test_yahoo_batch_maps_class_share_symbols_and_observation_dates(tmp_path: Path) -> None:
    client = FakeClient()
    provider = YahooBatchMarketProvider(
        client=client,
        cache=DiamondCache(tmp_path / "market"),
    )

    quotes = provider.quotes(("BRK.B", "AAPL"), date(2026, 9, 22))

    assert tuple(quotes) == ("AAPL", "BRK.B")
    assert quotes["AAPL"].price == 250.0
    assert quotes["AAPL"].observed_on == date(2026, 9, 21)
    assert quotes["BRK.B"].price == 500.0
    assert quotes["BRK.B"].observed_on == date(2026, 9, 18)
    assert quotes["AAPL"].market_cap is None
    assert client.requests == 1
    assert provider.provider_requests == 1
    assert provider.cache_misses == 1


def test_yahoo_batch_replays_without_network(tmp_path: Path) -> None:
    as_of = date(2026, 9, 22)
    cache = DiamondCache(tmp_path / "market")
    live = YahooBatchMarketProvider(client=FakeClient(), cache=cache)
    expected = live.quotes(("AAPL", "BRK.B"), as_of)

    replay = YahooBatchMarketProvider(client=None, cache=cache)
    actual = replay.quotes(("BRK.B", "AAPL"), as_of)

    assert actual == expected
    assert replay.provider_requests == 0
    assert replay.cache_hits == 1
    assert replay.cache_misses == 0


class TenSymbolLimitClient:
    def __init__(self) -> None:
        self.requests = 0

    def get_json(self, url: str) -> object:
        query = parse_qs(urlsplit(url).query)
        symbols = query["symbols"][0].split(",")

        if len(symbols) > 10:
            raise RuntimeError("provider rejects batches larger than ten symbols")

        self.requests += 1
        timestamp = int(datetime(2026, 9, 21, 20, tzinfo=timezone.utc).timestamp())

        return {
            "spark": {
                "result": [
                    {
                        "symbol": symbol,
                        "response": [
                            {
                                "meta": {"currency": "USD"},
                                "timestamp": [timestamp],
                                "indicators": {"quote": [{"close": [100.0]}]},
                            }
                        ],
                    }
                    for symbol in symbols
                ],
                "error": None,
            }
        }


def test_yahoo_batch_splits_requests_at_ten_symbols(tmp_path: Path) -> None:
    client = TenSymbolLimitClient()
    provider = YahooBatchMarketProvider(
        client=client,
        cache=DiamondCache(tmp_path / "market"),
    )
    tickers = tuple(f"T{index:02d}" for index in range(11))

    quotes = provider.quotes(tickers, date(2026, 9, 22))

    assert len(quotes) == 11
    assert client.requests == 2
