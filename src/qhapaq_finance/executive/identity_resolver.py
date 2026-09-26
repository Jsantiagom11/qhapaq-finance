"""Authoritative Diamond identity handoff for Executive analysis."""

from __future__ import annotations

from collections.abc import Sequence

from qhapaq_finance.company_resolver import (
    CompanyProvenance,
    RefreshableSymbolResolver,
    ResolvedCompany,
)
from qhapaq_finance.diamond.engine import DiamondResult
from qhapaq_finance.sec_client import SecClient

_DIAMOND_PROVENANCE = CompanyProvenance(
    source_url="diamond://sec-first/security-ref",
    fetched_at=None,
    raw_sha256=None,
    raw_byte_size=None,
)


def _authoritative_company(
    candidate: DiamondResult,
) -> ResolvedCompany | None:
    if getattr(candidate, "provider", None) != "sec-first":
        return None

    source_security = getattr(candidate, "source_security", None)
    if source_security is None:
        return None

    if source_security.ticker != candidate.ticker:
        return None

    prefix = "sec-cik:"
    issuer_id = source_security.issuer_id
    if not issuer_id.startswith(prefix):
        return None

    cik = issuer_id[len(prefix) :]
    if not cik or not cik.isdigit():
        return None

    return ResolvedCompany(
        ticker=candidate.ticker,
        company_name=candidate.company_name,
        cik=cik,
        exchange=None,
        provenance=_DIAMOND_PROVENANCE,
    )


class DiamondIdentityResolver:
    """Resolve exact Diamond Top-N identity before legacy fallback."""

    def __init__(
        self,
        candidates: Sequence[DiamondResult],
        fallback: RefreshableSymbolResolver,
    ) -> None:
        self._fallback = fallback
        self._authoritative: dict[str, ResolvedCompany] = {}

        for candidate in candidates:
            resolved = _authoritative_company(candidate)
            if resolved is not None:
                self._authoritative[
                    candidate.ticker.strip().upper()
                ] = resolved

    def resolve(self, ticker: str) -> ResolvedCompany | None:
        normalized = ticker.strip().upper()
        resolved = self._authoritative.get(normalized)
        if resolved is not None:
            return resolved
        return self._fallback.resolve(normalized)

    def refresh(self, client: SecClient) -> int:
        return self._fallback.refresh(client)
