from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

from qhapaq_finance.diamond.cache import DiamondCache, DiamondCacheError
from qhapaq_finance.diamond.canonical_json import (
    canonical_json_bytes,
    normalize_decimal,
    sha256_canonical_json,
)
from qhapaq_finance.financial_canonicalization import (
    RawFact,
    extract_company_facts,
)
from qhapaq_finance.sec_client import SecResponse

SEC_EVIDENCE_SCHEMA_VERSION = "diamond-sec-evidence-v1"
RECENT_AS_OF_DAYS = 2
RECENT_TTL = timedelta(hours=6)
HISTORICAL_TTL = timedelta(days=7)

_ALLOWED_FORMS = frozenset({"10-K", "10-K/A", "10-Q", "10-Q/A"})


class SecEvidenceError(RuntimeError):
    """SEC evidence cannot be trusted or refreshed."""


class _SecHttpClient(Protocol):
    def get(
        self,
        url: str,
        *,
        request_headers: Mapping[str, str] | None = None,
        accepted_statuses: frozenset[int] = frozenset(),
    ) -> SecResponse: ...


@dataclass(frozen=True, slots=True)
class SecEvidenceManifest:
    schema_version: str
    cik: str
    request_identity: str
    retrieved_at: datetime
    data_as_of: date
    payload_sha256: str
    evidence_revision_sha256: str
    latest_in_scope_filing_date: date | None
    latest_in_scope_accession: str | None
    etag: str | None
    last_modified: str | None
    blob_name: str


@dataclass(frozen=True, slots=True)
class ResolvedSecEvidence:
    manifest: SecEvidenceManifest
    facts: tuple[RawFact, ...] | None


def filtered_companyfacts(
    payload: Mapping[str, object],
    *,
    source_identity: str,
    as_of: date,
) -> tuple[RawFact, ...]:
    facts = extract_company_facts(payload, source_identity=source_identity)
    return tuple(
        fact
        for fact in facts
        if fact.filing_form in _ALLOWED_FORMS
        and fact.filing_date <= as_of
        and fact.end <= as_of
        and fact.consolidated
        and not fact.dimensions
    )


def evidence_revision(facts: tuple[RawFact, ...]) -> str:
    rows = [
        {
            "taxonomy": fact.taxonomy,
            "concept": fact.concept,
            "unit": fact.unit,
            "value": normalize_decimal(fact.value),
            "period_kind": fact.period_kind.value,
            "start": fact.start.isoformat() if fact.start is not None else None,
            "end": fact.end.isoformat(),
            "fiscal_year": fact.fiscal_year,
            "fiscal_period": fact.fiscal_period,
            "filing_form": fact.filing_form,
            "filing_date": fact.filing_date.isoformat(),
            "accession": fact.accession,
            "consolidated": fact.consolidated,
            "dimensions": list(fact.dimensions),
        }
        for fact in facts
    ]
    rows.sort(key=canonical_json_bytes)
    return sha256_canonical_json(rows)


def _ttl(as_of: date, today: date) -> timedelta:
    return RECENT_TTL if (today - as_of).days <= RECENT_AS_OF_DAYS else HISTORICAL_TTL


def _normalize_cik(value: object) -> str:
    if isinstance(value, bool):
        raise SecEvidenceError("SEC_CIK_INVALID")

    rendered = str(value).strip()
    if not rendered.isdigit() or len(rendered) > 10:
        raise SecEvidenceError("SEC_CIK_INVALID")

    return rendered.zfill(10)


def _response_header(headers: Mapping[str, str], name: str) -> str | None:
    target = name.casefold()
    for key, value in headers.items():
        if key.casefold() == target:
            return value
    return None


def _decode_payload(content: bytes) -> Mapping[str, object]:
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SecEvidenceError("SEC_PAYLOAD_INVALID") from exc

    if not isinstance(payload, dict):
        raise SecEvidenceError("SEC_PAYLOAD_INVALID")

    return payload


def _payload_cik(payload: Mapping[str, object]) -> str:
    try:
        return _normalize_cik(payload["cik"])
    except KeyError as exc:
        raise SecEvidenceError("SEC_CIK_INVALID") from exc


