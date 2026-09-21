"""One-time, SEC-only export of an offline canonicalization source corpus.

This module is deliberately not used by analysis.  It is an explicit fixture
builder: callers provide a :class:`SecClient`, source responses are staged via
``stage_sec_response``, and only validated bytes are exported under ``tests``.
"""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .company_resolver import CompanyResolver, SymbolResolver
from .sec_acquisition import (
    ImmutableArtifactConflictError,
    _write_new_atomically,
    stage_sec_response,
)
from .sec_client import SecClient, SecResponse

_ISSUER_CIKS = {
    "AAPL": "0000320193",
    "QCOM": "0000804328",
    "NVDA": "0001045810",
    "COST": "0000909832",
    "AMZN": "0001018724",
    "VRTX": "0000875320",
}
_ACCESSION = re.compile(r"^\d{10}-\d{2}-\d{6}$")
_XBRL_SUFFIX = re.compile(r"(?:\.xsd|\.xml)$", re.IGNORECASE)
_ROOT_SCHEMA_VERSION = "sec-corpus-v2"
_ISSUER_SCHEMA_VERSION = "sec-corpus-issuer-v1"


@dataclass(frozen=True)
class Filing:
    accession: str
    form: str
    filing_date: str
    report_date: str | None
    primary_document: str


class FilingDescriptor(Protocol):
    """The filing fields needed to export an already selected SEC filing."""

    @property
    def accession(self) -> str: ...

    @property
    def form(self) -> str: ...

    @property
    def filing_date(self) -> str: ...

    @property
    def report_date(self) -> str | None: ...

    @property
    def primary_document(self) -> str: ...


def reconcile_sec_corpus_manifest(
    *,
    corpus_root: str | Path = "tests/fixtures/sec_corpus",
    tickers: tuple[str, ...] = tuple(_ISSUER_CIKS),
) -> dict[str, Any]:
    """Build the root registry from validated, already-frozen issuer manifests.

    This is deliberately offline: directory names are only locations to inspect,
    never evidence of membership.  A version-2 registry is immutable once
    written; a different issuer-manifest identity requires an explicit corpus
    version change rather than silently changing the corpus identity.
    """
    if len(tickers) != len(_ISSUER_CIKS) or set(tickers) != set(_ISSUER_CIKS):
        raise ValueError("root corpus reconciliation requires exactly the configured issuers")

    root = Path(corpus_root)
    entries = [
        _validated_issuer_registry_entry(root, ticker, _ISSUER_CIKS[ticker])
        for ticker in _ISSUER_CIKS
    ]
    manifest_path = root / "manifest.json"
    existing = _read_existing_root_manifest(manifest_path)
    created_at = existing.get("created_at") if existing else _utc_now()
    if not isinstance(created_at, str):
        raise ImmutableArtifactConflictError(f"invalid existing corpus manifest: {manifest_path}")
    manifest = {
        "schema_version": _ROOT_SCHEMA_VERSION,
        "created_at": created_at,
        "issuers": entries,
    }
    content = _canonical_json_bytes(manifest)
    if existing:
        existing_content = manifest_path.read_bytes()
        if existing.get("schema_version") == _ROOT_SCHEMA_VERSION:
            if existing_content != content:
                raise ImmutableArtifactConflictError(
                    "root corpus identity changed; require an explicit corpus-version update"
                )
            return manifest
        _validate_legacy_root_for_upgrade(existing, entries)
        _replace_root_manifest_for_schema_upgrade(manifest_path, content)
        return manifest

    _write_new_atomically(manifest_path, content)
    return manifest


