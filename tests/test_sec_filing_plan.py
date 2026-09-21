from __future__ import annotations

from pathlib import Path

import pytest

from qhapaq_finance.sec_acquisition import StagedSecResource
from qhapaq_finance.sec_canonical_gate import SecCanonicalReason
from qhapaq_finance.sec_evidence_provider import SecFilingDescriptor, SecSubmissionsBundle
from qhapaq_finance.sec_filing_plan import (
    FilingRequirementContext,
    plan_filing_fallback,
)


def _bundle() -> SecSubmissionsBundle:
    filings = (
        SecFilingDescriptor(
            "0000000123-26-000004", "10-Q/A", "2026-08-15", "2026-06-30", "q2a.htm", True
        ),
        SecFilingDescriptor(
            "0000000123-26-000003", "10-Q", "2026-07-30", "2026-06-30", "q2.htm", False
        ),
        SecFilingDescriptor(
            "0000000123-26-000002", "10-K/A", "2026-03-01", "2025-12-31", "fya.htm", True
        ),
        SecFilingDescriptor(
            "0000000123-26-000001", "10-K", "2026-02-01", "2025-12-31", "fy.htm", False
        ),
        SecFilingDescriptor(
            "0000000123-25-000003", "10-Q", "2025-07-30", "2025-06-30", "q2-prior.htm", False
        ),
    )
    staged = StagedSecResource(Path("submissions.bin"), Path("submissions.json"), "abc", 3)
    return SecSubmissionsBundle({}, staged, filings)


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        (
            SecCanonicalReason.MISSING_STANDARD_CONCEPT,
            (("0000000123-26-000001", "10-K"),),
        ),
        (
            SecCanonicalReason.EXTENSION_DISCOVERY_REQUIRED,
            (("0000000123-26-000001", "10-K"),),
        ),
        (
            SecCanonicalReason.REQUIRED_COMPONENT_MISSING,
            (("0000000123-26-000003", "10-Q"),),
        ),
        (
            SecCanonicalReason.AMBIGUOUS_CONTEXT,
            (("0000000123-26-000003", "10-Q"),),
        ),
        (
            SecCanonicalReason.STANDARD_CONCEPT_COVERAGE_GAP,
            (("0000000123-26-000003", "10-Q"),),
        ),
        (
            SecCanonicalReason.FILING_CONTEXT_REQUIRED,
            (("0000000123-26-000003", "10-Q"),),
        ),
    ],
)
def test_reason_mapping_is_deterministic_and_uses_original_filings(
    reason: SecCanonicalReason, expected: tuple[tuple[str, str], ...]
) -> None:
    first = plan_filing_fallback(reason, _bundle(), FilingRequirementContext())
    second = plan_filing_fallback(reason, _bundle(), FilingRequirementContext())

    assert first == second
    assert first is not None
    assert tuple((item.accession, item.form) for item in first.filings) == expected
    assert all(not item.amendment and not item.form.endswith("/A") for item in first.filings)
    assert first.artifact_surface == (
        "primary-document",
        "xbrl-instance",
        "issuer-schema",
        "label-linkbase",
        "presentation-linkbase",
        "calculation-linkbase",
        "FilingSummary.xml",
    )


def test_ttm_gap_selects_minimum_explicit_annual_and_comparable_ytd_set() -> None:
    context = FilingRequirementContext(
        annual_report_date="2025-12-31",
        current_ytd_report_date="2026-06-30",
        prior_ytd_report_date="2025-06-30",
    )

    plan = plan_filing_fallback(SecCanonicalReason.PERIOD_COVERAGE_GAP, _bundle(), context)

    assert plan is not None
    assert tuple((item.accession, item.form) for item in plan.filings) == (
        ("0000000123-26-000001", "10-K"),
        ("0000000123-26-000003", "10-Q"),
        ("0000000123-25-000003", "10-Q"),
    )
    assert len(plan.filings) == 3


@pytest.mark.parametrize(
    "reason",
    [
        SecCanonicalReason.CANONICAL_CONFLICT,
        SecCanonicalReason.MALFORMED_EVIDENCE,
        SecCanonicalReason.CANONICAL_INVARIANT,
    ],
)
def test_nonrepairable_reason_has_no_fallback_plan(reason: SecCanonicalReason) -> None:
    assert plan_filing_fallback(reason, _bundle(), FilingRequirementContext()) is None
