"""Financial Modeling Prep adapter for Diamond Funnel."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from typing import Protocol
from urllib.parse import urlencode

from ..cache import DiamondCache
from ..contracts import (
    FiscalSlot,
    FundamentalObservation,
    FundamentalPeriodType,
    FundamentalRecord,
    Methodology,
    PeriodKind,
    SecurityRef,
    UnitKind,
)


class FmpProviderError(RuntimeError):
    """Raised when FMP evidence cannot be mapped safely."""


class FmpJsonClient(Protocol):
    def get_json(
        self,
        endpoint: str,
        params: Mapping[str, str] | None = None,
    ) -> object: ...


FISCAL_SLOTS = (
    FiscalSlot.FY1,
    FiscalSlot.FY2,
    FiscalSlot.FY3,
    FiscalSlot.FY4,
    FiscalSlot.FY5,
)


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _cash_flow_value(row: Mapping[str, object]) -> float | None:
    for key in (
        "operatingCashFlow",
        "netCashProvidedByOperatingActivities",
        "netCashProvidedByOperatingActivites",
    ):
        value = _number(row.get(key))
        if value is not None:
            return value
    return None


def _capex_value(row: Mapping[str, object]) -> float | None:
    for key in (
        "capitalExpenditure",
        "investmentsInPropertyPlantAndEquipment",
    ):
        value = _number(row.get(key))
        if value is not None:
            return abs(value)
    return None


def _marketable_securities(row: Mapping[str, object]) -> float | None:
    direct = _number(row.get("shortTermInvestments"))
    if direct is not None and direct >= 0:
        return direct

    combined = _number(row.get("cashAndShortTermInvestments"))
    cash = _number(row.get("cashAndCashEquivalents"))
    if combined is not None and cash is not None and combined >= cash:
        return combined - cash

    return None


def _methodology(
    sector: str | None,
    industry_group: str | None,
) -> Methodology:
    sector_key = (sector or "").casefold()
    industry_key = (industry_group or "").casefold()

    if "insurance" in industry_key:
        return Methodology.UNSUPPORTED_INSURER

    if sector_key in {
        "financial services",
        "financials",
        "financial",
    }:
        return Methodology.UNSUPPORTED_FINANCIAL

    if "reit" in industry_key or "real estate investment trust" in industry_key:
        return Methodology.UNSUPPORTED_REIT

    if not sector or not industry_group:
        return Methodology.UNKNOWN

    return Methodology.OPERATING_COMPANY


def _business_day_age(observed: date, as_of: date) -> int | None:
    if observed > as_of:
        return None

    age = 0
    current = observed
    while current < as_of:
        current += timedelta(days=1)
        if current.weekday() < 5:
            age += 1
    return age


class FmpProvider:
    """Bulk-first FMP adapter for the Diamond discovery layer."""

    PROVIDER = "fmp"
    QUOTE_CHUNK_SIZE = 150

    def __init__(
        self,
        *,
        client: FmpJsonClient | None,
        cache: DiamondCache | None = None,
        refresh: bool = False,
    ) -> None:
        self._client = client
        self._cache = cache
        self._refresh = refresh
        self._universe_metadata: dict[str, Mapping[str, object]] = {}

        self.provider_requests = 0
        self.cache_hits = 0
        self.cache_misses = 0

    @staticmethod
    def _request_identity(
        endpoint: str,
        params: Mapping[str, str] | None,
    ) -> str:
        if not params:
            return endpoint
        return f"{endpoint}?{urlencode(sorted(params.items()))}"

    def _fetch(
        self,
        endpoint: str,
        params: Mapping[str, str] | None,
        *,
        as_of: date,
    ) -> object:
        identity = self._request_identity(endpoint, params)

        if self._cache is not None and not self._refresh:
            cached = self._cache.load(identity)
            if cached is not None:
                if cached.provider != self.PROVIDER:
                    raise FmpProviderError("FMP_CACHE_PROVIDER_MISMATCH")
                self.cache_hits += 1
                return cached.payload

        self.cache_misses += 1

        if self._client is None:
            raise FmpProviderError("FMP_CACHE_MISS_REQUIRES_API_KEY")

        self.provider_requests += 1
        payload = self._client.get_json(endpoint, params)

        if self._cache is not None:
            self._cache.store(
                identity,
                provider=self.PROVIDER,
                data_as_of=as_of,
                payload=payload,
            )

        return payload

    @staticmethod
    def _rows(
        payload: object,
        *,
        endpoint: str,
    ) -> tuple[Mapping[str, object], ...]:
        if not isinstance(payload, list):
            raise FmpProviderError(f"FMP_SCHEMA_INVALID:{endpoint}")

        rows: list[Mapping[str, object]] = []
        for index, item in enumerate(payload):
            if not isinstance(item, dict):
                raise FmpProviderError(f"FMP_ROW_INVALID:{endpoint}:{index}")
            rows.append(item)
        return tuple(rows)

    def universe(
        self,
        universe_id: str,
        as_of: date,
    ) -> tuple[SecurityRef, ...]:
        if universe_id.casefold() != "sp500":
            raise FmpProviderError("UNSUPPORTED_UNIVERSE")

        payload = self._fetch(
            "sp500-constituent",
            None,
            as_of=as_of,
        )

        securities: list[SecurityRef] = []
        seen: set[str] = set()

        for index, raw in enumerate(self._rows(payload, endpoint="sp500-constituent")):
            symbol = _text(raw.get("symbol"))
            if symbol is None:
                raise FmpProviderError(f"FMP_SP500_SYMBOL_INVALID:{index}")

            ticker = symbol.upper()
            if ticker in seen:
                raise FmpProviderError("FMP_SP500_DUPLICATE_TICKER")

            seen.add(ticker)
            identity = f"fmp:{ticker}"

            securities.append(
                SecurityRef(
                    ticker=ticker,
                    security_id=identity,
                    issuer_id=identity,
                )
            )
            self._universe_metadata[ticker] = raw

        if not securities:
            raise FmpProviderError("FMP_SP500_EMPTY")

        return tuple(securities)

    def _bulk_index(
        self,
        endpoint: str,
        *,
        years: tuple[int, ...],
        periods: tuple[str, ...],
        tickers: set[str],
        as_of: date,
    ) -> dict[str, dict[date, Mapping[str, object]]]:
        indexed: dict[
            str,
            dict[date, Mapping[str, object]],
        ] = {ticker: {} for ticker in tickers}

        for year in years:
            for period in periods:
                params = {
                    "year": str(year),
                    "period": period,
                }
                payload = self._fetch(
                    endpoint,
                    params,
                    as_of=as_of,
                )

                for raw in self._rows(payload, endpoint=endpoint):
                    symbol = _text(raw.get("symbol"))
                    if symbol is None:
                        raise FmpProviderError(f"FMP_SYMBOL_MISSING:{endpoint}")

                    ticker = symbol.upper()
                    if ticker not in tickers:
                        continue

                    period_end = _date(raw.get("date"))
                    if period_end is None:
                        raise FmpProviderError(f"FMP_DATE_INVALID:{endpoint}:{ticker}")

                    if period_end > as_of:
                        continue

                    previous = indexed[ticker].get(period_end)
                    if previous is not None and previous != raw:
                        raise FmpProviderError(
                            f"FMP_DUPLICATE_PERIOD:{endpoint}:{ticker}:{period_end}"
                        )

                    indexed[ticker][period_end] = raw

        return indexed

    def _quotes(
        self,
        tickers: set[str],
        *,
        as_of: date,
    ) -> dict[str, Mapping[str, object]]:
        symbols = sorted(tickers)
        indexed: dict[str, Mapping[str, object]] = {}

        for offset in range(0, len(symbols), self.QUOTE_CHUNK_SIZE):
            chunk = symbols[offset : offset + self.QUOTE_CHUNK_SIZE]
            payload = self._fetch(
                "batch-quote",
                {"symbols": ",".join(chunk)},
                as_of=as_of,
            )

            for raw in self._rows(payload, endpoint="batch-quote"):
                symbol = _text(raw.get("symbol"))
                if symbol is None:
                    raise FmpProviderError("FMP_QUOTE_SYMBOL_MISSING")

                ticker = symbol.upper()
                if ticker not in tickers:
                    continue

                if ticker in indexed and indexed[ticker] != raw:
                    raise FmpProviderError(f"FMP_DUPLICATE_QUOTE:{ticker}")

                indexed[ticker] = raw

        return indexed

    @staticmethod
    def _sum_metric(
        rows: tuple[Mapping[str, object], ...],
        field: str,
    ) -> float | None:
        values = tuple(_number(row.get(field)) for row in rows)
        if any(value is None for value in values):
            return None
        return sum(value for value in values if value is not None)

    @staticmethod
    def _sum_cash_flow(
        rows: tuple[Mapping[str, object], ...],
    ) -> float | None:
        values = tuple(_cash_flow_value(row) for row in rows)
        if any(value is None for value in values):
            return None
        return sum(value for value in values if value is not None)

    @staticmethod
    def _sum_capex(
        rows: tuple[Mapping[str, object], ...],
    ) -> float | None:
        values = tuple(_capex_value(row) for row in rows)
        if any(value is None for value in values):
            return None
        return sum(value for value in values if value is not None)

    @staticmethod
    def _market_age(
        quote: Mapping[str, object] | None,
        *,
        as_of: date,
    ) -> int | None:
        if quote is None:
            return None

        timestamp = _number(quote.get("timestamp"))
        if timestamp is None:
            return None

        try:
            observed = datetime.fromtimestamp(
                timestamp,
                tz=timezone.utc,
            ).date()
        except (OverflowError, OSError, ValueError):
            return None

        return _business_day_age(observed, as_of)

    def _build_record(
        self,
        security: SecurityRef,
        *,
        as_of: date,
        history_years: int,
        income_annual: dict[str, dict[date, Mapping[str, object]]],
        balance_annual: dict[str, dict[date, Mapping[str, object]]],
        cash_annual: dict[str, dict[date, Mapping[str, object]]],
        income_quarter: dict[str, dict[date, Mapping[str, object]]],
        balance_quarter: dict[str, dict[date, Mapping[str, object]]],
        cash_quarter: dict[str, dict[date, Mapping[str, object]]],
        quotes: dict[str, Mapping[str, object]],
    ) -> FundamentalRecord | None:
        ticker = security.ticker

        quarter_dates = sorted(
            set(income_quarter[ticker]) & set(cash_quarter[ticker]),
            reverse=True,
        )

        if len(quarter_dates) < 4:
            return None

        ttm_dates = tuple(quarter_dates[:4])
        fundamental_period_end = ttm_dates[0]

        income_ttm = tuple(income_quarter[ticker][item] for item in ttm_dates)
        cash_ttm = tuple(cash_quarter[ticker][item] for item in ttm_dates)

        annual_dates = sorted(
            set(income_annual[ticker]) & set(balance_annual[ticker]) & set(cash_annual[ticker]),
            reverse=True,
        )[:history_years]

        latest_income = income_quarter[ticker][fundamental_period_end]
        currency = _text(latest_income.get("reportedCurrency"))

        if currency is None and annual_dates:
            currency = _text(income_annual[ticker][annual_dates[0]].get("reportedCurrency"))

        if currency is None:
            return None

        metadata = self._universe_metadata.get(ticker, {})
        company_name = _text(metadata.get("name")) or ticker
        sector = _text(metadata.get("sector"))
        industry_group = _text(metadata.get("subSector"))

        observations: list[FundamentalObservation] = []

        def add(
            metric_id: str,
            slot: FiscalSlot,
            value: float | None,
            period_end: date,
            period_kind: PeriodKind,
            unit_kind: UnitKind,
            source_identity: str,
            *,
            share_class_id: str | None = None,
            adjustment_basis_id: str | None = None,
        ) -> None:
            if value is None:
                return

            observations.append(
                FundamentalObservation(
                    metric_id=metric_id,
                    fiscal_slot=slot,
                    value=value,
                    period_start=None,
                    period_end=period_end,
                    period_kind=period_kind,
                    unit_kind=unit_kind,
                    source_provider=self.PROVIDER,
                    source_identity=source_identity,
                    share_class_id=share_class_id,
                    adjustment_basis_id=adjustment_basis_id,
                )
            )

        ttm_identity = (
            f"fmp:derived-ttm:{ticker}:{ttm_dates[-1].isoformat()}:{ttm_dates[0].isoformat()}"
        )

        add(
            "revenue",
            FiscalSlot.TTM,
            self._sum_metric(income_ttm, "revenue"),
            fundamental_period_end,
            PeriodKind.DURATION,
            UnitKind.CURRENCY,
            ttm_identity,
        )
        add(
            "operating_income",
            FiscalSlot.TTM,
            self._sum_metric(income_ttm, "operatingIncome"),
            fundamental_period_end,
            PeriodKind.DURATION,
            UnitKind.CURRENCY,
            ttm_identity,
        )
        add(
            "pretax_income",
            FiscalSlot.TTM,
            self._sum_metric(income_ttm, "incomeBeforeTax"),
            fundamental_period_end,
            PeriodKind.DURATION,
            UnitKind.CURRENCY,
            ttm_identity,
        )
        add(
            "income_tax_expense",
            FiscalSlot.TTM,
            self._sum_metric(income_ttm, "incomeTaxExpense"),
            fundamental_period_end,
            PeriodKind.DURATION,
            UnitKind.CURRENCY,
            ttm_identity,
        )
        add(
            "operating_cash_flow",
            FiscalSlot.TTM,
            self._sum_cash_flow(cash_ttm),
            fundamental_period_end,
            PeriodKind.DURATION,
            UnitKind.CURRENCY,
            ttm_identity,
        )
        add(
            "capital_expenditures",
            FiscalSlot.TTM,
            self._sum_capex(cash_ttm),
            fundamental_period_end,
            PeriodKind.DURATION,
            UnitKind.CURRENCY,
            ttm_identity,
        )

        for index, period_end in enumerate(annual_dates):
            if index >= len(FISCAL_SLOTS):
                break

            slot = FISCAL_SLOTS[index]
            income = income_annual[ticker][period_end]
            balance = balance_annual[ticker][period_end]
            cash = cash_annual[ticker][period_end]
            identity = f"fmp:annual:{ticker}:{period_end.isoformat()}"

            add(
                "revenue",
                slot,
                _number(income.get("revenue")),
                period_end,
                PeriodKind.DURATION,
                UnitKind.CURRENCY,
                identity,
            )
            add(
                "operating_income",
                slot,
                _number(income.get("operatingIncome")),
                period_end,
                PeriodKind.DURATION,
                UnitKind.CURRENCY,
                identity,
            )
            add(
                "pretax_income",
                slot,
                _number(income.get("incomeBeforeTax")),
                period_end,
                PeriodKind.DURATION,
                UnitKind.CURRENCY,
                identity,
            )
            add(
                "income_tax_expense",
                slot,
                _number(income.get("incomeTaxExpense")),
                period_end,
                PeriodKind.DURATION,
                UnitKind.CURRENCY,
                identity,
            )
            add(
                "operating_cash_flow",
                slot,
                _cash_flow_value(cash),
                period_end,
                PeriodKind.DURATION,
                UnitKind.CURRENCY,
                identity,
            )
            add(
                "capital_expenditures",
                slot,
                _capex_value(cash),
                period_end,
                PeriodKind.DURATION,
                UnitKind.CURRENCY,
                identity,
            )

            add(
                "diluted_shares",
                slot,
                _number(income.get("weightedAverageShsOutDil")),
                period_end,
                PeriodKind.DURATION,
                UnitKind.SHARES,
                identity,
                share_class_id="COMMON",
                adjustment_basis_id="FMP_STANDARDIZED_DILUTED_V1",
            )

            add(
                "cash_and_equivalents",
                slot,
                _number(balance.get("cashAndCashEquivalents")),
                period_end,
                PeriodKind.INSTANT,
                UnitKind.CURRENCY,
                identity,
            )
            add(
                "marketable_securities",
                slot,
                _marketable_securities(balance),
                period_end,
                PeriodKind.INSTANT,
                UnitKind.CURRENCY,
                identity,
            )
            add(
                "total_debt",
                slot,
                _number(balance.get("totalDebt")),
                period_end,
                PeriodKind.INSTANT,
                UnitKind.CURRENCY,
                identity,
            )
            add(
                "total_equity",
                slot,
                (
                    _number(balance.get("totalStockholdersEquity"))
                    or _number(balance.get("totalEquity"))
                ),
                period_end,
                PeriodKind.INSTANT,
                UnitKind.CURRENCY,
                identity,
            )

            if slot is FiscalSlot.FY1:
                add(
                    "shares_outstanding_fy1_end",
                    FiscalSlot.FY1,
                    _number(balance.get("commonStockSharesOutstanding")),
                    period_end,
                    PeriodKind.INSTANT,
                    UnitKind.SHARES,
                    identity,
                    share_class_id="COMMON",
                    adjustment_basis_id="FMP_STANDARDIZED_COMMON_V1",
                )

        balance_candidates = {
            **balance_annual[ticker],
            **balance_quarter[ticker],
        }
        latest_balance_date = max(balance_candidates) if balance_candidates else None

        if latest_balance_date is not None:
            latest_balance = balance_candidates[latest_balance_date]
            latest_identity = f"fmp:balance:{ticker}:{latest_balance_date.isoformat()}"

            add(
                "cash_and_equivalents",
                FiscalSlot.LATEST,
                _number(latest_balance.get("cashAndCashEquivalents")),
                latest_balance_date,
                PeriodKind.INSTANT,
                UnitKind.CURRENCY,
                latest_identity,
            )
            add(
                "marketable_securities",
                FiscalSlot.LATEST,
                _marketable_securities(latest_balance),
                latest_balance_date,
                PeriodKind.INSTANT,
                UnitKind.CURRENCY,
                latest_identity,
            )
            add(
                "total_debt",
                FiscalSlot.LATEST,
                _number(latest_balance.get("totalDebt")),
                latest_balance_date,
                PeriodKind.INSTANT,
                UnitKind.CURRENCY,
                latest_identity,
            )
            add(
                "total_equity",
                FiscalSlot.LATEST,
                (
                    _number(latest_balance.get("totalStockholdersEquity"))
                    or _number(latest_balance.get("totalEquity"))
                ),
                latest_balance_date,
                PeriodKind.INSTANT,
                UnitKind.CURRENCY,
                latest_identity,
            )
            add(
                "shares_outstanding_latest",
                FiscalSlot.LATEST,
                _number(latest_balance.get("commonStockSharesOutstanding")),
                latest_balance_date,
                PeriodKind.INSTANT,
                UnitKind.SHARES,
                latest_identity,
                share_class_id="COMMON",
                adjustment_basis_id="FMP_STANDARDIZED_COMMON_V1",
            )

        quote = quotes.get(ticker)
        if quote is not None:
            timestamp = _number(quote.get("timestamp"))
            quote_date = as_of

            if timestamp is not None:
                try:
                    quote_date = datetime.fromtimestamp(
                        timestamp,
                        tz=timezone.utc,
                    ).date()
                except (OverflowError, OSError, ValueError):
                    quote_date = as_of

            quote_identity = (
                f"fmp:quote:{ticker}:{int(timestamp) if timestamp is not None else 'unknown'}"
            )

            add(
                "market_cap",
                FiscalSlot.LATEST,
                _number(quote.get("marketCap")),
                quote_date,
                PeriodKind.INSTANT,
                UnitKind.CURRENCY,
                quote_identity,
            )
            add(
                "enterprise_value_provider",
                FiscalSlot.LATEST,
                _number(quote.get("enterpriseValue")),
                quote_date,
                PeriodKind.INSTANT,
                UnitKind.CURRENCY,
                quote_identity,
            )

        fiscal_year_end = None
        if annual_dates:
            fiscal_year_end = annual_dates[0].strftime("%m-%d")

        peer_group_id = industry_group or sector or "UNKNOWN"

        return FundamentalRecord(
            ticker=ticker,
            security_id=security.security_id,
            issuer_id=security.issuer_id,
            company_name=company_name,
            currency=currency,
            peer_group_id=peer_group_id,
            sector=sector,
            industry_group=industry_group,
            methodology=_methodology(
                sector,
                industry_group,
            ),
            fiscal_year_end=fiscal_year_end,
            data_as_of=as_of,
            fundamental_period_type=FundamentalPeriodType.TTM,
            fundamental_period_end=fundamental_period_end,
            market_age_trading_days=self._market_age(
                quote,
                as_of=as_of,
            ),
            provider=self.PROVIDER,
            provider_identity=(f"fmp:{ticker}:{fundamental_period_end.isoformat()}"),
            observations=tuple(observations),
        )

    def fundamentals(
        self,
        securities: tuple[SecurityRef, ...],
        as_of: date,
        history_years: int = 5,
    ) -> tuple[FundamentalRecord, ...]:
        if (
            isinstance(history_years, bool)
            or not isinstance(history_years, int)
            or not 1 <= history_years <= 5
        ):
            raise FmpProviderError("HISTORY_YEARS_INVALID")

        tickers = {item.ticker for item in securities}
        if not tickers:
            return ()

        annual_years = tuple(
            range(
                as_of.year,
                as_of.year - history_years - 1,
                -1,
            )
        )
        quarter_years = (
            as_of.year,
            as_of.year - 1,
        )

        income_annual = self._bulk_index(
            "income-statement-bulk",
            years=annual_years,
            periods=("FY",),
            tickers=tickers,
            as_of=as_of,
        )
        balance_annual = self._bulk_index(
            "balance-sheet-statement-bulk",
            years=annual_years,
            periods=("FY",),
            tickers=tickers,
            as_of=as_of,
        )
        cash_annual = self._bulk_index(
            "cash-flow-statement-bulk",
            years=annual_years,
            periods=("FY",),
            tickers=tickers,
            as_of=as_of,
        )

        quarter_periods = ("Q1", "Q2", "Q3", "Q4")
        income_quarter = self._bulk_index(
            "income-statement-bulk",
            years=quarter_years,
            periods=quarter_periods,
            tickers=tickers,
            as_of=as_of,
        )
        balance_quarter = self._bulk_index(
            "balance-sheet-statement-bulk",
            years=quarter_years,
            periods=quarter_periods,
            tickers=tickers,
            as_of=as_of,
        )
        cash_quarter = self._bulk_index(
            "cash-flow-statement-bulk",
            years=quarter_years,
            periods=quarter_periods,
            tickers=tickers,
            as_of=as_of,
        )

        quotes = self._quotes(
            tickers,
            as_of=as_of,
        )

        records: list[FundamentalRecord] = []
        for security in securities:
            record = self._build_record(
                security,
                as_of=as_of,
                history_years=history_years,
                income_annual=income_annual,
                balance_annual=balance_annual,
                cash_annual=cash_annual,
                income_quarter=income_quarter,
                balance_quarter=balance_quarter,
                cash_quarter=cash_quarter,
                quotes=quotes,
            )
            if record is not None:
                records.append(record)

        if not records:
            raise FmpProviderError("FMP_NO_CANONICAL_RECORDS")

        return tuple(records)