def build_sec_corpus(
    client: SecClient,
    *,
    corpus_root: str | Path = "tests/fixtures/sec_corpus",
    staging_root: str | Path = "data/raw/sec_corpus_staging",
    tickers: tuple[str, ...] = tuple(_ISSUER_CIKS),
    resolver: SymbolResolver | None = None,
) -> dict[str, Any]:
    """Acquire the fixed issuer corpus using only ``client`` for HTTP traffic.

    Existing files are immutable: equal content is reused and divergent content
    raises before any replacement.  A partially failed issuer never receives a
    manifest, so it cannot look like a complete frozen fixture.
    """
    root, staging = Path(corpus_root), Path(staging_root)
    active_resolver = resolver or CompanyResolver()
    issuers: list[dict[str, Any]] = []

    for requested_ticker in tickers:
        resolved = active_resolver.resolve(requested_ticker)
        if resolved is None:
            raise ValueError(
                f"ticker cannot be resolved from cached SEC company reference: {requested_ticker}"
            )

        ticker = resolved.ticker
        cik = resolved.cik
        issuer_root = root / ticker
        submissions, submission_record = _fetch_json(
            client,
            staging,
            issuer_root,
            ticker,
            cik,
            "submissions",
            f"https://data.sec.gov/submissions/CIK{cik}.json",
        )
        _validate_submissions(submissions, cik, ticker)
        facts, facts_record = _fetch_json(
            client,
            staging,
            issuer_root,
            ticker,
            cik,
            "companyfacts",
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
        )
        _validate_companyfacts(facts, cik)
        filings = _filings(submissions)
        selected: dict[str, Filing | None] = {
            "10-K": next((item for item in filings if item.form == "10-K"), None),
            "10-Q": next((item for item in filings if item.form == "10-Q"), None),
        }
        filing_records: list[dict[str, Any]] = []
        for filing in selected.values():
            if filing is not None:
                filing_records.extend(
                    _export_filing(client, staging, issuer_root, ticker, cik, filing)
                )
        amendments = [_filing_dict(item) for item in filings if item.form in {"10-K/A", "10-Q/A"}]
        issuer = {
            "schema_version": "sec-corpus-issuer-v1",
            "ticker": ticker,
            "cik": cik,
            "submissions": submission_record,
            "companyfacts": facts_record,
            "selected_filings": {
                key: _filing_dict(value) if value else None for key, value in selected.items()
            },
            "amendments_discovered": amendments,
            "artifacts": filing_records,
            "sufficiency": _sufficiency(filing_records),
        }
        _write_json_immutable(issuer_root / "manifest.json", issuer)
        issuers.append(issuer)
    manifest = {
        "schema_version": "sec-corpus-v1",
        "created_at": _existing_created_at(root / "manifest.json") or _utc_now(),
        "issuers": [
            {
                "ticker": issuer["ticker"],
                "cik": issuer["cik"],
                "manifest": f"{issuer['ticker']}/manifest.json",
                "selected_filings": issuer["selected_filings"],
                "sufficiency": issuer["sufficiency"],
            }
            for issuer in issuers
        ],
    }
    is_full_fixed_corpus = len(tickers) == len(_ISSUER_CIKS) and set(tickers) == set(_ISSUER_CIKS)
    root_manifest_path = root / "manifest.json"

    if is_full_fixed_corpus or not root_manifest_path.exists():
        _write_json_immutable(root_manifest_path, manifest)

    return manifest


def _fetch_json(
    client: SecClient, staging: Path, issuer_root: Path, ticker: str, cik: str, kind: str, url: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    response = client.get(url)
    payload = _json(response, kind)
    record = _stage_validate_export(
        client, staging, issuer_root, ticker, cik, kind, url, response, None, None, "json"
    )
    return payload, record


def _export_filing(
    client: SecClient,
    staging: Path,
    issuer_root: Path,
    ticker: str,
    cik: str,
    filing: FilingDescriptor,
) -> list[dict[str, Any]]:
    accession_id = filing.accession.replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_id}"
    index_url = f"{base}/index.json"
    index_response = client.get(index_url)
    index = _json(index_response, "filing index")
    names = _validate_index(index, filing)
    records = [
        _stage_validate_export(
            client,
            staging,
            issuer_root,
            ticker,
            cik,
            "filing-index",
            index_url,
            index_response,
            filing,
            "index.json",
            "json",
        )
    ]
    wanted = {filing.primary_document}
    wanted.update(name for name in names if _XBRL_SUFFIX.search(name))
    # FilingSummary.xml makes the SEC rendering/report taxonomy discoverable.
    if "FilingSummary.xml" in names:
        wanted.add("FilingSummary.xml")
    for name in sorted(wanted):
        url = f"{base}/{name}"
        response = client.get(url)
        extension = "xml" if name.lower().endswith((".xml", ".xsd")) else "html"
        records.append(
            _stage_validate_export(
                client,
                staging,
                issuer_root,
                ticker,
                cik,
                "filing-artifact",
                url,
                response,
                filing,
                name,
                extension,
            )
        )
    return records


