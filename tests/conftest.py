from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from qhapaq_finance.beta_evidence import CachedPriceSeries, PriceObservation, cache_price_series
from qhapaq_finance.equity_risk_premium import (
    SternErpObservation,
    cache_stern_erp_observations,
)
from qhapaq_finance.market import MarketSnapshot, MarketState
from qhapaq_finance.market_inputs import cache_yfinance_snapshot
from qhapaq_finance.risk_free_evidence import (
    TreasuryObservation,
    cache_treasury_observations,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
AAPL_SEC_FIXTURE = REPOSITORY_ROOT / "tests/fixtures/sec_corpus/AAPL"
FIXTURE_NOW = datetime(2026, 9, 15, 16, tzinfo=timezone.utc)


def _copy_aapl_sec_corpus(root: Path) -> None:
    shutil.copytree(AAPL_SEC_FIXTURE, root / "data/cache/sec_corpus_live/AAPL")


def _period(index: int) -> date:
    return date(2023 + index // 12, index % 12 + 1, 1)


def _price_series(security_id: str, ticker: str, returns: tuple[float, ...]) -> CachedPriceSeries:
    price = 100.0
    observations = [PriceObservation(_period(0), price)]
    for index, periodic_return in enumerate(returns, start=1):
        price *= 1 + periodic_return
        observations.append(PriceObservation(_period(index), price))
    return CachedPriceSeries(
        security_id,
        ticker,
        "monthly",
        "adjusted_close",
        tuple(observations),
        f"fixture:{security_id}",
        f"fixture-checksum:{security_id}",
    )


def _build_aapl_capital_market_evidence(root: Path) -> None:
    cache_yfinance_snapshot(
        root=root,
        ticker="AAPL",
        max_age=timedelta(days=2),
        fetcher=lambda _ticker, *, now: MarketSnapshot(
            ticker="AAPL",
            price=100.0,
            currency="USD",
            observed_at=FIXTURE_NOW,
            retrieved_at=FIXTURE_NOW,
            source="yfinance",
            market_state=MarketState.REGULAR,
        ),
        now=FIXTURE_NOW,
    )

    monthly_returns = tuple(0.005 + index / 10_000 for index in range(40))
    cache_price_series(
        root=root,
        series=_price_series("apple-inc:AAPL", "AAPL", monthly_returns),
    )
    cache_price_series(
        root=root,
        series=_price_series("benchmark:^GSPC", "^GSPC", monthly_returns),
    )
    cache_treasury_observations(
        root=root,
        observations=(TreasuryObservation(date(2026, 9, 15), "10Y", 5.0, "percent", FIXTURE_NOW),),
    )
    cache_stern_erp_observations(
        root=root,
        observations=(
            SternErpObservation(
                date(2026, 9, 1),
                "United States",
                "S&P 500 implied ERP",
                4.0,
                "percent",
                FIXTURE_NOW,
            ),
        ),
    )

    debt_directory = root / "data/cache/debt/market/apple-inc_AAPL"
    debt_directory.mkdir(parents=True)
    (debt_directory / "synthetic-senior-note.json").write_text(
        json.dumps(
            {
                "schema_version": "market-debt-observation-v1",
                "issuer_id": "apple-inc",
                "security_id": "apple-inc:AAPL",
                "instrument": "Synthetic fixed-rate senior note",
                "settlement_date": "2026-09-15",
                "yield": 0.04,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


@pytest.fixture(scope="session")
def aapl_sec_corpus_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("aapl-sec-corpus")
    _copy_aapl_sec_corpus(root)
    return root


@pytest.fixture(scope="session")
def aapl_companyfacts() -> dict[str, object]:
    return json.loads((AAPL_SEC_FIXTURE / "companyfacts.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def aapl_analysis_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("aapl-analysis")
    shutil.copytree(REPOSITORY_ROOT / "data/domain", root / "data/domain")
    sec_reference = root / "data/cache/sec"
    sec_reference.mkdir(parents=True)
    shutil.copy(
        REPOSITORY_ROOT / "data/cache/sec/company_tickers.json",
        sec_reference / "company_tickers.json",
    )
    _copy_aapl_sec_corpus(root)
    _build_aapl_capital_market_evidence(root)
    return root
