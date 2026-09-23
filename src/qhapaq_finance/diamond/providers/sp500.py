"""Cached S&P 500 membership and issuer metadata acquisition."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date
from html.parser import HTMLParser
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..cache import DiamondCache
from ..contracts import SecurityRef


class Sp500ProviderError(RuntimeError):
    """Raised when S&P 500 membership cannot be acquired or validated."""


class Sp500TextClient(Protocol):
    def get_text(self, url: str) -> str: ...


class WikipediaTextClient:
    """Small injectable HTTP boundary for public index membership evidence."""

    def __init__(self, *, timeout: float = 30.0) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self._timeout = timeout

    def get_text(self, url: str) -> str:
        request = Request(
            url,
            headers={"User-Agent": "QhapaqFinance/0.2 index-membership"},
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                return response.read().decode("utf-8")
        except (HTTPError, URLError, UnicodeDecodeError, OSError) as exc:
            raise Sp500ProviderError("SP500_UNIVERSE_REQUEST_FAILED") from exc


@dataclass(frozen=True, slots=True)
class Sp500Company:
    ticker: str
    cik: str
    company_name: str
    sector: str
    industry_group: str


class _ConstituentsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._cell_parts: list[str] = []
        self._row: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "table" and attributes.get("id") == "constituents":
            self._in_table = True
        elif self._in_table and tag == "tr":
            self._in_row = True
            self._row = []
        elif self._in_row and tag in {"th", "td"}:
            self._in_cell = True
            self._cell_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._in_cell and tag in {"th", "td"}:
            value = " ".join("".join(self._cell_parts).split())
            self._row.append(value)
            self._in_cell = False
            self._cell_parts = []
        elif self._in_row and tag == "tr":
            if self._row:
                self.rows.append(self._row)
            self._in_row = False
            self._row = []
        elif self._in_table and tag == "table":
            self._in_table = False


_TICKER = re.compile(r"^[A-Z0-9][A-Z0-9.-]*$")
_EXPECTED_COLUMNS = {
    "Symbol",
    "Security",
    "GICS Sector",
    "GICS Sub-Industry",
    "CIK",
}


def _validate_company(
    company: Sp500Company,
    index: int,
) -> Sp500Company:
    values = (
        company.ticker,
        company.cik,
        company.company_name,
        company.sector,
        company.industry_group,
    )
    if not all(isinstance(value, str) for value in values):
        raise Sp500ProviderError(f"SP500_CONSTITUENT_ROW_INVALID:{index}")

    ticker = company.ticker.strip().upper()
    cik_raw = company.cik.strip()
    company_name = company.company_name.strip()
    sector = company.sector.strip()
    industry_group = company.industry_group.strip()

    if (
        not _TICKER.fullmatch(ticker)
        or not cik_raw.isdigit()
        or len(cik_raw) > 10
        or not company_name
        or not sector
        or not industry_group
    ):
        raise Sp500ProviderError(f"SP500_CONSTITUENT_ROW_INVALID:{index}")

    return Sp500Company(
        ticker=ticker,
        cik=cik_raw.zfill(10),
        company_name=company_name,
        sector=sector,
        industry_group=industry_group,
    )


def _validate_companies(
    companies: tuple[Sp500Company, ...],
) -> tuple[Sp500Company, ...]:
    validated: list[Sp500Company] = []
    seen_tickers: set[str] = set()

    for index, company in enumerate(companies):
        normalized = _validate_company(company, index)

        if normalized.ticker in seen_tickers:
            raise Sp500ProviderError("SP500_DUPLICATE_TICKER")

        seen_tickers.add(normalized.ticker)
        validated.append(normalized)

    if not validated:
        raise Sp500ProviderError("SP500_UNIVERSE_EMPTY")

    return tuple(validated)


def _parse_constituents(html: str) -> tuple[Sp500Company, ...]:
    parser = _ConstituentsParser()
    parser.feed(html)
    if not parser.rows:
        raise Sp500ProviderError("SP500_CONSTITUENTS_TABLE_MISSING")

    headers = parser.rows[0]
    if not _EXPECTED_COLUMNS.issubset(headers):
        raise Sp500ProviderError("SP500_CONSTITUENTS_SCHEMA_INVALID")

    positions = {name: headers.index(name) for name in _EXPECTED_COLUMNS}

    companies: list[Sp500Company] = []
    for index, row in enumerate(parser.rows[1:]):
        if len(row) < len(headers):
            raise Sp500ProviderError(f"SP500_CONSTITUENT_ROW_INVALID:{index}")

        companies.append(
            Sp500Company(
                ticker=row[positions["Symbol"]],
                cik=row[positions["CIK"]],
                company_name=row[positions["Security"]],
                sector=row[positions["GICS Sector"]],
                industry_group=row[positions["GICS Sub-Industry"]],
            )
        )

    return _validate_companies(tuple(companies))


def _companies_from_payload(
    payload: object,
) -> tuple[Sp500Company, ...]:
    if not isinstance(payload, list):
        raise Sp500ProviderError("SP500_CACHE_SCHEMA_INVALID")

    companies: list[Sp500Company] = []

    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise Sp500ProviderError(f"SP500_CACHE_ROW_INVALID:{index}")

        try:
            ticker = item["ticker"]
            cik = item["cik"]
            company_name = item["company_name"]
            sector = item["sector"]
            industry_group = item["industry_group"]
        except KeyError as exc:
            raise Sp500ProviderError(f"SP500_CACHE_ROW_INVALID:{index}") from exc

        if not all(
            isinstance(value, str)
            for value in (
                ticker,
                cik,
                company_name,
                sector,
                industry_group,
            )
        ):
            raise Sp500ProviderError(f"SP500_CACHE_ROW_INVALID:{index}")

        companies.append(
            Sp500Company(
                ticker=ticker,
                cik=cik,
                company_name=company_name,
                sector=sector,
                industry_group=industry_group,
            )
        )

    return _validate_companies(tuple(companies))


class Sp500UniverseProvider:
    """Resolve real S&P 500 members with ticker, CIK, and GICS metadata."""

    SOURCE_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    PROVIDER = "wikipedia-sp500"

    def __init__(
        self,
        *,
        client: Sp500TextClient | None,
        cache: DiamondCache,
        refresh: bool = False,
    ) -> None:
        self._client = client
        self._cache = cache
        self._refresh = refresh
        self._metadata: dict[str, Sp500Company] = {}
        self.provider_requests = 0
        self.cache_hits = 0
        self.cache_misses = 0

    def universe(self, universe_id: str, as_of: date) -> tuple[SecurityRef, ...]:
        if universe_id.casefold() != "sp500":
            raise Sp500ProviderError("UNSUPPORTED_UNIVERSE")

        companies: tuple[Sp500Company, ...] | None = None
        if not self._refresh:
            cached = self._cache.load(self.SOURCE_URL)
            if cached is not None and cached.data_as_of == as_of:
                if cached.provider != self.PROVIDER:
                    raise Sp500ProviderError("SP500_CACHE_PROVIDER_MISMATCH")
                companies = _companies_from_payload(cached.payload)
                self.cache_hits += 1

        if companies is None:
            self.cache_misses += 1
            if self._client is None:
                raise Sp500ProviderError("SP500_CACHE_MISS_REQUIRES_NETWORK")
            self.provider_requests += 1
            companies = _parse_constituents(self._client.get_text(self.SOURCE_URL))
            self._cache.store(
                self.SOURCE_URL,
                provider=self.PROVIDER,
                data_as_of=as_of,
                payload=[asdict(item) for item in companies],
            )

        self._metadata = {item.ticker: item for item in companies}
        return tuple(
            SecurityRef(
                ticker=item.ticker,
                security_id=f"sp500:{item.ticker}",
                issuer_id=f"sec-cik:{item.cik}",
            )
            for item in companies
        )

    def metadata(self, ticker: str) -> Sp500Company:
        try:
            return self._metadata[ticker.strip().upper()]
        except KeyError as exc:
            raise Sp500ProviderError("SP500_METADATA_UNAVAILABLE") from exc
