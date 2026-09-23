from __future__ import annotations

from dataclasses import replace

import pytest

from qhapaq_finance.diamond.canonical_json import (
    CanonicalJsonError,
    normalize_decimal,
)
from qhapaq_finance.diamond.contracts import FiscalSlot, PeriodKind
from qhapaq_finance.diamond.dataset_identity import (
    DATASET_CANONICALIZER_VERSION,
    DATASET_SCHEMA_VERSION,
    dataset_identity,
    fundamental_dataset_payload,
)

try:
    from tests.diamond_helpers import make_record, obs, rich_record
except ModuleNotFoundError:
    from diamond_helpers import make_record, obs, rich_record


def test_record_order_does_not_change_identity() -> None:
    first = rich_record("AAA")
    second = rich_record("BBB")

    assert dataset_identity((first, second)) == dataset_identity((second, first))


def test_observation_order_does_not_change_identity() -> None:
    record = rich_record("AAA")
    reversed_record = replace(
        record,
        observations=tuple(reversed(record.observations)),
    )

    assert dataset_identity((record,)) == dataset_identity((reversed_record,))


def test_one_observation_change_changes_identity() -> None:
    record = rich_record("AAA")
    first = record.observations[0]
    changed = replace(
        record,
        observations=(
            replace(first, value=first.value + 1.0),
            *record.observations[1:],
        ),
    )

    assert dataset_identity((record,)) != dataset_identity((changed,))


def test_dataset_projection_uses_versioned_contract() -> None:
    payload = fundamental_dataset_payload((make_record("AAA"),))

    assert payload["schema_version"] == DATASET_SCHEMA_VERSION
    assert payload["canonicalizer_version"] == DATASET_CANONICALIZER_VERSION


def test_dataset_projection_normalizes_numeric_values() -> None:
    record = make_record(
        "AAA",
        observations=(
            obs(
                "revenue",
                FiscalSlot.TTM,
                10.0,
            ),
            obs(
                "cash_and_equivalents",
                FiscalSlot.LATEST,
                -0.0,
                period_start=None,
                period_kind=PeriodKind.INSTANT,
            ),
        ),
    )

    payload = fundamental_dataset_payload((record,))
    observations = {item["metric_id"]: item for item in payload["records"][0]["observations"]}

    assert observations["revenue"]["value"] == "10"
    assert observations["cash_and_equivalents"]["value"] == "0"


def test_evidence_diagnostics_are_order_independent() -> None:
    first = replace(
        make_record("AAA"),
        evidence_diagnostics=("Z_DIAGNOSTIC", "A_DIAGNOSTIC"),
    )
    second = replace(
        first,
        evidence_diagnostics=("A_DIAGNOSTIC", "Z_DIAGNOSTIC"),
    )

    assert dataset_identity((first,)) == dataset_identity((second,))

    payload = fundamental_dataset_payload((first,))
    assert payload["records"][0]["evidence_diagnostics"] == [
        "A_DIAGNOSTIC",
        "Z_DIAGNOSTIC",
    ]


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), float("-inf")],
)
def test_canonical_primitive_rejects_non_finite_numbers(value: float) -> None:
    with pytest.raises(
        CanonicalJsonError,
        match="CANONICAL_NUMBER_NOT_FINITE",
    ):
        normalize_decimal(value)
