"""Deterministic, network-free planning for one filing-native fallback phase."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .financial_canonicalization import RawFact
from .sec_canonical_gate import SecCanonicalReason
from .sec_evidence_provider import SecFilingDescriptor, SecSubmissionsBundle

FILING_ARTIFACT_SURFACE = (
    "primary-document",
    "xbrl-instance",
    "issuer-schema",
    "label-linkbase",
    "presentation-linkbase",
    "calculation-linkbase",
    "FilingSummary.xml",
)


@dataclass(frozen=True)
class FilingRequirementContext:
    annual_report_date: str | None = None
    current_ytd_report_date: str | None = None
    prior_ytd_report_date: str | None = None


@dataclass(frozen=True)
class FilingFallbackPlan:
    reason: SecCanonicalReason
    filings: tuple[SecFilingDescriptor, ...]
    artifact_surface: tuple[str, ...] = FILING_ARTIFACT_SURFACE


_ANNUAL_ONLY = frozenset(
    {
        SecCanonicalReason.MISSING_STANDARD_CONCEPT,
        SecCanonicalReason.EXTENSION_DISCOVERY_REQUIRED,
    }
)
_LATEST_PERIODS = frozenset(
    {
        SecCanonicalReason.REQUIRED_COMPONENT_MISSING,
        SecCanonicalReason.AMBIGUOUS_CONTEXT,
        SecCanonicalReason.FILING_CONTEXT_REQUIRED,
        SecCanonicalReason.STANDARD_CONCEPT_COVERAGE_GAP,
    }
)


def filing_requirement_context(
    filings: tuple[SecFilingDescriptor, ...],
    raw_facts: tuple[RawFact, ...],
) -> FilingRequirementContext:
    """Resolve exact-period targets using the eligible originals and their fiscal identities."""
    originals = tuple(
        filing
        for filing in filings
        if not filing.amendment
        and filing.form in {"10-K", "10-Q"}
        and filing.report_date is not None
    )
    annual = next((filing for filing in originals if filing.form == "10-K"), None)
    quarters = tuple(filing for filing in originals if filing.form == "10-Q")
    current = quarters[0] if quarters else None
    prior: SecFilingDescriptor | None = None
    if current is not None:
        identities = filing_fact_identities(raw_facts)
        current_identity = identities.get(current.accession)
        if current_identity is not None:
            current_year, current_period = current_identity
            prior = next(
                (
                    filing
                    for filing in quarters[1:]
                    if identities.get(filing.accession) == (current_year - 1, current_period)
                ),
                None,
            )
        if prior is None and current.report_date is not None:
            current_date = date.fromisoformat(current.report_date)
            prior = next(
                (
                    filing
                    for filing in quarters[1:]
                    if filing.report_date is not None
                    and date.fromisoformat(filing.report_date).year == current_date.year - 1
                ),
                None,
            )
    return FilingRequirementContext(
        annual_report_date=annual.report_date if annual is not None else None,
        current_ytd_report_date=current.report_date if current is not None else None,
        prior_ytd_report_date=prior.report_date if prior is not None else None,
    )


def filing_fact_identities(
    raw_facts: tuple[RawFact, ...],
) -> dict[str, tuple[int, str]]:
    """Return the unambiguous fiscal year and period of each observed accession."""
    candidates: dict[str, set[tuple[int, str]]] = {}
    for fact in raw_facts:
        if fact.fiscal_year > 0 and fact.fiscal_period in {"FY", "Q1", "Q2", "Q3"}:
            candidates.setdefault(fact.accession, set()).add((fact.fiscal_year, fact.fiscal_period))
    return {
        accession: next(iter(identities))
        for accession, identities in candidates.items()
        if len(identities) == 1
    }


def plan_filing_fallback(
    reason: SecCanonicalReason,
    submissions_bundle: SecSubmissionsBundle,
    requirement_context: FilingRequirementContext,
) -> FilingFallbackPlan | None:
    """Plan fallback from the filings in a staged submissions bundle."""
    return select_filing_fallback(reason, submissions_bundle.filings, requirement_context)


def select_filing_fallback(
    reason: SecCanonicalReason,
    eligible_filings: tuple[SecFilingDescriptor, ...],
    requirement_context: FilingRequirementContext,
) -> FilingFallbackPlan | None:
    """Select the minimum original filing set implied by a typed SEC gap."""

    originals = tuple(
        filing
        for filing in eligible_filings
        if not filing.amendment and filing.form in {"10-K", "10-Q"}
    )

    if reason is SecCanonicalReason.PERIOD_COVERAGE_GAP:
        dates = (
            ("10-K", requirement_context.annual_report_date),
            ("10-Q", requirement_context.current_ytd_report_date),
            ("10-Q", requirement_context.prior_ytd_report_date),
        )
        if any(report_date is None for _, report_date in dates):
            return None
        selected = tuple(
            _filing(originals, form=form, report_date=report_date) for form, report_date in dates
        )
    elif reason in _ANNUAL_ONLY:
        selected = (_filing(originals, form="10-K"),)
    elif reason in _LATEST_PERIODS:
        selected = (_filing(originals, form="10-Q"),)
    else:
        return None

    if any(filing is None for filing in selected):
        return None
    filings = tuple(filing for filing in selected if filing is not None)
    if len({filing.accession for filing in filings}) != len(filings):
        return None
    return FilingFallbackPlan(reason, filings)


def _filing(
    filings: tuple[SecFilingDescriptor, ...],
    *,
    form: str,
    report_date: str | None = None,
) -> SecFilingDescriptor | None:
    return next(
        (
            filing
            for filing in filings
            if filing.form == form and (report_date is None or filing.report_date == report_date)
        ),
        None,
    )