def _latest_filing(
    facts: tuple[RawFact, ...],
) -> tuple[date | None, str | None]:
    if not facts:
        return None, None

    latest = max(facts, key=lambda fact: (fact.filing_date, fact.accession))
    return latest.filing_date, latest.accession


class SecEvidenceStore:
    def __init__(
        self,
        *,
        root: Path,
        client: _SecHttpClient | None,
        legacy_cache: DiamondCache | None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = Path(root)
        self.client = client
        self.legacy_cache = legacy_cache
        self._now = now or (lambda: datetime.now(timezone.utc))

        self.provider_requests = 0
        self.cache_hits = 0
        self.cache_misses = 0

    @staticmethod
    def request_identity(cik: str) -> str:
        normalized = _normalize_cik(cik)
        return f"https://data.sec.gov/api/xbrl/companyfacts/CIK{normalized}.json"

    def resolve(self, cik: str, as_of: date) -> ResolvedSecEvidence:
        normalized_cik = _normalize_cik(cik)
        identity = self.request_identity(normalized_cik)
        manifest = self._load_manifest(identity)

        if manifest is not None:
            self._validate_manifest(
                manifest,
                cik=normalized_cik,
                request_identity=identity,
            )

            if manifest.data_as_of == as_of and self._is_fresh(manifest):
                self.cache_hits += 1
                return ResolvedSecEvidence(manifest=manifest, facts=None)

            if manifest.data_as_of == as_of:
                self.cache_misses += 1
                return self._revalidate(manifest)

        migrated = self._try_legacy(
            cik=normalized_cik,
            request_identity=identity,
            as_of=as_of,
        )
        if migrated is not None:
            self.cache_hits += 1
            return migrated

        self.cache_misses += 1
        return self._fetch(
            cik=normalized_cik,
            request_identity=identity,
            as_of=as_of,
        )

    def load_facts(
        self,
        manifest: SecEvidenceManifest,
    ) -> tuple[RawFact, ...]:
        blob = self.root / "blobs" / manifest.blob_name
        try:
            content = blob.read_bytes()
        except OSError as exc:
            raise SecEvidenceError("SEC_BLOB_UNREADABLE") from exc

        actual_sha = hashlib.sha256(content).hexdigest()
        if actual_sha != manifest.payload_sha256:
            raise SecEvidenceError("SEC_BLOB_CHECKSUM_MISMATCH")

        payload = _decode_payload(content)
        if _payload_cik(payload) != manifest.cik:
            raise SecEvidenceError("SEC_CIK_MISMATCH")

        try:
            facts = filtered_companyfacts(
                payload,
                source_identity=f"sec-payload:{manifest.payload_sha256}",
                as_of=manifest.data_as_of,
            )
        except ValueError as exc:
            raise SecEvidenceError("SEC_PAYLOAD_INVALID") from exc

        if evidence_revision(facts) != manifest.evidence_revision_sha256:
            raise SecEvidenceError("SEC_EVIDENCE_REVISION_MISMATCH")

        return facts

    def _is_fresh(self, manifest: SecEvidenceManifest) -> bool:
        now = self._now()
        age = now - manifest.retrieved_at
        return age <= _ttl(manifest.data_as_of, now.date())

    def _revalidate(
        self,
        manifest: SecEvidenceManifest,
    ) -> ResolvedSecEvidence:
        if self.client is None:
            raise SecEvidenceError("SEC_REVALIDATION_FAILED")

        request_headers: dict[str, str] = {}
        if manifest.etag is not None:
            request_headers["If-None-Match"] = manifest.etag
        elif manifest.last_modified is not None:
            request_headers["If-Modified-Since"] = manifest.last_modified

        try:
            self.provider_requests += 1
            response = self.client.get(
                manifest.request_identity,
                request_headers=request_headers,
                accepted_statuses=frozenset({304}),
            )
        except Exception as exc:
            raise SecEvidenceError("SEC_REVALIDATION_FAILED") from exc

        if response.status_code == 304:
            updated = replace(
                manifest,
                retrieved_at=self._now(),
                etag=_response_header(response.headers, "ETag") or manifest.etag,
                last_modified=_response_header(
                    response.headers,
                    "Last-Modified",
                )
                or manifest.last_modified,
            )
            self._write_manifest(updated)
            return ResolvedSecEvidence(manifest=updated, facts=None)

        if not 200 <= response.status_code < 300:
            raise SecEvidenceError("SEC_REVALIDATION_FAILED")

        return self._store_response(
            cik=manifest.cik,
            request_identity=manifest.request_identity,
            as_of=manifest.data_as_of,
            response=response,
        )

    def _fetch(
        self,
        *,
        cik: str,
        request_identity: str,
        as_of: date,
    ) -> ResolvedSecEvidence:
        if self.client is None:
            raise SecEvidenceError("SEC_REVALIDATION_FAILED")

        try:
            self.provider_requests += 1
            response = self.client.get(request_identity)
        except Exception as exc:
            raise SecEvidenceError("SEC_REVALIDATION_FAILED") from exc

        if not 200 <= response.status_code < 300:
            raise SecEvidenceError("SEC_REVALIDATION_FAILED")

        return self._store_response(
            cik=cik,
            request_identity=request_identity,
            as_of=as_of,
            response=response,
        )

    def _store_response(
        self,
        *,
        cik: str,
        request_identity: str,
        as_of: date,
        response: SecResponse,
    ) -> ResolvedSecEvidence:
        return self._store_payload_bytes(
            cik=cik,
            request_identity=request_identity,
            as_of=as_of,
            content=response.content,
            etag=_response_header(response.headers, "ETag"),
            last_modified=_response_header(
                response.headers,
                "Last-Modified",
            ),
            retrieved_at=self._now(),
        )

    def _store_payload_bytes(
        self,
        *,
        cik: str,
        request_identity: str,
        as_of: date,
        content: bytes,
        etag: str | None,
        last_modified: str | None,
        retrieved_at: datetime,
    ) -> ResolvedSecEvidence:
        payload = _decode_payload(content)

        if _payload_cik(payload) != cik:
            raise SecEvidenceError("SEC_CIK_MISMATCH")

        payload_sha256 = hashlib.sha256(content).hexdigest()

        try:
            facts = filtered_companyfacts(
                payload,
                source_identity=f"sec-payload:{payload_sha256}",
                as_of=as_of,
            )
        except ValueError as exc:
            raise SecEvidenceError("SEC_PAYLOAD_INVALID") from exc

        revision = evidence_revision(facts)
        latest_date, latest_accession = _latest_filing(facts)
        blob_name = f"{payload_sha256}.json"

        self._atomic_write(
            self.root / "blobs" / blob_name,
            content,
        )

        manifest = SecEvidenceManifest(
            schema_version=SEC_EVIDENCE_SCHEMA_VERSION,
            cik=cik,
            request_identity=request_identity,
            retrieved_at=retrieved_at,
            data_as_of=as_of,
            payload_sha256=payload_sha256,
            evidence_revision_sha256=revision,
            latest_in_scope_filing_date=latest_date,
            latest_in_scope_accession=latest_accession,
            etag=etag,
            last_modified=last_modified,
            blob_name=blob_name,
        )
        self._write_manifest(manifest)

        return ResolvedSecEvidence(
            manifest=manifest,
            facts=facts,
        )

    def _try_legacy(
        self,
        *,
        cik: str,
        request_identity: str,
        as_of: date,
    ) -> ResolvedSecEvidence | None:
        if self.legacy_cache is None:
            return None

        try:
            cached = self.legacy_cache.load(request_identity)
        except DiamondCacheError as exc:
            raise SecEvidenceError("SEC_LEGACY_CACHE_INVALID") from exc

        if cached is None:
            return None
        if cached.provider != "sec-companyfacts":
            return None
        if cached.data_as_of != as_of:
            return None
        if not isinstance(cached.payload, Mapping):
            return None

        try:
            cached_cik = _payload_cik(cached.payload)
        except SecEvidenceError:
            return None

        if cached_cik != cik:
            return None

        now = self._now()
        if now - cached.retrieved_at > _ttl(as_of, now.date()):
            return None

        content = canonical_json_bytes(cached.payload)

        return self._store_payload_bytes(
            cik=cik,
            request_identity=request_identity,
            as_of=as_of,
            content=content,
            etag=None,
            last_modified=None,
            retrieved_at=cached.retrieved_at,
        )

    def _manifest_path(self, request_identity: str) -> Path:
        digest = hashlib.sha256(request_identity.encode("utf-8")).hexdigest()
        return self.root / "index" / f"{digest}.json"

    def _load_manifest(
        self,
        request_identity: str,
    ) -> SecEvidenceManifest | None:
        path = self._manifest_path(request_identity)
        if not path.exists():
            return None

        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SecEvidenceError("SEC_MANIFEST_UNREADABLE") from exc

        if not isinstance(document, dict):
            raise SecEvidenceError("SEC_MANIFEST_INVALID")

        try:
            latest_filing_raw = document["latest_in_scope_filing_date"]
            latest_accession_raw = document["latest_in_scope_accession"]

            manifest = SecEvidenceManifest(
                schema_version=str(document["schema_version"]),
                cik=str(document["cik"]),
                request_identity=str(document["request_identity"]),
                retrieved_at=datetime.fromisoformat(str(document["retrieved_at"])),
                data_as_of=date.fromisoformat(str(document["data_as_of"])),
                payload_sha256=str(document["payload_sha256"]),
                evidence_revision_sha256=str(document["evidence_revision_sha256"]),
                latest_in_scope_filing_date=(
                    date.fromisoformat(str(latest_filing_raw))
                    if latest_filing_raw is not None
                    else None
                ),
                latest_in_scope_accession=(
                    str(latest_accession_raw) if latest_accession_raw is not None else None
                ),
                etag=(str(document["etag"]) if document["etag"] is not None else None),
                last_modified=(
                    str(document["last_modified"])
                    if document["last_modified"] is not None
                    else None
                ),
                blob_name=str(document["blob_name"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SecEvidenceError("SEC_MANIFEST_INVALID") from exc

        return manifest

    @staticmethod
    def _validate_manifest(
        manifest: SecEvidenceManifest,
        *,
        cik: str,
        request_identity: str,
    ) -> None:
        if manifest.schema_version != SEC_EVIDENCE_SCHEMA_VERSION:
            raise SecEvidenceError("SEC_MANIFEST_SCHEMA_UNSUPPORTED")
        if manifest.cik != cik:
            raise SecEvidenceError("SEC_CIK_MISMATCH")
        if manifest.request_identity != request_identity:
            raise SecEvidenceError("SEC_REQUEST_IDENTITY_MISMATCH")
        if not manifest.payload_sha256:
            raise SecEvidenceError("SEC_MANIFEST_INVALID")
        if not manifest.evidence_revision_sha256:
            raise SecEvidenceError("SEC_MANIFEST_INVALID")
        if manifest.blob_name != f"{manifest.payload_sha256}.json":
            raise SecEvidenceError("SEC_MANIFEST_INVALID")

    def _write_manifest(
        self,
        manifest: SecEvidenceManifest,
    ) -> None:
        document = {
            "schema_version": manifest.schema_version,
            "cik": manifest.cik,
            "request_identity": manifest.request_identity,
            "retrieved_at": manifest.retrieved_at.isoformat(),
            "data_as_of": manifest.data_as_of.isoformat(),
            "payload_sha256": manifest.payload_sha256,
            "evidence_revision_sha256": (manifest.evidence_revision_sha256),
            "latest_in_scope_filing_date": (
                manifest.latest_in_scope_filing_date.isoformat()
                if manifest.latest_in_scope_filing_date is not None
                else None
            ),
            "latest_in_scope_accession": (manifest.latest_in_scope_accession),
            "etag": manifest.etag,
            "last_modified": manifest.last_modified,
            "blob_name": manifest.blob_name,
        }

        self._atomic_write(
            self._manifest_path(manifest.request_identity),
            canonical_json_bytes(document) + b"\n",
        )

    @staticmethod
    def _atomic_write(target: Path, content: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)

        fd, temporary = tempfile.mkstemp(
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        except BaseException:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
