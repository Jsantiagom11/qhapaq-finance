from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, datetime, timezone
from pathlib import Path
from typing import cast

import pytest

import qhapaq_finance.diamond.providers.sec as sec_module
from qhapaq_finance.diamond.cache import DiamondCache
from qhapaq_finance.diamond.contracts import FiscalSlot, Methodology, SecurityRef
from qhapaq_finance.diamond.metrics import value
from qhapaq_finance.diamond.providers.market import (
    BatchMarketProvider,
    MarketProviderError,
    MarketQuote,
    SplitAdjustmentProvider,
    SplitCoverage,
)
from qhapaq_finance.diamond.providers.sec import (
    SecFirstProvider,
    UniverseMetadataProvider,
)
from qhapaq_finance.diamond.providers.sec_canonical import (
    CanonicalIssuerCache,
    CanonicalIssuerSnapshot,
    SecCanonicalError,
)
from qhapaq_finance.diamond.providers.sec_evidence import (
    SecEvidenceError,
    SecEvidenceManifest,
    SecEvidenceStore,
)
from qhapaq_finance.diamond.providers.sp500 import Sp500Company
from qhapaq_finance.financial_canonicalization import RawFact
from qhapaq_finance.sec_client import SecResponse


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


class TwoClassUniverse(FakeUniverse):
    def universe(self, universe_id: str, as_of: date) -> tuple[SecurityRef, ...]:
        assert universe_id == "sp500"
        return (
            SecurityRef("AAA", "sp500:AAA", "sec-cik:0000320193"),
            SecurityRef("AAB", "sp500:AAB", "sec-cik:0000320193"),
        )

    def metadata(self, ticker: str) -> Sp500Company:
        return Sp500Company(
            ticker=ticker,
            cik="0000320193",
            company_name=f"Issuer {ticker}",
            sector="Information Technology",
            industry_group="Technology Hardware",
        )


class FakeSecClient:
    def __init__(self, payload: dict[str, object] | None = None) -> None:
        self.payload = payload if payload is not None else _companyfacts()
        self.calls: list[tuple[str, dict[str, str], frozenset[int]]] = []

    @property
    def requests(self) -> int:
        return len(self.calls)

    def get(
        self,
        url: str,
        *,
        request_headers: Mapping[str, str] | None = None,
        accepted_statuses: frozenset[int] = frozenset(),
    ) -> SecResponse:
        assert url.endswith("/CIK0000320193.json")
        self.calls.append((url, dict(request_headers or {}), accepted_statuses))
        return SecResponse(200, {}, json.dumps(self.payload).encode())


class InstrumentedEvidenceStore(SecEvidenceStore):
    load_facts_calls = 0

    def load_facts(self, manifest: SecEvidenceManifest) -> tuple[RawFact, ...]:
        self.load_facts_calls += 1
        return super().load_facts(manifest)


def make_sec_first_provider(
    *,
    tmp_path: Path,
    payload: dict[str, object],
    market_provider: BatchMarketProvider | None,
    universe_provider: UniverseMetadataProvider | None = None,
    allow_network: bool = True,
    refresh: bool = False,
    client: FakeSecClient | None = None,
    split_provider: SplitAdjustmentProvider | None = None,
) -> SecFirstProvider:
    evidence_client = client or (FakeSecClient(payload) if allow_network else None)
    return SecFirstProvider(
        universe_provider=universe_provider or FakeUniverse(),
        evidence_store=InstrumentedEvidenceStore(
            root=tmp_path / "sec-evidence",
            client=evidence_client,
            legacy_cache=None,
            now=lambda: datetime(2026, 9, 22, 12, tzinfo=timezone.utc),
        ),
        canonical_cache=CanonicalIssuerCache(DiamondCache(tmp_path / "canonical")),
        market_provider=market_provider,
        split_provider=split_provider,
        refresh=refresh,
    )


class FakeMarketProvider:
    provider_requests = 1
    cache_hits = 0
    cache_misses = 1

    def __init__(self, *, market_cap: float | None = None) -> None:
        self.market_cap = market_cap

    def quotes(self, tickers: tuple[str, ...], as_of: date) -> dict[str, MarketQuote]:
        assert tickers == ("AAPL",)
        assert as_of == date(2026, 9, 22)
        return {
            "AAPL": MarketQuote(
                ticker="AAPL",
                price=10.0,
                observed_on=date(2026, 9, 21),
                currency="USD",
                market_cap=self.market_cap,
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


class FakeSplitProvider:
    provider_requests = 0
    cache_hits = 0
    cache_misses = 0

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, date, date, date]] = []

    def coverage(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
        as_of: date,
    ) -> SplitCoverage | None:
        self.calls.append((ticker, start_date, end_date, as_of))
        if self.fail:
            raise MarketProviderError("SPLIT_PROVIDER_BLOCKED")
        return SplitCoverage(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            cumulative_factor=4.0,
            source_provider="split-test",
            source_identity="split-payload-sha",
            event_dates=(date(2026, 8, 15),),
        )


