from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal


class CanonicalJsonError(ValueError):
    """Canonical wire data cannot be represented safely."""


def normalize_decimal(value: int | float | Decimal) -> str:
    if isinstance(value, bool):
        raise CanonicalJsonError("CANONICAL_NUMBER_INVALID")

    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalJsonError("CANONICAL_NUMBER_NOT_FINITE")
        number = Decimal(repr(value))
    elif isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, Decimal):
        number = value
    else:
        raise CanonicalJsonError("CANONICAL_NUMBER_INVALID")

    if not number.is_finite():
        raise CanonicalJsonError("CANONICAL_NUMBER_NOT_FINITE")

    if number == 0:
        return "0"

    rendered = format(number, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")

    return rendered


def canonical_json_bytes(payload: object) -> bytes:
    try:
        rendered = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise CanonicalJsonError("CANONICAL_JSON_INVALID") from exc

    return rendered.encode("utf-8")


def sha256_canonical_json(payload: object) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
