"""SEC-first fundamental provider for broad Diamond Funnel discovery."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, timedelta
from typing import Protocol

from qhapaq_finance.evidence import DerivedFact, FinancialFact
from qhapaq_finance.financial_canonicalization import (
    PeriodKind as CanonicalPeriodKind,
)
from qhapaq_finance.financial_canonicalization import RawFact, extract_company_facts
from qhapaq_finance.financial_promotion import (
    FinancialPromotionError,
    MultiPeriodFinancialPromoter,
    accounting_evidence_policies,
)

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
from .market import BatchMarketProvider, MarketProviderError, MarketQuote
from .sp500 import Sp500Company


class SecFirstProviderError(RuntimeError):
    """Raised when SEC-first evidence cannot be mapped safely."""


class SecJsonClient(Protocol):
    def get_json(self, url: str) -> object: ...


class UniverseMetadataProvider(Protocol):
    provider_requests: int
    cache_hits: int
    cache_misses: int

    def universe(self, universe_id: str, as_of: date) -> tuple[SecurityRef, ...]: ...

    def metadata(self, ticker: str) -> Sp500Company: ...


_FISCAL_SLOTS = (
    FiscalSlot.FY1,
    FiscalSlot.FY2,
    FiscalSlot.FY3,
    FiscalSlot.FY4,
    FiscalSlot.FY5,
)

_DURATION_CONCEPTS: dict[str, tuple[tuple[str, str], ...]] = {
    "revenue": (
        ("RevenueFromContractWithCustomerExcludingAssessedTax", "USD"),
        ("Revenues", "USD"),
        ("SalesRevenueNet", "USD"),
    ),
    "operating_income": (("OperatingIncomeLoss", "USD"),),
    "operating_cash_flow": (
        ("NetCashProvidedByUsedInOperatingActivities", "USD"),
        ("NetCashProvidedByUsedInOperatingActivitiesContinuingOperations", "USD"),
    ),
    "capital_expenditures": (
        ("PaymentsToAcquirePropertyPlantAndEquipment", "USD"),
        ("PaymentsForAdditionsToPropertyPlantAndEquipment", "USD"),
    ),
    "pretax_income": (
        (
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxes"
            "ExtraordinaryItemsNoncontrollingInterest",
            "USD",
        ),
        (
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxes"
            "MinorityInterestAndIncomeLossFromEquityMethodInvestments",
            "USD",
        ),
    ),
    "income_tax_expense": (("IncomeTaxExpenseBenefit", "USD"),),
    "diluted_shares": (("WeightedAverageNumberOfDilutedSharesOutstanding", "shares"),),
}


def _methodology(company: Sp500Company) -> Methodology:
    sector = company.sector.casefold()
    industry = company.industry_group.casefold()
    if "insurance" in industry:
        return Methodology.UNSUPPORTED_INSURER
    if "reit" in industry or "real estate investment trust" in industry:
        return Methodology.UNSUPPORTED_REIT
    if sector in {"financials", "financial services", "financial"}:
        return Methodology.UNSUPPORTED_FINANCIAL
    if not company.sector or not company.industry_group:
        return Methodology.UNKNOWN
    return Methodology.OPERATING_COMPANY


def _business_day_age(observed: date, as_of: date) -> int | None:
    if observed > as_of:
        return None
    age = 0
    cursor = observed
    while cursor < as_of:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            age += 1
    return age


def _filtered_facts(payload: object, *, source_identity: str, as_of: date) -> tuple[RawFact, ...]:
    if not isinstance(payload, Mapping):
        raise SecFirstProviderError("SEC_COMPANYFACTS_SCHEMA_INVALID")
    try:
        extracted = extract_company_facts(payload, source_identity=source_identity)
    except ValueError as exc:
        raise SecFirstProviderError("SEC_COMPANYFACTS_SCHEMA_INVALID") from exc
    return tuple(
        fact
        for fact in extracted
        if fact.filing_date <= as_of
        and fact.end <= as_of
        and fact.filing_form in {"10-K", "10-Q"}
        and fact.consolidated
        and not fact.dimensions
    )


def _promote_ttm(
    facts: tuple[RawFact, ...], concepts: tuple[tuple[str, str], ...]
) -> FinancialFact | DerivedFact | None:
    promoter = MultiPeriodFinancialPromoter()
    for concept, unit in concepts:
        candidates = tuple(
            fact
            for fact in facts
            if fact.taxonomy == "us-gaap" and fact.concept == concept and fact.unit == unit
        )
        try:
            return promoter.promote_ttm(candidates, concept=concept)
        except FinancialPromotionError:
            continue
    return None


def _annual_fact(
    facts: tuple[RawFact, ...],
    *,
    concepts: tuple[tuple[str, str], ...],
    period_end: date,
) -> RawFact | None:
    for concept, unit in concepts:
        candidates = tuple(
            fact
            for fact in facts
            if fact.taxonomy == "us-gaap"
            and fact.concept == concept
            and fact.unit == unit
            and fact.period_kind is CanonicalPeriodKind.DURATION
            and fact.filing_form == "10-K"
            and fact.fiscal_period == "FY"
            and fact.start is not None
            and 250 <= (fact.end - fact.start).days <= 450
            and fact.end == period_end
        )
        if not candidates:
            continue
        rank = max((fact.filing_date, fact.accession) for fact in candidates)
        winners = tuple(fact for fact in candidates if (fact.filing_date, fact.accession) == rank)
        if len({fact.value for fact in winners}) != 1:
            raise SecFirstProviderError("SEC_ANNUAL_FACT_AMBIGUOUS")
        return winners[0]
    return None


def _annual_ends(facts: tuple[RawFact, ...]) -> tuple[date, ...]:
    for concept, unit in _DURATION_CONCEPTS["revenue"]:
        ends = {
            fact.end
            for fact in facts
            if fact.taxonomy == "us-gaap"
            and fact.concept == concept
            and fact.unit == unit
            and fact.period_kind is CanonicalPeriodKind.DURATION
            and fact.filing_form == "10-K"
            and fact.fiscal_period == "FY"
            and fact.start is not None
            and 250 <= (fact.end - fact.start).days <= 450
        }
        if ends:
            return tuple(sorted(ends, reverse=True)[: len(_FISCAL_SLOTS)])
    return ()


def _instant_fact(
    facts: tuple[RawFact, ...],
    *,
    taxonomy: str,
    concept: str,
    unit: str,
    period_end: date,
) -> RawFact | None:
    candidates = tuple(
        fact
        for fact in facts
        if fact.taxonomy == taxonomy
        and fact.concept == concept
        and fact.unit == unit
        and fact.period_kind is CanonicalPeriodKind.INSTANT
        and fact.end == period_end
    )
    if not candidates:
        return None
    rank = max((fact.filing_date, fact.accession) for fact in candidates)
    winners = tuple(fact for fact in candidates if (fact.filing_date, fact.accession) == rank)
    if len({fact.value for fact in winners}) != 1:
        raise SecFirstProviderError("SEC_INSTANT_FACT_AMBIGUOUS")
    return winners[0]


def _latest_balance_end(facts: tuple[RawFact, ...]) -> date | None:
    ends = (
        fact.end
        for fact in facts
        if fact.period_kind is CanonicalPeriodKind.INSTANT
        and fact.unit == "USD"
        and fact.taxonomy == "us-gaap"
    )
    return max(ends, default=None)


def _latest_instant_fact(
    facts: tuple[RawFact, ...],
    *,
    taxonomy: str,
    concept: str,
    unit: str,
) -> RawFact | None:
    ends = tuple(
        fact.end
        for fact in facts
        if fact.taxonomy == taxonomy
        and fact.concept == concept
        and fact.unit == unit
        and fact.period_kind is CanonicalPeriodKind.INSTANT
    )
    if not ends:
        return None
    return _instant_fact(
        facts,
        taxonomy=taxonomy,
        concept=concept,
        unit=unit,
        period_end=max(ends),
    )


def _promoted_instants(
    facts: tuple[RawFact, ...], target_end: date
) -> dict[str, FinancialFact | DerivedFact]:
    policies = {
        policy.metric_id: policy for policy in accounting_evidence_policies(closing_end=target_end)
    }
    promoter = MultiPeriodFinancialPromoter()
    selected: dict[str, FinancialFact | DerivedFact] = {}
    for source_name, metric_id in (
        ("cash", "cash_and_equivalents"),
        ("marketable_securities", "marketable_securities"),
        ("total_debt", "total_debt"),
        ("common_equity", "total_equity"),
    ):
        try:
            selected[metric_id] = promoter.promote(facts, policy=policies[source_name])
        except FinancialPromotionError:
            continue
    return selected


def _counter(provider: object | None, name: str) -> int:
    value = getattr(provider, name, 0)
    return value if isinstance(value, int) else 0


class SecFirstProvider:
    """Compose real membership, SEC accounting evidence, and market observations."""

    PROVIDER = "sec-first"
    SEC_PROVIDER = "sec-companyfacts"
    COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

    def __init__(
        self,
        *,
        universe_provider: UniverseMetadataProvider,
        sec_client: SecJsonClient | None,
        sec_cache: DiamondCache,
        market_provider: BatchMarketProvider | None,
        refresh: bool = False,
    ) -> None:
        self._universe_provider = universe_provider
        self._sec_client = sec_client
        self._sec_cache = sec_cache
        self._market_provider = market_provider
        self._refresh = refresh
        self._sec_provider_requests = 0
        self._sec_cache_hits = 0
        self._sec_cache_misses = 0

    @property
    def provider_requests(self) -> int:
        return (
            self._sec_provider_requests
            + _counter(self._universe_provider, "provider_requests")
            + _counter(self._market_provider, "provider_requests")
        )

    @property
    def cache_hits(self) -> int:
        return (
            self._sec_cache_hits
            + _counter(self._universe_provider, "cache_hits")
            + _counter(self._market_provider, "cache_hits")
        )

    @property
    def cache_misses(self) -> int:
        return (
            self._sec_cache_misses
            + _counter(self._universe_provider, "cache_misses")
            + _counter(self._market_provider, "cache_misses")
        )

    def universe(self, universe_id: str, as_of: date) -> tuple[SecurityRef, ...]:
        return self._universe_provider.universe(universe_id, as_of)

    def _companyfacts(self, cik: str, as_of: date) -> tuple[object, str]:
        identity = self.COMPANYFACTS_URL.format(cik=cik)
        if not self._refresh:
            cached = self._sec_cache.load(identity)
            if cached is not None and cached.data_as_of == as_of:
                if cached.provider != self.SEC_PROVIDER:
                    raise SecFirstProviderError("SEC_CACHE_PROVIDER_MISMATCH")
                self._validate_companyfacts_identity(cached.payload, cik)
                self._sec_cache_hits += 1
                return cached.payload, cached.payload_sha256

        self._sec_cache_misses += 1
        if self._sec_client is None:
            raise SecFirstProviderError("SEC_CACHE_MISS_REQUIRES_CLIENT")
        self._sec_provider_requests += 1
        try:
            payload = self._sec_client.get_json(identity)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SecFirstProviderError("SEC_COMPANYFACTS_REQUEST_FAILED") from exc
        self._validate_companyfacts_identity(payload, cik)
        stored = self._sec_cache.store(
            identity,
            provider=self.SEC_PROVIDER,
            data_as_of=as_of,
            payload=payload,
        )
        return stored.payload, stored.payload_sha256

    @staticmethod
    def _validate_companyfacts_identity(payload: object, cik: str) -> None:
        if not isinstance(payload, Mapping):
            raise SecFirstProviderError("SEC_COMPANYFACTS_SCHEMA_INVALID")
        raw_cik = payload.get("cik")
        if isinstance(raw_cik, bool) or not isinstance(raw_cik, (int, str)):
            raise SecFirstProviderError("SEC_COMPANYFACTS_CIK_INVALID")
        normalized = str(raw_cik).strip()
        if not normalized.isdigit() or normalized.zfill(10) != cik:
            raise SecFirstProviderError("SEC_COMPANYFACTS_CIK_MISMATCH")

    def fundamentals(
        self,
        securities: tuple[SecurityRef, ...],
        as_of: date,
        history_years: int = 5,
    ) -> tuple[FundamentalRecord, ...]:
        if history_years < 1:
            raise ValueError("history_years must be positive")
        try:
            quotes = (
                self._market_provider.quotes(tuple(item.ticker for item in securities), as_of)
                if self._market_provider is not None
                else {}
            )
        except MarketProviderError:
            quotes = {}
        evidence_by_cik: dict[str, tuple[object, str]] = {}
        records: list[FundamentalRecord] = []
        for security in securities:
            prefix = "sec-cik:"
            if not security.issuer_id.startswith(prefix):
                raise SecFirstProviderError("SEC_ISSUER_ID_INVALID")
            cik = security.issuer_id.removeprefix(prefix)
            evidence = evidence_by_cik.get(cik)
            if evidence is None:
                evidence = self._companyfacts(cik, as_of)
                evidence_by_cik[cik] = evidence
            record = self._build_record(
                security,
                company=self._universe_provider.metadata(security.ticker),
                payload=evidence[0],
                payload_identity=evidence[1],
                quote=quotes.get(security.ticker),
                as_of=as_of,
                history_years=history_years,
            )
            if record is not None:
                records.append(record)
        return tuple(records)

    def _build_record(
        self,
        security: SecurityRef,
        *,
        company: Sp500Company,
        payload: object,
        payload_identity: str,
        quote: MarketQuote | None,
        as_of: date,
        history_years: int,
    ) -> FundamentalRecord | None:
        facts = _filtered_facts(payload, source_identity=payload_identity, as_of=as_of)
        if not facts:
            return None
        annual_ends = _annual_ends(facts)[:history_years]
        revenue_ttm = _promote_ttm(facts, _DURATION_CONCEPTS["revenue"])
        fundamental_end = (
            revenue_ttm.period_end if revenue_ttm is not None else _latest_balance_end(facts)
        )
        if fundamental_end is None:
            return None

        observations: list[FundamentalObservation] = []

        def add(
            metric_id: str,
            slot: FiscalSlot,
            raw_value: float | None,
            *,
            period_start: date | None,
            period_end: date,
            period_kind: PeriodKind,
            unit_kind: UnitKind,
            source_provider: str = "sec",
            source_identity: str = payload_identity,
            share_class_id: str | None = None,
            adjustment_basis_id: str | None = None,
        ) -> None:
            if raw_value is None:
                return
            canonical_value = abs(raw_value) if metric_id == "capital_expenditures" else raw_value
            observations.append(
                FundamentalObservation(
                    metric_id=metric_id,
                    fiscal_slot=slot,
                    value=canonical_value,
                    period_start=period_start,
                    period_end=period_end,
                    period_kind=period_kind,
                    unit_kind=unit_kind,
                    source_provider=source_provider,
                    source_identity=source_identity,
                    share_class_id=share_class_id,
                    adjustment_basis_id=adjustment_basis_id,
                )
            )

        for metric_id, concepts in _DURATION_CONCEPTS.items():
            promoted = revenue_ttm if metric_id == "revenue" else _promote_ttm(facts, concepts)
            if promoted is None or promoted.period_end != fundamental_end:
                continue
            add(
                metric_id,
                FiscalSlot.TTM,
                promoted.value,
                period_start=promoted.period_start,
                period_end=promoted.period_end,
                period_kind=PeriodKind.DURATION,
                unit_kind=(UnitKind.SHARES if metric_id == "diluted_shares" else UnitKind.CURRENCY),
                adjustment_basis_id=(
                    "SEC_REPORTED_DILUTED_V1" if metric_id == "diluted_shares" else None
                ),
                share_class_id=("CONSOLIDATED_COMMON" if metric_id == "diluted_shares" else None),
            )

        for slot, annual_end in zip(_FISCAL_SLOTS, annual_ends, strict=False):
            for metric_id, concepts in _DURATION_CONCEPTS.items():
                fact = _annual_fact(facts, concepts=concepts, period_end=annual_end)
                if fact is None:
                    continue
                add(
                    metric_id,
                    slot,
                    fact.value,
                    period_start=fact.start,
                    period_end=fact.end,
                    period_kind=PeriodKind.DURATION,
                    unit_kind=(
                        UnitKind.SHARES if metric_id == "diluted_shares" else UnitKind.CURRENCY
                    ),
                    adjustment_basis_id=(
                        "SEC_REPORTED_DILUTED_V1" if metric_id == "diluted_shares" else None
                    ),
                    share_class_id=(
                        "CONSOLIDATED_COMMON" if metric_id == "diluted_shares" else None
                    ),
                )
            for metric_id, promoted in _promoted_instants(facts, annual_end).items():
                add(
                    metric_id,
                    slot,
                    promoted.value,
                    period_start=None,
                    period_end=promoted.period_end,
                    period_kind=PeriodKind.INSTANT,
                    unit_kind=UnitKind.CURRENCY,
                )

        latest_end = _latest_balance_end(facts)
        if latest_end is not None:
            for metric_id, promoted in _promoted_instants(facts, latest_end).items():
                add(
                    metric_id,
                    FiscalSlot.LATEST,
                    promoted.value,
                    period_start=None,
                    period_end=promoted.period_end,
                    period_kind=PeriodKind.INSTANT,
                    unit_kind=UnitKind.CURRENCY,
                )
            latest_shares = _latest_instant_fact(
                facts,
                taxonomy="dei",
                concept="EntityCommonStockSharesOutstanding",
                unit="shares",
            )
            if latest_shares is not None:
                add(
                    "shares_outstanding_latest",
                    FiscalSlot.LATEST,
                    latest_shares.value,
                    period_start=None,
                    period_end=latest_shares.end,
                    period_kind=PeriodKind.INSTANT,
                    unit_kind=UnitKind.SHARES,
                    share_class_id="CONSOLIDATED_COMMON",
                    adjustment_basis_id="SEC_REPORTED_COMMON_V1",
                )

        if annual_ends:
            annual_shares = _instant_fact(
                facts,
                taxonomy="dei",
                concept="EntityCommonStockSharesOutstanding",
                unit="shares",
                period_end=annual_ends[0],
            )
            if annual_shares is not None:
                add(
                    "shares_outstanding_fy1_end",
                    FiscalSlot.FY1,
                    annual_shares.value,
                    period_start=None,
                    period_end=annual_shares.end,
                    period_kind=PeriodKind.INSTANT,
                    unit_kind=UnitKind.SHARES,
                    share_class_id="CONSOLIDATED_COMMON",
                    adjustment_basis_id="SEC_REPORTED_COMMON_V1",
                )

        market_age = None
        if quote is not None and quote.observed_on <= as_of:
            market_cap = quote.market_cap
            if market_cap is None:
                latest_shares_value = next(
                    (
                        item.value
                        for item in observations
                        if item.metric_id == "shares_outstanding_latest"
                        and item.fiscal_slot is FiscalSlot.LATEST
                    ),
                    None,
                )
                if latest_shares_value is not None:
                    market_cap = quote.price * latest_shares_value
            add(
                "market_cap",
                FiscalSlot.LATEST,
                market_cap,
                period_start=None,
                period_end=quote.observed_on,
                period_kind=PeriodKind.INSTANT,
                unit_kind=UnitKind.CURRENCY,
                source_provider=quote.source_provider,
                source_identity=quote.source_identity,
            )
            market_age = _business_day_age(quote.observed_on, as_of)

        return FundamentalRecord(
            ticker=security.ticker,
            security_id=security.security_id,
            issuer_id=security.issuer_id,
            company_name=company.company_name,
            currency="USD",
            peer_group_id=company.sector,
            sector=company.sector,
            industry_group=company.industry_group,
            methodology=_methodology(company),
            fiscal_year_end=(annual_ends[0].isoformat()[5:] if annual_ends else None),
            data_as_of=as_of,
            fundamental_period_type=FundamentalPeriodType.TTM,
            fundamental_period_end=fundamental_end,
            market_age_trading_days=market_age,
            provider=self.PROVIDER,
            provider_identity=payload_identity,
            observations=tuple(observations),
        )
