from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from qhapaq_finance.diamond.cache import DiamondCache
from qhapaq_finance.diamond.contracts import (
    FiscalSlot,
    Methodology,
)
from qhapaq_finance.diamond.metrics import value
from qhapaq_finance.diamond.providers.fmp import FmpProvider


class FakeFmpClient:
    QUARTERS = {
        (2025, "Q3"): "2025-09-30",
        (2025, "Q4"): "2025-12-31",
        (2026, "Q1"): "2026-03-31",
        (2026, "Q2"): "2026-06-30",
    }

    def get_json(
        self,
        endpoint: str,
        params: Mapping[str, str] | None = None,
    ) -> object:
        params = params or {}

        if endpoint == "sp500-constituent":
            return [
                {
                    "symbol": "ACME",
                    "name": "Acme Corporation",
                    "sector": "Technology",
                    "subSector": "Software",
                }
            ]

        if endpoint == "batch-quote":
            return [
                {
                    "symbol": "ACME",
                    "marketCap": 1_000.0,
                    "timestamp": int(
                        datetime(
                            2026,
                            9,
                            21,
                            16,
                            0,
                            tzinfo=timezone.utc,
                        ).timestamp()
                    ),
                }
            ]

        year = int(params["year"])
        period = params["period"]

        if period == "FY":
            if not 2021 <= year <= 2025:
                return []
            statement_date = f"{year}-12-31"
        else:
            statement_date = self.QUARTERS.get((year, period))
            if statement_date is None:
                return []

        if endpoint == "income-statement-bulk":
            annual_step = max(year - 2021, 0)
            revenue = 80.0 + annual_step * 5.0 if period == "FY" else 30.0
            return [
                {
                    "symbol": "ACME",
                    "date": statement_date,
                    "reportedCurrency": "USD",
                    "revenue": revenue,
                    "operatingIncome": (revenue * 0.20),
                    "incomeBeforeTax": (revenue * 0.18),
                    "incomeTaxExpense": (revenue * 0.04),
                    "weightedAverageShsOutDil": (10.0 + annual_step * 0.1),
                }
            ]

        if endpoint == "balance-sheet-statement-bulk":
            annual_step = max(year - 2021, 0)
            return [
                {
                    "symbol": "ACME",
                    "date": statement_date,
                    "cashAndCashEquivalents": 10.0,
                    "shortTermInvestments": 2.0,
                    "totalDebt": 5.0,
                    "totalStockholdersEquity": 40.0,
                    "commonStockSharesOutstanding": (10.0 + annual_step * 0.1),
                }
            ]

        if endpoint == "cash-flow-statement-bulk":
            return [
                {
                    "symbol": "ACME",
                    "date": statement_date,
                    "operatingCashFlow": 8.0,
                    "capitalExpenditure": -2.0,
                }
            ]

        raise AssertionError(endpoint)


def test_fmp_provider_builds_canonical_record_and_replays_cache(
    tmp_path: Path,
) -> None:
    as_of = date(2026, 9, 21)
    cache = DiamondCache(tmp_path / "fmp")

    live = FmpProvider(
        client=FakeFmpClient(),
        cache=cache,
    )
    securities = live.universe("sp500", as_of)
    records = live.fundamentals(
        securities,
        as_of,
    )

    assert len(records) == 1
    record = records[0]

    assert record.ticker == "ACME"
    assert record.methodology is Methodology.OPERATING_COMPANY
    assert record.fundamental_period_end == date(
        2026,
        6,
        30,
    )
    assert record.market_age_trading_days == 0

    assert value(
        record,
        "revenue",
        FiscalSlot.TTM,
    ) == pytest.approx(120.0)

    assert value(
        record,
        "operating_cash_flow",
        FiscalSlot.TTM,
    ) == pytest.approx(32.0)

    assert value(
        record,
        "capital_expenditures",
        FiscalSlot.TTM,
    ) == pytest.approx(8.0)

    assert value(
        record,
        "market_cap",
        FiscalSlot.LATEST,
    ) == pytest.approx(1_000.0)

    assert value(
        record,
        "revenue",
        FiscalSlot.FY1,
    ) == pytest.approx(100.0)

    assert live.provider_requests > 0

    replay = FmpProvider(
        client=None,
        cache=cache,
    )
    replay_securities = replay.universe(
        "sp500",
        as_of,
    )
    replay_records = replay.fundamentals(
        replay_securities,
        as_of,
    )

    assert replay_records == records
    assert replay.provider_requests == 0
    assert replay.cache_hits > 0