def export_sec_filing(
    client: SecClient,
    *,
    staging_root: str | Path,
    issuer_root: str | Path,
    ticker: str,
    cik: str,
    filing: FilingDescriptor,
) -> list[dict[str, Any]]:
    """Acquire one explicit filing descriptor without refetching SEC aggregates."""

    return _export_filing(
        client,
        Path(staging_root),
        Path(issuer_root),
        ticker,
        cik,
        filing,
    )


def _stage_validate_export(
    client: SecClient,
    staging: Path,
    issuer_root: Path,
    ticker: str,
    cik: str,
    kind: str,
    url: str,
    response: SecResponse,
    filing: FilingDescriptor | None,
    name: str | None,
    format_hint: str | None,
) -> dict[str, Any]:
    del client  # Documents that network access ended at the supplied SecClient boundary.
    _validate_content(response.decoded_content, format_hint, name)
    staged = stage_sec_response(
        url,
        response,
        staging,
        source_metadata={"ticker": ticker, "cik": cik, "artifact_kind": kind},
    )
    relative = Path(kind) / (name or f"{kind}.json")
    # Keep submissions/companyfacts at stable, obvious paths.
    if kind in {"submissions", "companyfacts"}:
        relative = Path(f"{kind}.json")
    elif filing is not None:
        relative = Path("filings") / filing.accession / relative
    target = issuer_root / relative
    _export_immutable(target, staged.raw_path.read_bytes())
    return {
        "ticker": ticker,
        "cik": cik,
        "artifact_kind": kind,
        "path": relative.as_posix(),
        "source_endpoint": url,
        "accession": filing.accession if filing else None,
        "form": filing.form if filing else None,
        "filing_date": filing.filing_date if filing else None,
        "report_date": filing.report_date if filing else None,
        "fetched_at": _metadata_fetched_at(staged.metadata_path),
        "content_type": response.headers.get("Content-Type")
        or response.headers.get("content-type"),
        "artifact_representation": "decoded-entity-body",
        "byte_size": staged.byte_size,
        "sha256": staged.sha256,
        "provider": "SEC",
        "provider_schema": "sec-acquisition-v1",
    }


def _json(response: SecResponse, label: str) -> dict[str, Any]:
    try:
        value = response.json()
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"malformed {label} JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"invalid {label} JSON root")
    return value


def _validate_submissions(payload: dict[str, Any], cik: str, ticker: str) -> None:
    if str(payload.get("cik", "")).zfill(10) != cik:
        raise ValueError("submissions CIK mismatch")
    tickers = payload.get("tickers")
    if not isinstance(tickers, list) or ticker not in tickers:
        raise ValueError("submissions ticker mismatch")
    _filings(payload)


def _validate_companyfacts(payload: dict[str, Any], cik: str) -> None:
    if str(payload.get("cik", "")).zfill(10) != cik or not isinstance(payload.get("facts"), dict):
        raise ValueError("companyfacts CIK or facts mismatch")


def _filings(payload: dict[str, Any]) -> list[Filing]:
    try:
        recent = payload["filings"]["recent"]
        columns = [
            recent[key]
            for key in ("accessionNumber", "form", "filingDate", "reportDate", "primaryDocument")
        ]
    except (KeyError, TypeError) as exc:
        raise ValueError("malformed submissions filings") from exc
    if (
        any(not isinstance(column, list) for column in columns)
        or len({len(column) for column in columns}) != 1
    ):
        raise ValueError("contradictory submissions filing arrays")
    result: list[Filing] = []
    for accession, form, filed, report, document in zip(*columns, strict=True):
        if not all(
            isinstance(value, str) for value in (accession, form, filed, document)
        ) or not _ACCESSION.fullmatch(accession):
            raise ValueError("invalid submission filing row")
        if form in {"10-K", "10-Q", "10-K/A", "10-Q/A"}:
            result.append(Filing(accession, form, filed, report or None, document))
    return sorted(result, key=lambda item: (item.filing_date, item.accession), reverse=True)


