"""Offline-first resolution of US symbols from SEC company reference data."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .sec_client import SecClient

SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_CACHE_SCHEMA = "sec-company-tickers-cache-v1"


class ResolverError(ValueError):
    """The local SEC company-reference cache is unavailable or invalid."""


@dataclass(frozen=True)
class CompanyProvenance:
    """Source metadata retained with a resolved company identity."""

    source_url: str
    fetched_at: str | None
    raw_sha256: str | None
    raw_byte_size: int | None

    def to_dict(self) -> dict[str, str | int | None]:
        return {
            "source_url": self.source_url,
            "fetched_at": self.fetched_at,
            "raw_sha256": self.raw_sha256,
            "raw_byte_size": self.raw_byte_size,
        }


@dataclass(frozen=True)
class ResolvedCompany:
    """Normalized company identity returned from SEC reference data."""

    ticker: str
    company_name: str
    cik: str
    exchange: str | None
    provenance: CompanyProvenance


class SymbolResolver(Protocol):
    """Offline symbol-to-company identity boundary used by analysis orchestration."""

    def resolve(self, ticker: str) -> ResolvedCompany | None: ...


class CompanyResolver:
    """Resolve only from a validated local cache; refresh is an explicit action."""

    def __init__(
        self, repository_root: str | Path = ".", *, cache_path: str | Path | None = None
    ) -> None:
        root = Path(repository_root)
        self.cache_path = (
            Path(cache_path)
            if cache_path is not None
            else root / "data/cache/sec/company_tickers.json"
        )

    def resolve(self, ticker: str) -> ResolvedCompany | None:
        """Return a cached SEC identity without initiating any network access."""
        normalized = _ticker(ticker)
        try:
            cache = _load_cache(self.cache_path)
        except (OSError, json.JSONDecodeError, ResolverError):
            return None
        for entry in cache["entries"]:
            if entry["ticker"] == normalized:
                return ResolvedCompany(
                    normalized,
                    entry["company_name"],
                    entry["cik"],
                    entry["exchange"],
                    cache["provenance"],
                )
        return None

    def refresh(self, client: SecClient, *, now: Callable[[], datetime] | None = None) -> int:
        """Explicitly refresh the cache through ``SecClient`` after full validation."""
        response = client.get(SEC_COMPANY_TICKERS_URL)
        raw = response.raw_content
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise ResolverError("SEC company reference response is not JSON") from exc
        entries = _entries_from_sec(payload)
        fetched_at = (now or (lambda: datetime.now(timezone.utc)))().astimezone(timezone.utc)
        source = {
            "source_url": SEC_COMPANY_TICKERS_URL,
            "fetched_at": fetched_at.isoformat().replace("+00:00", "Z"),
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "raw_byte_size": len(raw),
            "http_status": response.status_code,
            "content_type": _header(response.headers, "content-type"),
        }
        document = {
            "schema_version": _CACHE_SCHEMA,
            "source": source,
            "entries_sha256": _entries_checksum(entries),
            "entries": entries,
        }
        _validate_cache(document)
        _write_atomically(self.cache_path, _canonical_json(document))
        return len(entries)


def _load_cache(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    _validate_cache(payload)
    source = payload["source"]
    return {
        "entries": payload["entries"],
        "provenance": CompanyProvenance(
            source["source_url"],
            source["fetched_at"],
            source["raw_sha256"],
            source["raw_byte_size"],
        ),
    }


def _entries_from_sec(payload: object) -> list[dict[str, str | None]]:
    if not isinstance(payload, dict):
        raise ResolverError("SEC company reference payload must be an object")
    entries: list[dict[str, str | None]] = []
    tickers: set[str] = set()
    for item in payload.values():
        if not isinstance(item, Mapping):
            raise ResolverError("SEC company reference entry must be an object")
        try:
            ticker = _ticker(_text(item.get("ticker"), "ticker"))
            company_name = _company_name(_text(item.get("title"), "title"))
            cik = _cik(item.get("cik_str"))
        except ResolverError:
            raise
        if ticker in tickers:
            raise ResolverError(f"duplicate SEC ticker: {ticker}")
        tickers.add(ticker)
        entries.append(
            {"ticker": ticker, "company_name": company_name, "cik": cik, "exchange": None}
        )
    if not entries:
        raise ResolverError("SEC company reference payload is empty")
    return sorted(entries, key=lambda item: str(item["ticker"]))


def _validate_cache(payload: object) -> None:
    if not isinstance(payload, dict) or payload.get("schema_version") != _CACHE_SCHEMA:
        raise ResolverError("unsupported SEC company-reference cache")
    source = payload.get("source")
    entries = payload.get("entries")
    if not isinstance(source, dict) or not isinstance(entries, list):
        raise ResolverError("invalid SEC company-reference cache")
    if not isinstance(source.get("source_url"), str):
        raise ResolverError("invalid SEC company-reference provenance")
    if source.get("fetched_at") is not None and not isinstance(source["fetched_at"], str):
        raise ResolverError("invalid SEC company-reference fetched_at")
    if source.get("raw_sha256") is not None and not isinstance(source["raw_sha256"], str):
        raise ResolverError("invalid SEC company-reference raw checksum")
    if source.get("raw_byte_size") is not None and (
        not isinstance(source["raw_byte_size"], int) or source["raw_byte_size"] < 0
    ):
        raise ResolverError("invalid SEC company-reference byte size")
    normalized: list[dict[str, str | None]] = []
    seen: set[str] = set()
    for item in entries:
        if not isinstance(item, dict):
            raise ResolverError("invalid SEC company-reference entry")
        ticker = _ticker(_text(item.get("ticker"), "ticker"))
        if ticker in seen:
            raise ResolverError(f"duplicate SEC ticker: {ticker}")
        seen.add(ticker)
        normalized.append(
            {
                "ticker": ticker,
                "company_name": _company_name(_text(item.get("company_name"), "company_name")),
                "cik": _cik(item.get("cik")),
                "exchange": _optional_text(item.get("exchange"), "exchange"),
            }
        )
    if not normalized or payload.get("entries_sha256") != _entries_checksum(normalized):
        raise ResolverError("SEC company-reference cache checksum mismatch")


def _ticker(value: str) -> str:
    normalized = value.strip().upper()
    if not normalized:
        raise ResolverError("ticker is required")
    return normalized


def _company_name(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ResolverError("company name is required")
    return normalized


def _cik(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ResolverError("CIK is required")
    normalized = str(value).strip()
    if not normalized.isdigit() or int(normalized) <= 0 or len(normalized) > 10:
        raise ResolverError("CIK must be a positive value with at most 10 digits")
    return normalized.zfill(10)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ResolverError(f"{field} must be text")
    return value


def _optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _text(value, field)


def _entries_checksum(entries: list[dict[str, str | None]]) -> str:
    return hashlib.sha256(_canonical_json(entries)).hexdigest()


def _canonical_json(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _header(headers: Mapping[str, str], name: str) -> str | None:
    return next((value for key, value in headers.items() if key.lower() == name), None)


def _write_atomically(path: Path, content: bytes) -> None:
    """Replace the cache atomically, but only after the new document validates."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
