from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from qhapaq_finance.diamond.cache import DiamondCache
from qhapaq_finance.diamond.contracts import FiscalSlot, Methodology, SecurityRef
from qhapaq_finance.diamond.metrics import value
from qhapaq_finance.diamond.providers.market import MarketProviderError, MarketQuote
from qhapaq_finance.diamond.providers.sec import SecFirstProvider, SecFirstProviderError
from qhapaq_finance.diamond.providers.sp500 import Sp500Company


def _duration(
    value: float,
    *,
    start: str,
    end: str,
    filed: str,
    fiscal_year: int,
    fiscal_period: str,
    form: str,
) -> dict[str, object]:
    return {
        "start": start,
        "end": end,
        "val": value,
        "accn": f"{fiscal_year:010d}-26-000001",
        "fy": fiscal_year,
        "fp": fiscal_period,
        "form": form,
        "filed": filed,
    }


def _instant(
    value: float,
    *,
    end: str,
    filed: str,
    fiscal_year: int,
    fiscal_period: str,
    form: str,
) -> dict[str, object]:
    return {
        "end": end,
        "val": value,
        "accn": f"{fiscal_year:010d}-26-000002",
        "fy": fiscal_year,
        "fp": fiscal_period,
        "form": form,
        "filed": filed,
    }


def _companyfacts() -> dict[str, object]:
    annual_periods = tuple(range(2021, 2026))

    def durations(
        base: float,
        step: float,
        *,
        prior_ytd: float = 40.0,
        current_ytd: float = 50.0,
    ) -> list[dict[str, object]]:
        rows = [
            _duration(
                base + step * (year - 2021),
                start=f"{year}-01-01",
                end=f"{year}-12-31",
                filed=f"{year + 1}-02-15",
                fiscal_year=year,
                fiscal_period="FY",
                form="10-K",
            )
            for year in annual_periods
        ]
        rows.extend(
            (
                _duration(
                    prior_ytd,
                    start="2025-01-01",
                    end="2025-06-30",
                    filed="2025-08-01",
                    fiscal_year=2025,
                    fiscal_period="Q2",
                    form="10-Q",
                ),
                _duration(
                    current_ytd,
                    start="2026-01-01",
                    end="2026-06-30",
                    filed="2026-08-01",
                    fiscal_year=2026,
                    fiscal_period="Q2",
                    form="10-Q",
                ),
            )
        )
        return rows

    def instants(base: float) -> list[dict[str, object]]:
        rows = [
            _instant(
                base + year - 2021,
                end=f"{year}-12-31",
                filed=f"{year + 1}-02-15",
                fiscal_year=year,
                fiscal_period="FY",
                form="10-K",
            )
            for year in annual_periods
        ]
        rows.append(
            _instant(
                base + 6,
                end="2026-06-30",
                filed="2026-08-01",
                fiscal_year=2026,
                fiscal_period="Q2",
                form="10-Q",
            )
        )
        return rows

    revenue = durations(80.0, 5.0)
    operating_income = durations(16.0, 1.0)
    operating_cash_flow = durations(14.0, 1.0)
    capex = durations(-8.0, -0.5, prior_ytd=-4.0, current_ytd=-6.0)
    pretax = durations(14.0, 1.0)
    taxes = durations(3.0, 0.2)
    diluted = durations(10.0, 0.1)
    common_shares = instants(10.0)
    common_shares.append(
        _instant(
            17.0,
            end="2026-07-31",
            filed="2026-08-01",
            fiscal_year=2026,
            fiscal_period="Q2",
            form="10-Q",
        )
    )

    return {
        "cik": 320193,
        "entityName": "Apple Inc.",
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "label": "Revenue",
                    "units": {"USD": revenue},
                },
                "OperatingIncomeLoss": {
                    "label": "Operating income",
                    "units": {"USD": operating_income},
                },
                "NetCashProvidedByUsedInOperatingActivities": {
                    "label": "Operating cash flow",
                    "units": {"USD": operating_cash_flow},
                },
                "PaymentsToAcquirePropertyPlantAndEquipment": {
                    "label": "Capital expenditures",
                    "units": {"USD": capex},
                },
                (
                    "IncomeLossFromContinuingOperationsBeforeIncomeTaxes"
                    "ExtraordinaryItemsNoncontrollingInterest"
                ): {
                    "label": "Pretax income",
                    "units": {"USD": pretax},
                },
                "IncomeTaxExpenseBenefit": {
                    "label": "Income tax",
                    "units": {"USD": taxes},
                },
                "WeightedAverageNumberOfDilutedSharesOutstanding": {
                    "label": "Diluted shares",
                    "units": {"shares": diluted},
                },
                "CashAndCashEquivalentsAtCarryingValue": {
                    "label": "Cash",
                    "units": {"USD": instants(20.0)},
                },
                "StockholdersEquity": {
                    "label": "Equity",
                    "units": {"USD": instants(40.0)},
                },
                "LongTermDebtCurrent": {
                    "label": "Current debt",
                    "units": {"USD": instants(2.0)},
                },
                "LongTermDebtNoncurrent": {
                    "label": "Noncurrent debt",
                    "units": {"USD": instants(8.0)},
                },
            },
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "label": "Shares outstanding",
                    "units": {"shares": common_shares},
                }
            },
        },
    }