def _validate_index(payload: dict[str, Any], filing: FilingDescriptor) -> set[str]:
    try:
        items = payload["directory"]["item"]
    except (KeyError, TypeError) as exc:
        raise ValueError("malformed filing index") from exc
    if not isinstance(items, list):
        raise ValueError("malformed filing index items")
    names: set[str] = set()
    for item in items:
        if isinstance(item, dict):
            name = item.get("name")
            if isinstance(name, str):
                names.add(name)
    if filing.primary_document not in names:
        raise ValueError("filing index does not contain its primary document")
    return names


def _validate_content(content: bytes, hint: str | None, name: str | None) -> None:
    if not content:
        raise ValueError("empty SEC artifact")
    if hint == "json":
        json.loads(content)
    elif hint == "xml":
        try:
            ET.fromstring(content)
        except ET.ParseError as exc:
            raise ValueError(f"malformed XML/XBRL artifact: {name}") from exc
    elif hint == "html":
        lowered = content[:4096].lower()
        if b"<html" not in lowered and b"<xbrl" not in lowered:
            raise ValueError(f"malformed filing document: {name}")


def _sufficiency(records: list[dict[str, Any]]) -> dict[str, bool]:
    # Companyfacts is recorded separately; structural tests need an instance,
    # schema, labels, presentation, and calculation linkbase from any filing.
    names = [str(record["path"]).lower() for record in records]
    return {
        "primitive_companyfacts_canonicalization": True,
        "structural_xbrl_extension_testing": all(
            any(token in name for name in names)
            for token in (".xsd", "_lab.xml", "_pre.xml", "_cal.xml")
        )
        and any(name.endswith((".htm", ".html")) for name in names),
    }


def _validated_issuer_registry_entry(root: Path, ticker: str, cik: str) -> dict[str, Any]:
    manifest_path = root / ticker / "manifest.json"
    try:
        manifest_bytes = manifest_path.read_bytes()
        issuer = json.loads(manifest_bytes)
    except (OSError, json.JSONDecodeError) as exc:
        raise ImmutableArtifactConflictError(
            f"invalid or missing issuer manifest: {manifest_path}"
        ) from exc
    if not isinstance(issuer, dict):
        raise ImmutableArtifactConflictError(f"invalid issuer manifest: {manifest_path}")
    if issuer.get("schema_version") != _ISSUER_SCHEMA_VERSION:
        raise ImmutableArtifactConflictError(f"unsupported issuer manifest schema: {manifest_path}")
    if issuer.get("ticker") != ticker or issuer.get("cik") != cik:
        raise ImmutableArtifactConflictError(
            f"issuer manifest ticker/CIK mismatch: {manifest_path}"
        )

    artifacts = issuer.get("artifacts")
    if not isinstance(artifacts, list):
        raise ImmutableArtifactConflictError(f"invalid issuer artifacts: {manifest_path}")
    records = [issuer.get("submissions"), issuer.get("companyfacts"), *artifacts]
    paths: set[str] = set()
    for record in records:
        _validate_issuer_artifact_record(root / ticker, record, ticker, cik, paths, manifest_path)

    selected = issuer.get("selected_filings")
    if not isinstance(selected, dict):
        raise ImmutableArtifactConflictError(f"invalid selected filings: {manifest_path}")
    accessions: dict[str, str] = {}
    for form in ("10-K", "10-Q"):
        filing = selected.get(form)
        if not isinstance(filing, dict) or filing.get("form") != form:
            raise ImmutableArtifactConflictError(f"missing selected {form}: {manifest_path}")
        accession = filing.get("accession")
        if not isinstance(accession, str) or not _ACCESSION.fullmatch(accession):
            raise ImmutableArtifactConflictError(f"invalid selected {form}: {manifest_path}")
        accessions[form] = accession

    return {
        "ticker": ticker,
        "cik": cik,
        "issuer_manifest_path": f"{ticker}/manifest.json",
        "issuer_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "issuer_schema_version": _ISSUER_SCHEMA_VERSION,
        "artifact_count": len(records),
        "selected_10_k_accession": accessions["10-K"],
        "selected_10_q_accession": accessions["10-Q"],
    }


