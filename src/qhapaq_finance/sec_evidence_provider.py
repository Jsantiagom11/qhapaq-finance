"""Typed, staging-only SEC payload provider."""

from __future__ import annotations

import json
import re
from datetime import date

from .evidence_orchestration import EvidenceRequirement
from .sec_acquisition import StagedSecResource, stage_sec_response
from .sec_client import SecClient, SecResponse

_ACCESSION = re.compile(r"^\d{10}-\d{2}-\d{6}$")


class SecArtifactKind:
    SUBMISSIONS = "SEC_SUBMISSIONS"
    COMPANY_FACTS = "SEC_COMPANY_FACTS"
    LATEST_10K = "SEC_LATEST_10K_METADATA"
    LATEST_10Q = "SEC_LATEST_10Q_METADATA"


class StructuredSecProvider:
    """Derives fixed SEC endpoints from a requirement's normalized CIK."""

    name = "SEC"

    def __init__(self, client: SecClient, staging_root: str = "data/raw") -> None:
        self.client, self.staging_root = client, staging_root

    def acquire(self, requirement: EvidenceRequirement) -> StagedSecResource:
        cik = requirement.company.cik
        if cik is None or len(cik) != 10 or not cik.isdigit():
            raise ValueError("SEC requirement requires normalized CIK")
        if requirement.artifact_kind == SecArtifactKind.COMPANY_FACTS:
            url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
            response = self.client.get(url)
            payload = self._json(response, "company facts")
            if str(payload.get("cik", "")).zfill(10) != cik or not isinstance(
                payload.get("facts"), dict
            ):
                raise ValueError("invalid SEC company facts payload")
            return stage_sec_response(
                url, response, self.staging_root, source_metadata=self._meta(requirement)
            )
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        response = self.client.get(url)
        filings = self._filings(self._json(response, "submissions"), cik)
        raw = stage_sec_response(
            url, response, self.staging_root, source_metadata=self._meta(requirement)
        )
        form = {SecArtifactKind.LATEST_10K: "10-K", SecArtifactKind.LATEST_10Q: "10-Q"}.get(
            requirement.artifact_kind
        )
        if requirement.artifact_kind == SecArtifactKind.SUBMISSIONS:
            return raw
        if form is None:
            raise ValueError("unsupported SEC artifact kind")
        filing = next((item for item in filings if item[1] == form), None)
        if filing is None:
            raise ValueError(f"SEC submissions has no {form}")
        accession, _, filing_date, report_date, document, amendment = filing
        discovery = json.dumps(
            {
                "schema_version": "sec-filing-discovery-v1",
                "cik": cik,
                "ticker": requirement.company.ticker,
                "artifact_kind": requirement.artifact_kind,
                "accession": accession,
                "form": form,
                "filing_date": filing_date,
                "report_date": report_date,
                "primary_document": document,
                "amendment": amendment,
            },
            sort_keys=True,
        ).encode()
        return stage_sec_response(
            url,
            SecResponse(200, {"Content-Type": "application/json"}, discovery),
            self.staging_root,
            source_metadata={**self._meta(requirement), "accession": accession, "form": form},
        )

    @staticmethod
    def _meta(requirement: EvidenceRequirement) -> dict[str, str]:
        return {
            "artifact_kind": requirement.artifact_kind,
            "ticker": requirement.company.ticker,
            "cik": requirement.company.cik or "",
        }

    @staticmethod
    def _json(response: SecResponse, label: str) -> dict[str, object]:
        try:
            payload = response.json()
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"malformed SEC {label} JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"invalid SEC {label} payload")
        return payload

    @staticmethod
    def _filings(
        payload: dict[str, object], cik: str
    ) -> tuple[tuple[str, str, str, str | None, str, bool], ...]:
        try:
            recent = payload["filings"]
            if not isinstance(recent, dict):
                raise ValueError
            recent = recent["recent"]
            if not isinstance(recent, dict):
                raise ValueError
            arrays = [
                recent[key]
                for key in (
                    "accessionNumber",
                    "form",
                    "filingDate",
                    "reportDate",
                    "primaryDocument",
                )
            ]
        except (KeyError, ValueError) as exc:
            raise ValueError("malformed SEC submissions JSON") from exc
        if (
            str(payload.get("cik", "")).zfill(10) != cik
            or any(not isinstance(x, list) for x in arrays)
            or len({len(x) for x in arrays}) != 1
        ):
            raise ValueError("contradictory SEC submissions payload")
        result, seen = [], set()
        for accession, form, filed, report, document in zip(*arrays, strict=True):
            if (
                not all(isinstance(x, str) for x in (accession, form, filed, document))
                or not _ACCESSION.fullmatch(accession)
                or accession in seen
            ):
                raise ValueError("invalid or duplicate SEC accession")
            seen.add(accession)
            date.fromisoformat(filed)
            if report:
                date.fromisoformat(report)
            if form in {"10-K", "10-K/A", "10-Q", "10-Q/A"}:
                result.append(
                    (accession, form, filed, report or None, document, form.endswith("/A"))
                )
        return tuple(sorted(result, key=lambda item: (item[2], item[0]), reverse=True))
