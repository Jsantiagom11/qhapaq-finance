"""Point-in-time filing planning from captured SEC aggregate evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

from .financial_canonicalization import extract_company_facts
from .sec_canonical_gate import SecCanonicalGateState, evaluate_sec_canonical_gate
from .sec_evidence_provider import StructuredSecProvider
from .sec_filing_plan import filing_requirement_context, select_filing_fallback


def _issuer_payload(path: Path, *, cik: str, label: str) -> tuple[dict[str, object], str]:
    raw = path.read_bytes()
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise ValueError(f"{label} must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    if str(payload.get("cik", "")).zfill(10) != cik:
        raise ValueError(f"{label} CIK does not match {cik}")
    return payload, hashlib.sha256(raw).hexdigest()


def plan_historical_filings(
    cik: str,
    *,
    as_of: date,
    submissions_path: Path,
    companyfacts_path: Path,
) -> dict[str, object]:
    """Evaluate the SEC gate and plan fallback from evidence available by the cutoff."""
    if not (1 <= len(cik) <= 10 and cik.isascii() and cik.isdecimal() and int(cik) > 0):
        raise ValueError("CIK must be a positive number of up to 10 digits")
    cik = cik.zfill(10)
    submissions, submissions_sha256 = _issuer_payload(
        submissions_path,
        cik=cik,
        label="submissions",
    )
    companyfacts, companyfacts_sha256 = _issuer_payload(
        companyfacts_path,
        cik=cik,
        label="companyfacts",
    )
    filings = tuple(
        filing
        for filing in StructuredSecProvider.parse_filings(submissions, cik)
        if date.fromisoformat(filing.filing_date) <= as_of
    )
    facts = extract_company_facts(companyfacts, source_identity=companyfacts_sha256, as_of=as_of)
    gate = evaluate_sec_canonical_gate(facts)
    fallback = None
    if gate.state is SecCanonicalGateState.GAP and gate.reason is not None:
        fallback = select_filing_fallback(
            gate.reason,
            filings,
            filing_requirement_context(filings, facts),
        )
    return {
        "schema_version": "sec-historical-filing-plan-v1",
        "cik": cik,
        "as_of": as_of.isoformat(),
        "state": gate.state.value,
        "reason": gate.reason.value if gate.reason is not None else None,
        "eligible_facts": len(facts),
        "eligible_filings": len(filings),
        "input_sha256": {"submissions": submissions_sha256, "companyfacts": companyfacts_sha256},
        "fallback": (
            {
                "filings": [asdict(filing) for filing in fallback.filings],
                "artifact_surface": list(fallback.artifact_surface),
            }
            if fallback is not None
            else None
        ),
    }
