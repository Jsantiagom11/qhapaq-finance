"""Offline, fail-closed promotion of a validated local SEC issuer corpus."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, TypeVar

from .financial_canonicalization import CanonicalizationEngine, IssuerProfile

if TYPE_CHECKING:
    from .analysis import CompanyIdentity


_ACCESSION = re.compile(r"^\d{10}-\d{2}-\d{6}$")
T_co = TypeVar("T_co", covariant=True)


class LocalSecCorpusError(ValueError):
    """A local issuer corpus is absent or fails its integrity contract."""


class Canonicalizer(Protocol[T_co]):
    def canonicalize(
        self,
        company: object,
        staged_evidence: Mapping[str, object],
        *,
        profile: IssuerProfile,
        source_identity: str,
    ) -> T_co: ...


@dataclass(frozen=True)
class LocalSecEvidence:
    """Validated inputs accepted by the financial canonicalization kernel."""

    companyfacts: Mapping[str, object]
    submissions: Mapping[str, object]
    selected_filing: Mapping[str, object]
    companyfacts_identity: str

    def staged(self) -> dict[str, object]:
        return {
            "companyfacts": self.companyfacts,
            "selected_filing": dict(self.selected_filing),
        }


class LocalSecCorpus:
    """Read one issuer corpus by resolved identity; this never performs HTTP."""

    def __init__(self, repository_root: str | Path = ".") -> None:
        self.root = Path(repository_root)

    def evidence(self, identity: CompanyIdentity) -> LocalSecEvidence:
        if identity.cik is None or not identity.cik.isdigit() or len(identity.cik) != 10:
            raise LocalSecCorpusError("local SEC corpus requires a normalized CIK")
        ticker = identity.ticker.strip().upper()
        issuer_root = self.root / "data/cache/sec_corpus_live" / ticker
        manifest = self._json(issuer_root / "manifest.json", "issuer manifest")
        if manifest.get("schema_version") != "sec-corpus-issuer-v1":
            raise LocalSecCorpusError("unsupported local SEC corpus schema")
        if manifest.get("ticker") != ticker or manifest.get("cik") != identity.cik:
            raise LocalSecCorpusError("local SEC corpus identity mismatch")

        companyfacts_record = manifest.get("companyfacts")
        companyfacts = self._artifact(issuer_root, companyfacts_record, "companyfacts")
        submissions = self._artifact(issuer_root, manifest.get("submissions"), "submissions")
        self._validate_companyfacts(companyfacts, identity.cik)
        self._validate_submissions(submissions, identity.cik)
        selected = self._selected_filing(manifest, submissions)
        self._validate_filing_artifacts(issuer_root, manifest, selected, ticker, identity.cik)
        assert isinstance(companyfacts_record, Mapping)
        companyfacts_path = companyfacts_record.get("path")
        assert isinstance(companyfacts_path, str)
        return LocalSecEvidence(
            companyfacts,
            submissions,
            selected,
            hashlib.sha256(
                (issuer_root / companyfacts_path).read_bytes()
            ).hexdigest(),
        )

    def canonicalize(
        self,
        identity: CompanyIdentity,
        *,
        profile: IssuerProfile,
        engine: Canonicalizer[T_co] | None = None,
    ) -> T_co:
        evidence = self.evidence(identity)
        canonicalizer: Canonicalizer[T_co] = (
            CanonicalizationEngine() if engine is None else engine  # type: ignore[assignment]
        )
        return canonicalizer.canonicalize(
            identity,
            evidence.staged(),
            profile=profile,
            source_identity=evidence.companyfacts_identity,
        )

    @staticmethod
    def _json(path: Path, label: str) -> dict[str, object]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LocalSecCorpusError(f"local SEC {label} is invalid") from exc
        if not isinstance(payload, dict):
            raise LocalSecCorpusError(f"local SEC {label} is invalid")
        return payload

    def _artifact(self, issuer_root: Path, record: object, label: str) -> dict[str, object]:
        if not isinstance(record, Mapping) or record.get("artifact_kind") != label:
            raise LocalSecCorpusError(f"local SEC {label} record is invalid")
        path_value = record.get("path")
        if not isinstance(path_value, str) or not path_value or Path(path_value).is_absolute():
            raise LocalSecCorpusError(f"local SEC {label} path is invalid")
        path = issuer_root / path_value
        if issuer_root.resolve() not in path.resolve().parents or not path.is_file():
            raise LocalSecCorpusError(f"local SEC {label} artifact is absent")
        checksum = record.get("sha256")
        if checksum is not None and (
            not isinstance(checksum, str)
            or hashlib.sha256(path.read_bytes()).hexdigest() != checksum
        ):
            raise LocalSecCorpusError(f"local SEC {label} checksum mismatch")
        return self._json(path, label)

    @staticmethod
    def _validate_companyfacts(payload: Mapping[str, object], cik: str) -> None:
        if str(payload.get("cik", "")).zfill(10) != cik or not isinstance(
            payload.get("facts"), Mapping
        ):
            raise LocalSecCorpusError("local SEC companyfacts identity mismatch")

    @staticmethod
    def _validate_submissions(payload: Mapping[str, object], cik: str) -> None:
        if str(payload.get("cik", "")).zfill(10) != cik:
            raise LocalSecCorpusError("local SEC submissions identity mismatch")
        filings = payload.get("filings")
        if not isinstance(filings, Mapping) or not isinstance(filings.get("recent"), Mapping):
            raise LocalSecCorpusError("local SEC submissions are invalid")

    def _selected_filing(
        self, manifest: Mapping[str, object], submissions: Mapping[str, object]
    ) -> dict[str, object]:
        selected_filings = manifest.get("selected_filings")
        selected = selected_filings.get("10-K") if isinstance(selected_filings, Mapping) else None
        if not isinstance(selected, Mapping):
            raise LocalSecCorpusError("local SEC original 10-K is absent")
        required = ("accession", "form", "filing_date", "report_date", "primary_document")
        if any(not isinstance(selected.get(key), str) or not selected[key] for key in required):
            raise LocalSecCorpusError("local SEC selected filing is invalid")
        if selected["form"] != "10-K" or not _ACCESSION.fullmatch(str(selected["accession"])):
            raise LocalSecCorpusError("local SEC selected filing is not an original 10-K")
        try:
            date.fromisoformat(str(selected["filing_date"]))
            date.fromisoformat(str(selected["report_date"]))
        except ValueError as exc:
            raise LocalSecCorpusError("local SEC selected filing dates are invalid") from exc
        recent = submissions["filings"]
        assert isinstance(recent, Mapping)
        recent = recent["recent"]
        assert isinstance(recent, Mapping)
        try:
            rows = zip(
                recent["accessionNumber"],
                recent["form"],
                recent["filingDate"],
                recent["reportDate"],
                recent["primaryDocument"],
                strict=True,
            )
        except KeyError as exc:
            raise LocalSecCorpusError("local SEC submissions are incomplete") from exc
        if not any(
            row
            == (
                selected["accession"],
                "10-K",
                selected["filing_date"],
                selected["report_date"],
                selected["primary_document"],
            )
            for row in rows
        ):
            raise LocalSecCorpusError("local SEC selected filing disagrees with submissions")
        return dict(selected)

    def _validate_filing_artifacts(
        self,
        issuer_root: Path,
        manifest: Mapping[str, object],
        selected: Mapping[str, object],
        ticker: str,
        cik: str,
    ) -> None:
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, list):
            raise LocalSecCorpusError("local SEC filing artifacts are invalid")
        primary = f"filings/{selected['accession']}/filing-artifact/{selected['primary_document']}"
        match = False
        for record in artifacts:
            if not isinstance(record, Mapping):
                raise LocalSecCorpusError("local SEC filing artifact record is invalid")
            path_value = record.get("path")
            if not isinstance(path_value, str):
                raise LocalSecCorpusError("local SEC filing artifact path is invalid")
            path = issuer_root / path_value
            if issuer_root.resolve() not in path.resolve().parents or not path.is_file():
                raise LocalSecCorpusError("local SEC filing artifact is absent")
            checksum = record.get("sha256")
            if not isinstance(checksum, str) or (
                hashlib.sha256(path.read_bytes()).hexdigest() != checksum
            ):
                raise LocalSecCorpusError("local SEC filing artifact checksum mismatch")
            if path_value == primary:
                match = (
                    record.get("ticker") == ticker
                    and record.get("cik") == cik
                    and record.get("accession") == selected["accession"]
                    and record.get("form") == "10-K"
                    and record.get("filing_date") == selected["filing_date"]
                    and record.get("report_date") == selected["report_date"]
                )
        if not match:
            raise LocalSecCorpusError("local SEC selected filing artifact is invalid")