class FakeUniverse:
    provider_requests = 0
    cache_hits = 0
    cache_misses = 0

    def __init__(self, *, sector: str = "Information Technology") -> None:
        self.company = Sp500Company(
            ticker="AAPL",
            cik="0000320193",
            company_name="Apple Inc.",
            sector=sector,
            industry_group="Technology Hardware",
        )

    def universe(self, universe_id: str, as_of: date) -> tuple[SecurityRef, ...]:
        assert universe_id == "sp500"
        return (SecurityRef("AAPL", "sp500:AAPL", "sec-cik:0000320193"),)

    def metadata(self, ticker: str) -> Sp500Company:
        assert ticker == "AAPL"
        return self.company


class FakeSecClient:
    def __init__(self) -> None:
        self.requests = 0

    def get_json(self, url: str) -> object:
        assert url.endswith("/CIK0000320193.json")
        self.requests += 1
        return _companyfacts()


class FakeMarketProvider:
    provider_requests = 1
    cache_hits = 0
    cache_misses = 1

    def quotes(self, tickers: tuple[str, ...], as_of: date) -> dict[str, MarketQuote]:
        assert tickers == ("AAPL",)
        assert as_of == date(2026, 9, 22)
        return {
            "AAPL": MarketQuote(
                ticker="AAPL",
                price=10.0,
                observed_on=date(2026, 9, 21),
                currency="USD",
                market_cap=None,
                source_provider="market-test",
                source_identity="market-payload-sha",
            )
        }


class BlockedMarketProvider:
    provider_requests = 1
    cache_hits = 0
    cache_misses = 1

    def quotes(self, tickers: tuple[str, ...], as_of: date) -> dict[str, MarketQuote]:
        raise MarketProviderError("MARKET_PROVIDER_BLOCKED")


def test_sec_provider_reuses_ttm_and_promotion_primitives(tmp_path: Path) -> None:
    client = FakeSecClient()
    provider = SecFirstProvider(
        universe_provider=FakeUniverse(),
        sec_client=client,
        sec_cache=DiamondCache(tmp_path / "sec"),
        market_provider=None,
    )
    securities = provider.universe("sp500", date(2026, 9, 22))

    records = provider.fundamentals(securities, date(2026, 9, 22))

    assert len(records) == 1
    record = records[0]
    assert record.ticker == "AAPL"
    assert record.methodology is Methodology.OPERATING_COMPANY
    assert record.fundamental_period_end == date(2026, 6, 30)
    assert value(record, "revenue", FiscalSlot.TTM) == pytest.approx(110.0)
    assert value(record, "capital_expenditures", FiscalSlot.TTM) == pytest.approx(12.0)
    assert value(record, "revenue", FiscalSlot.FY1) == pytest.approx(100.0)
    assert value(record, "revenue", FiscalSlot.FY5) == pytest.approx(80.0)
    assert value(record, "total_debt", FiscalSlot.LATEST) == pytest.approx(22.0)
    assert value(record, "total_equity", FiscalSlot.FY2) == pytest.approx(43.0)
    assert value(record, "shares_outstanding_latest", FiscalSlot.LATEST) == pytest.approx(17.0)
    assert record.market_age_trading_days is None
    assert client.requests == 1


