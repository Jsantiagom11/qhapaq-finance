"""Deterministic evidence cache for Diamond Funnel providers."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path


class DiamondCacheError(RuntimeError):
    """Raised when cached Diamond evidence cannot be trusted."""


@dataclass(frozen=True, slots=True)
class CachedEvidence:
    provider: str
    request_identity: str
    retrieved_at: datetime
    data_as_of: date
    payload: object
    payload_sha256: str


def _canonical_bytes(payload: object) -> bytes:
    try:
        text = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise DiamondCacheError("CACHE_PAYLOAD_NOT_CANONICAL_JSON") from exc
    return text.encode("utf-8")


def _sha256(payload: object) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


class DiamondCache:
    """Small checksum-verified JSON cache with atomic writes."""

    SCHEMA_VERSION = "diamond-cache-v1"

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, request_identity: str) -> Path:
        digest = hashlib.sha256(request_identity.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.json"

    def load(self, request_identity: str) -> CachedEvidence | None:
        path = self._path(request_identity)
        if not path.exists():
            return None

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DiamondCacheError("CACHE_UNREADABLE") from exc

        if not isinstance(raw, dict):
            raise DiamondCacheError("CACHE_ROOT_INVALID")
        if raw.get("schema_version") != self.SCHEMA_VERSION:
            raise DiamondCacheError("CACHE_SCHEMA_UNSUPPORTED")
        if raw.get("request_identity") != request_identity:
            raise DiamondCacheError("CACHE_REQUEST_IDENTITY_MISMATCH")

        provider = raw.get("provider")
        retrieved_at_raw = raw.get("retrieved_at")
        data_as_of_raw = raw.get("data_as_of")
        payload_sha256 = raw.get("payload_sha256")

        if not isinstance(provider, str) or not provider:
            raise DiamondCacheError("CACHE_PROVIDER_INVALID")
        if not isinstance(retrieved_at_raw, str):
            raise DiamondCacheError("CACHE_RETRIEVED_AT_INVALID")
        if not isinstance(data_as_of_raw, str):
            raise DiamondCacheError("CACHE_DATA_AS_OF_INVALID")
        if not isinstance(payload_sha256, str):
            raise DiamondCacheError("CACHE_CHECKSUM_INVALID")

        try:
            retrieved_at = datetime.fromisoformat(retrieved_at_raw)
            data_as_of = date.fromisoformat(data_as_of_raw)
        except ValueError as exc:
            raise DiamondCacheError("CACHE_TEMPORAL_METADATA_INVALID") from exc

        payload = raw.get("payload")
        actual = _sha256(payload)
        if actual != payload_sha256:
            raise DiamondCacheError("CACHE_CHECKSUM_MISMATCH")

        return CachedEvidence(
            provider=provider,
            request_identity=request_identity,
            retrieved_at=retrieved_at,
            data_as_of=data_as_of,
            payload=payload,
            payload_sha256=payload_sha256,
        )

    def store(
        self,
        request_identity: str,
        *,
        provider: str,
        data_as_of: date,
        payload: object,
    ) -> CachedEvidence:
        if not request_identity.strip():
            raise DiamondCacheError("CACHE_REQUEST_IDENTITY_REQUIRED")
        if not provider.strip():
            raise DiamondCacheError("CACHE_PROVIDER_REQUIRED")

        retrieved_at = datetime.now(timezone.utc)
        payload_sha256 = _sha256(payload)

        document = {
            "schema_version": self.SCHEMA_VERSION,
            "provider": provider,
            "request_identity": request_identity,
            "retrieved_at": retrieved_at.isoformat(),
            "data_as_of": data_as_of.isoformat(),
            "payload_sha256": payload_sha256,
            "payload": payload,
        }

        self.root.mkdir(parents=True, exist_ok=True)
        target = self._path(request_identity)

        encoded = _canonical_bytes(document) + b"\n"

        fd, temporary = tempfile.mkstemp(
            dir=self.root,
            prefix=f".{target.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        except BaseException:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise

        return CachedEvidence(
            provider=provider,
            request_identity=request_identity,
            retrieved_at=retrieved_at,
            data_as_of=data_as_of,
            payload=payload,
            payload_sha256=payload_sha256,
        )