def test_sec_canonicalizer_uses_in_scope_10q_amendment(tmp_path: Path) -> None:
    payload = _companyfacts()
    facts = cast(dict[str, object], payload["facts"])
    gaap = cast(dict[str, object], facts["us-gaap"])
    revenue = cast(
        dict[str, object],
        gaap["RevenueFromContractWithCustomerExcludingAssessedTax"],
    )
    units = cast(dict[str, list[dict[str, object]]], revenue["units"])
    units["USD"].append(
        _duration(
            60.0,
            start="2026-01-01",
            end="2026-06-30",
            filed="2026-08-15",
            fiscal_year=2026,
            fiscal_period="Q2",
            form="10-Q/A",
        )
    )
    provider = make_sec_first_provider(
        tmp_path=tmp_path,
        payload=payload,
        market_provider=None,
    )

    record = provider.fundamentals(
        provider.universe("sp500", date(2026, 9, 22)),
        date(2026, 9, 22),
    )[0]

    assert value(record, "revenue", FiscalSlot.TTM) == pytest.approx(120.0)


def test_sec_canonicalizer_uses_in_scope_10k_amendment(tmp_path: Path) -> None:
    payload = _companyfacts()
    facts = cast(dict[str, object], payload["facts"])
    gaap = cast(dict[str, object], facts["us-gaap"])
    revenue = cast(
        dict[str, object],
        gaap["RevenueFromContractWithCustomerExcludingAssessedTax"],
    )
    units = cast(dict[str, list[dict[str, object]]], revenue["units"])
    units["USD"].append(
        _duration(
            125.0,
            start="2025-01-01",
            end="2025-12-31",
            filed="2026-03-01",
            fiscal_year=2025,
            fiscal_period="FY",
            form="10-K/A",
        )
    )
    provider = make_sec_first_provider(
        tmp_path=tmp_path,
        payload=payload,
        market_provider=None,
    )

    record = provider.fundamentals(
        provider.universe("sp500", date(2026, 9, 22)),
        date(2026, 9, 22),
    )[0]

    assert value(record, "revenue", FiscalSlot.FY1) == pytest.approx(125.0)


def test_sec_canonicalizer_rejects_same_rank_conflicting_amendment(
    tmp_path: Path,
) -> None:
    payload = _companyfacts()
    facts = cast(dict[str, object], payload["facts"])
    gaap = cast(dict[str, object], facts["us-gaap"])
    revenue = cast(
        dict[str, object],
        gaap["RevenueFromContractWithCustomerExcludingAssessedTax"],
    )
    units = cast(dict[str, list[dict[str, object]]], revenue["units"])
    for amended_value in (125.0, 126.0):
        units["USD"].append(
            _duration(
                amended_value,
                start="2024-01-01",
                end="2024-12-31",
                filed="2025-03-01",
                fiscal_year=2024,
                fiscal_period="FY",
                form="10-K/A",
            )
        )
    provider = make_sec_first_provider(
        tmp_path=tmp_path,
        payload=payload,
        market_provider=None,
    )

    with pytest.raises(SecCanonicalError, match="SEC_.*_FACT_AMBIGUOUS"):
        provider.fundamentals(
            provider.universe("sp500", date(2026, 9, 22)),
            date(2026, 9, 22),
        )