def test_sec_provider_derives_market_cap_only_when_price_and_shares_exist(tmp_path: Path) -> None:
    provider = SecFirstProvider(
        universe_provider=FakeUniverse(),
        sec_client=FakeSecClient(),
        sec_cache=DiamondCache(tmp_path / "sec"),
        market_provider=FakeMarketProvider(),
    )
    securities = provider.universe("sp500", date(2026, 9, 22))

    record = provider.fundamentals(securities, date(2026, 9, 22))[0]

    assert value(record, "market_cap", FiscalSlot.LATEST) == pytest.approx(170.0)
    assert record.market_age_trading_days == 1


def test_sec_first_funnel_continues_when_optional_market_provider_is_blocked(
    tmp_path: Path,
) -> None:
    provider = SecFirstProvider(
        universe_provider=FakeUniverse(),
        sec_client=FakeSecClient(),
        sec_cache=DiamondCache(tmp_path / "sec"),
        market_provider=BlockedMarketProvider(),
    )
    securities = provider.universe("sp500", date(2026, 9, 22))

    record = provider.fundamentals(securities, date(2026, 9, 22))[0]

    assert value(record, "market_cap", FiscalSlot.LATEST) is None
    assert record.market_age_trading_days is None


def test_sec_provider_keeps_financials_visible_but_unrankable(tmp_path: Path) -> None:
    provider = SecFirstProvider(
        universe_provider=FakeUniverse(sector="Financials"),
        sec_client=FakeSecClient(),
        sec_cache=DiamondCache(tmp_path / "sec"),
        market_provider=None,
    )
    securities = provider.universe("sp500", date(2026, 9, 22))

    record = provider.fundamentals(securities, date(2026, 9, 22))[0]

    assert record.methodology is Methodology.UNSUPPORTED_FINANCIAL


def test_sec_provider_replays_companyfacts_without_network(tmp_path: Path) -> None:
    as_of = date(2026, 9, 22)
    cache = DiamondCache(tmp_path / "sec")
    live = SecFirstProvider(
        universe_provider=FakeUniverse(),
        sec_client=FakeSecClient(),
        sec_cache=cache,
        market_provider=None,
    )
    securities = live.universe("sp500", as_of)
    expected = live.fundamentals(securities, as_of)

    replay = SecFirstProvider(
        universe_provider=FakeUniverse(),
        sec_client=None,
        sec_cache=cache,
        market_provider=None,
    )
    replay.universe("sp500", as_of)
    actual = replay.fundamentals(securities, as_of)

    assert actual == expected
    assert replay.provider_requests == 0
    assert replay.cache_hits == 1
    assert replay.cache_misses == 0


def test_sec_provider_rejects_companyfacts_for_a_different_cik(tmp_path: Path) -> None:
    class WrongIssuerClient(FakeSecClient):
        def get_json(self, url: str) -> object:
            payload = _companyfacts()
            payload["cik"] = 789019
            return payload

    provider = SecFirstProvider(
        universe_provider=FakeUniverse(),
        sec_client=WrongIssuerClient(),
        sec_cache=DiamondCache(tmp_path / "sec"),
        market_provider=None,
    )
    securities = provider.universe("sp500", date(2026, 9, 22))

    with pytest.raises(SecFirstProviderError, match="SEC_COMPANYFACTS_CIK_MISMATCH"):
        provider.fundamentals(securities, date(2026, 9, 22))
