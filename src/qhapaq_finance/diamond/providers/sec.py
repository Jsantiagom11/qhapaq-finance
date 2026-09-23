"""SEC-first fundamental provider for broad Diamond Funnel discovery."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from typing import Protocol

from qhapaq_finance.sec_client import SecResponse

from ..cache import DiamondCache
from ..contracts import (
    FiscalSlot,
    FundamentalObservation,
    FundamentalRecord,
    Methodology,
    PeriodKind,
    SecurityRef,
    UnitKind,
)
from .market import BatchMarketProvider, MarketProviderError, MarketQuote
from .sec_canonical import (
    CanonicalIssuerCache,
    CanonicalIssuerSnapshot,
    canonicalize_issuer,
)
from .sec_evidence import SecEvidenceStore
from .sp500 import Sp500Company


class SecFirstProviderError(RuntimeError):
    """Raised when SEC-first evidence cannot be mapped safely."""


class UniverseMetadataProvider(Protocol):
    provider_requests: int
    cache_hits: int
    cache_misses: int

    def universe(self, universe_id: str, as_of: date) -> tuple[SecurityRef, ...]: ...

    def metadata(self, ticker: str) -> Sp500Company: ...


class SecHttpClient(Protocol):
    def get(
        self,
        url: str,
        *,
        request_headers: Mapping[str, str] | None = None,
        accepted_statuses: frozenset[int] = frozenset(),
    ) -> SecResponse: ...


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


def _counter(provider: object | None, name: str) -> int:
    value = getattr(provider, name, 0)
    return value if isinstance(value, int) else 0


class SecFirstProvider:
    """Compose issuer SEC accounting with current security metadata and market data."""

    PROVIDER = "sec-first"

    def __init__(
        self,
        *,
        universe_provider: UniverseMetadataProvider,
        market_provider: BatchMarketProvider | None,
        evidence_store: SecEvidenceStore | None = None,
        canonical_cache: CanonicalIssuerCache | None = None,
        split_provider: object | None = None,
        refresh: bool = False,
        sec_client: SecHttpClient | None = None,
        sec_cache: DiamondCache | None = None,
    ) -> None:
        using_legacy_inputs = sec_client is not None or sec_cache is not None
        using_canonical_inputs = evidence_store is not None or canonical_cache is not None
        if using_legacy_inputs and using_canonical_inputs:
            raise TypeError("SEC_PROVIDER_INPUTS_CONFLICT")
        if using_legacy_inputs:
            if sec_cache is None:
                raise TypeError("SEC_CACHE_REQUIRED")
            evidence_store = SecEvidenceStore(
                root=sec_cache.root,
                client=sec_client,
                legacy_cache=sec_cache,
            )
            canonical_cache = CanonicalIssuerCache(
                DiamondCache(sec_cache.root.parent / "canonical")
            )
        if evidence_store is None or canonical_cache is None:
            raise TypeError("SEC_EVIDENCE_AND_CANONICAL_CACHE_REQUIRED")

        self._universe_provider = universe_provider
        self.evidence_store = evidence_store
        self.canonical_cache = canonical_cache
        self._market_provider = market_provider
        self._split_provider = split_provider
        self._refresh = refresh

    @property
    def provider_requests(self) -> int:
        return sum(
            _counter(provider, "provider_requests")
            for provider in (
                self._universe_provider,
                self.evidence_store,
                self._market_provider,
                self._split_provider,
            )
        )

    @property
    def cache_hits(self) -> int:
        return sum(
            _counter(provider, "cache_hits")
            for provider in (
                self._universe_provider,
                self.evidence_store,
                self.canonical_cache,
                self._market_provider,
                self._split_provider,
            )
        )

    @property
    def cache_misses(self) -> int:
        return sum(
            _counter(provider, "cache_misses")
            for provider in (
                self._universe_provider,
                self.evidence_store,
                self.canonical_cache,
                self._market_provider,
                self._split_provider,
            )
        )

    def universe(self, universe_id: str, as_of: date) -> tuple[SecurityRef, ...]:
        return self._universe_provider.universe(universe_id, as_of)

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

        snapshots_by_cik: dict[str, CanonicalIssuerSnapshot | None] = {}
        records: list[FundamentalRecord] = []
        for security in securities:
            cik = self._cik(security)
            if cik not in snapshots_by_cik:
                snapshots_by_cik[cik] = self._issuer_snapshot(
                    security.issuer_id,
                    cik=cik,
                    as_of=as_of,
                    history_years=history_years,
                )
            snapshot = snapshots_by_cik[cik]
            if snapshot is None:
                continue
            records.append(
                self._build_record(
                    security,
                    company=self._universe_provider.metadata(security.ticker),
                    snapshot=snapshot,
                    quote=quotes.get(security.ticker),
                    as_of=as_of,
                )
            )
        return tuple(records)

    @staticmethod
    def _cik(security: SecurityRef) -> str:
        prefix = "sec-cik:"
        if not security.issuer_id.startswith(prefix):
            raise SecFirstProviderError("SEC_ISSUER_ID_INVALID")
        cik = security.issuer_id.removeprefix(prefix)
        if not cik:
            raise SecFirstProviderError("SEC_ISSUER_ID_INVALID")
        return cik

    def _issuer_snapshot(
        self,
        issuer_id: str,
        *,
        cik: str,
        as_of: date,
        history_years: int,
    ) -> CanonicalIssuerSnapshot | None:
        resolved = self.evidence_store.resolve(cik, as_of, refresh=self._refresh)
        revision = resolved.manifest.evidence_revision_sha256
        snapshot = self.canonical_cache.load(
            issuer_id=issuer_id,
            as_of=as_of,
            history_years=history_years,
            evidence_revision_sha256=revision,
        )
        if snapshot is not None:
            return snapshot

        facts = (
            resolved.facts
            if resolved.facts is not None
            else self.evidence_store.load_facts(resolved.manifest)
        )
        snapshot = canonicalize_issuer(
            issuer_id=issuer_id,
            cik=resolved.manifest.cik,
            as_of=as_of,
            history_years=history_years,
            evidence_revision_sha256=revision,
            facts=facts,
        )
        if snapshot is None:
            return None
        return self.canonical_cache.store(snapshot)

    def _build_record(
        self,
        security: SecurityRef,
        *,
        company: Sp500Company,
        snapshot: CanonicalIssuerSnapshot,
        quote: MarketQuote | None,
        as_of: date,
    ) -> FundamentalRecord:
        observations = list(snapshot.observations)
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
            if market_cap is not None:
                observations.append(
                    FundamentalObservation(
                        metric_id="market_cap",
                        fiscal_slot=FiscalSlot.LATEST,
                        value=market_cap,
                        period_start=None,
                        period_end=quote.observed_on,
                        period_kind=PeriodKind.INSTANT,
                        unit_kind=UnitKind.CURRENCY,
                        source_provider=quote.source_provider,
                        source_identity=quote.source_identity,
                    )
                )
            market_age = _business_day_age(quote.observed_on, as_of)

        source_identity = f"sec-evidence:{snapshot.evidence_revision_sha256}"
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
            fiscal_year_end=snapshot.fiscal_year_end,
            data_as_of=as_of,
            fundamental_period_type=snapshot.fundamental_period_type,
            fundamental_period_end=snapshot.fundamental_period_end,
            market_age_trading_days=market_age,
            provider=self.PROVIDER,
            provider_identity=source_identity,
            observations=tuple(observations),
        )