def test_sec_provider_reuses_ttm_and_promotion_primitives(tmp_path: Path) -> None:
    client = FakeSecClient()
    provider = make_sec_first_provider(
        tmp_path=tmp_path,
        payload=client.payload,
        market_provider=None,
        client=client,
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
    assert record.provider_identity.startswith("sec-evidence:")
    assert {item.source_identity for item in record.observations} == {record.provider_identity}
    assert record.market_age_trading_days is None
    assert client.requests == 1
    assert provider.provider_requests == 1
    assert provider.cache_misses == 2


def test_sec_provider_withholds_market_cap_without_split_evidence(tmp_path: Path) -> None:
    provider = make_sec_first_provider(
        tmp_path=tmp_path,
        payload=_companyfacts(),
        market_provider=FakeMarketProvider(),
    )
    securities = provider.universe("sp500", date(2026, 9, 22))

    record = provider.fundamentals(securities, date(2026, 9, 22))[0]

    assert value(record, "market_cap", FiscalSlot.LATEST) is None
    assert "MARKET_CAP_SPLIT_UNVERIFIED" in record.evidence_diagnostics
    assert record.market_age_trading_days == 1


def test_sec_provider_derives_market_cap_with_complete_split_evidence(tmp_path: Path) -> None:
    split_provider = FakeSplitProvider()
    provider = make_sec_first_provider(
        tmp_path=tmp_path,
        payload=_companyfacts(),
        market_provider=FakeMarketProvider(),
        split_provider=split_provider,
    )
    securities = provider.universe("sp500", date(2026, 9, 22))

    record = provider.fundamentals(securities, date(2026, 9, 22))[0]

    assert value(record, "market_cap", FiscalSlot.LATEST) == pytest.approx(680.0)
    assert record.evidence_diagnostics == ()
    assert split_provider.calls == [
        ("AAPL", date(2026, 7, 31), date(2026, 9, 21), date(2026, 9, 22))
    ]


def test_sec_provider_keeps_security_when_optional_split_provider_fails(tmp_path: Path) -> None:
    provider = make_sec_first_provider(
        tmp_path=tmp_path,
        payload=_companyfacts(),
        market_provider=FakeMarketProvider(),
        split_provider=FakeSplitProvider(fail=True),
    )
    securities = provider.universe("sp500", date(2026, 9, 22))

    records = provider.fundamentals(securities, date(2026, 9, 22))

    assert len(records) == 1
    assert value(records[0], "market_cap", FiscalSlot.LATEST) is None
    assert "MARKET_CAP_SPLIT_UNVERIFIED" in records[0].evidence_diagnostics


def test_sec_provider_does_not_request_splits_for_direct_market_cap(tmp_path: Path) -> None:
    split_provider = FakeSplitProvider()
    provider = make_sec_first_provider(
        tmp_path=tmp_path,
        payload=_companyfacts(),
        market_provider=FakeMarketProvider(market_cap=250.0),
        split_provider=split_provider,
    )
    securities = provider.universe("sp500", date(2026, 9, 22))

    record = provider.fundamentals(securities, date(2026, 9, 22))[0]

    assert value(record, "market_cap", FiscalSlot.LATEST) == pytest.approx(250.0)
    assert split_provider.calls == []


def test_sec_first_funnel_continues_when_optional_market_provider_is_blocked(
    tmp_path: Path,
) -> None:
    provider = make_sec_first_provider(
        tmp_path=tmp_path,
        payload=_companyfacts(),
        market_provider=BlockedMarketProvider(),
    )
    securities = provider.universe("sp500", date(2026, 9, 22))

    record = provider.fundamentals(securities, date(2026, 9, 22))[0]

    assert value(record, "market_cap", FiscalSlot.LATEST) is None
    assert record.market_age_trading_days is None


def test_sec_provider_keeps_financials_visible_but_unrankable(tmp_path: Path) -> None:
    provider = make_sec_first_provider(
        tmp_path=tmp_path,
        payload=_companyfacts(),
        universe_provider=FakeUniverse(sector="Financials"),
        market_provider=None,
    )
    securities = provider.universe("sp500", date(2026, 9, 22))

    record = provider.fundamentals(securities, date(2026, 9, 22))[0]

    assert record.methodology is Methodology.UNSUPPORTED_FINANCIAL


def test_warm_canonical_hit_does_not_load_raw_sec_blob(tmp_path: Path) -> None:
    as_of = date(2026, 9, 22)
    payload = _companyfacts()
    live = make_sec_first_provider(
        tmp_path=tmp_path,
        payload=payload,
        market_provider=None,
    )
    securities = live.universe("sp500", as_of)
    expected = live.fundamentals(securities, as_of)

    replay = make_sec_first_provider(
        tmp_path=tmp_path,
        payload=payload,
        market_provider=None,
        allow_network=False,
    )
    replay.universe("sp500", as_of)
    actual = replay.fundamentals(securities, as_of)

    assert actual == expected
    assert replay.evidence_store.load_facts_calls == 0
    assert replay.canonical_cache.cache_hits == 1
    assert replay.provider_requests == 0
    assert replay.cache_hits == 2
    assert replay.cache_misses == 0


def test_sec_provider_rejects_companyfacts_for_a_different_cik(tmp_path: Path) -> None:
    payload = _companyfacts()
    payload["cik"] = 789019
    provider = make_sec_first_provider(
        tmp_path=tmp_path,
        payload=payload,
        market_provider=None,
    )
    securities = provider.universe("sp500", date(2026, 9, 22))

    with pytest.raises(SecEvidenceError, match="SEC_CIK_MISMATCH"):
        provider.fundamentals(securities, date(2026, 9, 22))


def test_two_share_classes_reuse_one_issuer_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    original = sec_module.canonicalize_issuer

    def counted_canonicalize(
        *,
        issuer_id: str,
        cik: str,
        as_of: date,
        history_years: int,
        evidence_revision_sha256: str,
        facts: tuple[RawFact, ...],
    ) -> CanonicalIssuerSnapshot | None:
        nonlocal calls
        calls += 1
        return original(
            issuer_id=issuer_id,
            cik=cik,
            as_of=as_of,
            history_years=history_years,
            evidence_revision_sha256=evidence_revision_sha256,
            facts=facts,
        )

    monkeypatch.setattr(sec_module, "canonicalize_issuer", counted_canonicalize)
    provider = make_sec_first_provider(
        tmp_path=tmp_path,
        payload=_companyfacts(),
        universe_provider=TwoClassUniverse(),
        market_provider=None,
    )

    securities = provider.universe("sp500", date(2026, 9, 22))
    records = provider.fundamentals(securities, date(2026, 9, 22))

    assert [item.ticker for item in records] == ["AAA", "AAB"]
    assert {item.issuer_id for item in records} == {"sec-cik:0000320193"}
    assert calls == 1
    assert provider.canonical_cache.cache_misses == 1


def test_universe_metadata_does_not_invalidate_canonical_snapshot(
    tmp_path: Path,
) -> None:
    payload = _companyfacts()
    first = make_sec_first_provider(
        tmp_path=tmp_path,
        payload=payload,
        universe_provider=FakeUniverse(sector="Information Technology"),
        market_provider=None,
    )
    securities = first.universe("sp500", date(2026, 9, 22))
    first.fundamentals(securities, date(2026, 9, 22))

    replay = make_sec_first_provider(
        tmp_path=tmp_path,
        payload=payload,
        universe_provider=FakeUniverse(sector="Industrials"),
        market_provider=None,
        allow_network=False,
    )
    record = replay.fundamentals(securities, date(2026, 9, 22))[0]

    assert record.sector == "Industrials"
    assert record.peer_group_id == "Industrials"
    assert replay.canonical_cache.cache_hits == 1
    assert replay.evidence_store.load_facts_calls == 0


def test_refresh_rebuilds_canonical_snapshot_from_new_evidence_revision(
    tmp_path: Path,
) -> None:
    as_of = date(2026, 9, 22)
    first = make_sec_first_provider(
        tmp_path=tmp_path,
        payload=_companyfacts(),
        market_provider=None,
    )
    securities = first.universe("sp500", as_of)
    initial = first.fundamentals(securities, as_of)[0]

    amended = _companyfacts()
    facts = cast(dict[str, object], amended["facts"])
    gaap = cast(dict[str, object], facts["us-gaap"])
    revenue = cast(
        dict[str, object],
        gaap["RevenueFromContractWithCustomerExcludingAssessedTax"],
    )
    units = cast(dict[str, list[dict[str, object]]], revenue["units"])
    units["USD"].append(
        _duration(
            125.0,
            start="2025-01-01",
            end="2025-12-31",
            filed="2026-03-01",
            fiscal_year=2025,
            fiscal_period="FY",
            form="10-K/A",
        )
    )
    client = FakeSecClient(amended)
    refreshed = make_sec_first_provider(
        tmp_path=tmp_path,
        payload=amended,
        market_provider=None,
        refresh=True,
        client=client,
    )
    updated = refreshed.fundamentals(securities, as_of)[0]

    assert value(initial, "revenue", FiscalSlot.FY1) == pytest.approx(100.0)
    assert value(updated, "revenue", FiscalSlot.FY1) == pytest.approx(125.0)
    assert client.calls[0][1] == {}
    assert refreshed.canonical_cache.cache_misses == 1
    assert updated.provider_identity != initial.provider_identity
