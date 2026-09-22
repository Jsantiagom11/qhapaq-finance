from decimal import Decimal

import pytest

from qhapaq_finance.diamond.canonical_json import (
    CanonicalJsonError,
    canonical_json_bytes,
    normalize_decimal,
    sha256_canonical_json,
)


def test_decimal_lexical_variants_share_one_value() -> None:
    assert normalize_decimal(10) == "10"
    assert normalize_decimal(10.0) == "10"
    assert normalize_decimal(Decimal("10.00")) == "10"
    assert normalize_decimal(Decimal("1E+3")) == "1000"


def test_negative_zero_normalizes_to_zero() -> None:
    assert normalize_decimal(-0.0) == "0"
    assert normalize_decimal(Decimal("-0.000")) == "0"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_values_fail_closed(value: float) -> None:
    with pytest.raises(CanonicalJsonError, match="CANONICAL_NUMBER_NOT_FINITE"):
        normalize_decimal(value)


def test_canonical_json_is_key_order_independent() -> None:
    left = {"b": "2", "a": ["1", None]}
    right = {"a": ["1", None], "b": "2"}

    assert canonical_json_bytes(left) == canonical_json_bytes(right)
    assert sha256_canonical_json(left) == sha256_canonical_json(right)
