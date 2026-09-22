from __future__ import annotations

from datetime import date
from pathlib import Path

from qhapaq_finance.diamond.cache import DiamondCache
from qhapaq_finance.diamond.providers.sp500 import Sp500UniverseProvider

HTML = """
<html><body>
<table class="wikitable sortable" id="constituents">
  <thead><tr>
    <th>Symbol</th><th>Security</th><th>GICS Sector</th>
    <th>GICS Sub-Industry</th><th>Headquarters Location</th>
    <th>Date added</th><th>CIK</th><th>Founded</th>
  </tr></thead>
  <tbody>
    <tr><td><a> AAPL </a></td><td>Apple Inc.</td><td>Information Technology</td>
      <td>Technology Hardware, Storage &amp; Peripherals</td><td>Cupertino</td>
      <td>1982-11-30</td><td>320193</td><td>1976</td></tr>
    <tr><td>BRK.B</td><td>Berkshire Hathaway</td><td>Financials</td>
      <td>Multi-Sector Holdings</td><td>Omaha</td>
      <td>2010-02-16</td><td>1067983</td><td>1839</td></tr>
  </tbody>
</table>
</body></html>
"""


class FakeClient:
    def __init__(self) -> None:
        self.requests = 0

    def get_text(self, url: str) -> str:
        assert url == Sp500UniverseProvider.SOURCE_URL
        self.requests += 1
        return HTML


def test_sp500_universe_maps_real_identity_and_class_share_symbol(tmp_path: Path) -> None:
    client = FakeClient()
    provider = Sp500UniverseProvider(
        client=client,
        cache=DiamondCache(tmp_path / "universe"),
    )

    securities = provider.universe("sp500", date(2026, 9, 22))

    assert [item.ticker for item in securities] == ["AAPL", "BRK.B"]
    assert securities[0].security_id == "sp500:AAPL"
    assert securities[0].issuer_id == "sec-cik:0000320193"
    assert securities[1].issuer_id == "sec-cik:0001067983"
    assert provider.metadata("AAPL").company_name == "Apple Inc."
    assert provider.metadata("AAPL").sector == "Information Technology"
    assert provider.metadata("AAPL").industry_group == (
        "Technology Hardware, Storage & Peripherals"
    )
    assert client.requests == 1
    assert provider.provider_requests == 1
    assert provider.cache_misses == 1


def test_sp500_universe_replays_from_cache_without_a_client(tmp_path: Path) -> None:
    cache = DiamondCache(tmp_path / "universe")
    live = Sp500UniverseProvider(client=FakeClient(), cache=cache)
    expected = live.universe("sp500", date(2026, 9, 22))

    replay = Sp500UniverseProvider(client=None, cache=cache)
    actual = replay.universe("sp500", date(2026, 9, 22))

    assert actual == expected
    assert replay.provider_requests == 0
    assert replay.cache_hits == 1
    assert replay.cache_misses == 0
    assert replay.metadata("BRK.B").company_name == "Berkshire Hathaway"
