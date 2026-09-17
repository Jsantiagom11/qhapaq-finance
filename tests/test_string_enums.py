from __future__ import annotations

import json

import pytest

from qhapaq_finance.agents.contracts import Confidence, EvidenceKind, NumericUnit
from qhapaq_finance.agents.interpretation import SignalCode
from qhapaq_finance.decision import DecisionStatus
from qhapaq_finance.explainability import ArgumentCategory, FactStatus


@pytest.mark.parametrize(
    ("member", "value"),
    (
        (DecisionStatus.ELIGIBLE, "ELIGIBLE"),
        (FactStatus.FACT, "FACT"),
        (ArgumentCategory.VALUATION, "VALUATION"),
        (SignalCode.ABOVE_FAIR_VALUE, "ABOVE_FAIR_VALUE"),
        (Confidence.LOW, "LOW"),
        (EvidenceKind.DETERMINISTIC_ARTIFACT, "DETERMINISTIC_ARTIFACT"),
        (NumericUnit.USD_PER_SHARE, "USD_PER_SHARE"),
    ),
)
def test_string_enum_observable_contract(member: object, value: str) -> None:
    assert member.value == value  # type: ignore[attr-defined]
    assert member == value
    assert json.dumps(member) == json.dumps(value)
    assert str(member) == value
    assert f"{member}" == value
    assert f"{member:>30}" == f"{value:>30}"


def test_confidence_iteration_retains_schema_order_and_values() -> None:
    assert [(item.name, item.value) for item in Confidence] == [
        ("LOW", "LOW"),
        ("MEDIUM", "MEDIUM"),
        ("HIGH", "HIGH"),
    ]