def _validate_issuer_artifact_record(
    issuer_root: Path,
    record: object,
    ticker: str,
    cik: str,
    paths: set[str],
    manifest_path: Path,
) -> None:
    if not isinstance(record, dict):
        raise ImmutableArtifactConflictError(f"invalid issuer artifact record: {manifest_path}")
    relative = record.get("path")
    expected_checksum = record.get("sha256")
    expected_size = record.get("byte_size")
    if (
        record.get("ticker") != ticker
        or record.get("cik") != cik
        or not isinstance(relative, str)
        or not relative
        or Path(relative).is_absolute()
        or ".." in Path(relative).parts
        or not isinstance(expected_checksum, str)
        or not re.fullmatch(r"[0-9a-f]{64}", expected_checksum)
        or not isinstance(expected_size, int)
        or isinstance(expected_size, bool)
        or expected_size < 0
        or relative in paths
    ):
        raise ImmutableArtifactConflictError(f"invalid issuer artifact record: {manifest_path}")
    paths.add(relative)
    artifact_path = issuer_root / relative
    try:
        content = artifact_path.read_bytes()
    except OSError as exc:
        raise ImmutableArtifactConflictError(f"missing issuer artifact: {artifact_path}") from exc
    if len(content) != expected_size or hashlib.sha256(content).hexdigest() != expected_checksum:
        raise ImmutableArtifactConflictError(f"issuer artifact checksum mismatch: {artifact_path}")


def _read_existing_root_manifest(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ImmutableArtifactConflictError(f"invalid existing corpus manifest: {path}") from exc
    if not isinstance(existing, dict):
        raise ImmutableArtifactConflictError(f"invalid existing corpus manifest: {path}")
    return existing


def _validate_legacy_root_for_upgrade(
    existing: dict[str, Any], entries: list[dict[str, Any]]
) -> None:
    """Permit only the known v1-to-v2 metadata upgrade, never a data rewrite."""
    if existing.get("schema_version") != "sec-corpus-v1":
        raise ImmutableArtifactConflictError("unsupported existing root corpus schema")
    legacy_issuers = existing.get("issuers")
    if not isinstance(legacy_issuers, list):
        raise ImmutableArtifactConflictError("invalid existing corpus manifest")
    current = {entry["ticker"]: entry for entry in entries}
    for issuer in legacy_issuers:
        if not isinstance(issuer, dict) or issuer.get("ticker") not in current:
            raise ImmutableArtifactConflictError("existing root corpus issuer is invalid")
        target = current[issuer["ticker"]]
        if (
            issuer.get("cik") != target["cik"]
            or issuer.get("manifest") != target["issuer_manifest_path"]
        ):
            raise ImmutableArtifactConflictError(
                "existing root corpus issuer conflicts with frozen corpus"
            )


def _replace_root_manifest_for_schema_upgrade(path: Path, content: bytes) -> None:
    """The explicit v1-to-v2 reconciliation is the sole allowed root rewrite."""
    temporary = path.with_name(f".{path.name}.reconciled")
    _write_new_atomically(temporary, content)
    try:
        temporary.replace(path)
    except OSError as exc:
        raise ImmutableArtifactConflictError(
            f"could not reconcile root corpus manifest: {path}"
        ) from exc


def _canonical_json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def _filing_dict(filing: Filing) -> dict[str, str | None]:
    return {
        "accession": filing.accession,
        "form": filing.form,
        "filing_date": filing.filing_date,
        "report_date": filing.report_date,
        "primary_document": filing.primary_document,
    }


def _metadata_fetched_at(path: Path) -> str:
    return str(json.loads(path.read_text(encoding="utf-8"))["fetched_at"])


def _export_immutable(path: Path, content: bytes) -> None:
    try:
        _write_new_atomically(path, content)
    except ImmutableArtifactConflictError as exc:
        raise ImmutableArtifactConflictError(
            f"refusing to overwrite divergent corpus artifact: {path}"
        ) from exc


def _write_json_immutable(path: Path, value: dict[str, Any]) -> None:
    _export_immutable(path, (json.dumps(value, sort_keys=True, indent=2) + "\n").encode())


def _existing_created_at(path: Path) -> str | None:
    """Keep root-manifest event metadata out of subsequent immutable writes."""
    if not path.exists():
        return None
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ImmutableArtifactConflictError(f"invalid existing corpus manifest: {path}") from exc
    created_at = existing.get("created_at") if isinstance(existing, dict) else None
    if not isinstance(created_at, str):
        raise ImmutableArtifactConflictError(f"invalid existing corpus manifest: {path}")
    return created_at


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
