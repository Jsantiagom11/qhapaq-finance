"""Deterministic, network-free planning for one filing-native fallback phase."""

from __future__ import annotations

from dataclasses import dataclass

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


def plan_filing_fallback(
    reason: SecCanonicalReason,
    submissions_bundle: SecSubmissionsBundle,
    requirement_context: FilingRequirementContext,
) -> FilingFallbackPlan | None:
    """Select the minimum original filing set implied by a typed SEC gap."""

    originals = tuple(
        filing
        for filing in submissions_bundle.filings
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
