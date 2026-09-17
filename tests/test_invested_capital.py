from datetime import date

import pytest

from qhapaq_finance.accounting import (
    AccountingError,
    DataState,
    ICComponent,
    ICMethod,
    InvestedCapitalPair,
    ReconciliationStatus,
    build_bottom_up_invested_capital,
    build_financing_identity_invested_capital,
    component_from_source,
    reconcile_invested_capital,
)

AS_OF = date(2026, 6, 27)


def _reported(value: float, name: str) -> ICComponent:
    return component_from_source(value, provenance=[f"source:{name}"])


def _financing_components() -> dict[str, ICComponent]:
    return {
        "common_equity": _reported(100.0, "equity"),
        "short_term_debt": _reported(10.0, "short-debt"),
        "long_term_debt": _reported(40.0, "long-debt"),
        "operating_lease_liabilities": _reported(5.0, "leases"),
        "minority_interest": _reported(2.0, "minority"),
        "cash_and_equivalents": _reported(15.0, "cash"),
        "short_term_investments": _reported(3.0, "short-investments"),
        "long_term_marketable_securities": _reported(2.0, "long-securities"),
    }


def _bottom_up_components() -> dict[str, ICComponent]:
    return {
        "current_assets": _reported(100.0, "current-assets"),
        "cash_and_equivalents": _reported(10.0, "cash"),
        "short_term_investments": _reported(5.0, "short-investments"),
        "operating_current_liabilities": _reported(30.0, "operating-liabilities"),
        "net_ppe": _reported(50.0, "ppe"),
        "net_intangibles": _reported(20.0, "intangibles"),
        "other_noncurrent_operating_assets": _reported(12.0, "other-assets"),
        "other_noncurrent_operating_liabilities": _reported(7.0, "other-liabilities"),
    }


def test_explicit_source_zero_is_reported_zero() -> None:
    component = component_from_source(0.0, provenance=["fact:zero"])

    assert component.value == 0.0
    assert component.state is DataState.REPORTED_ZERO
    assert component.provenance == ["fact:zero"]


@pytest.mark.parametrize("value", [-1.0, 1.0])
def test_nonzero_source_value_is_reported_value(value: float) -> None:
    component = component_from_source(value, provenance=["fact:value"])

    assert component.value == value
    assert component.state is DataState.REPORTED_VALUE


def test_absent_or_unmapped_evidence_is_missing_not_zero() -> None:
    component = component_from_source(None)

    assert component.value is None
    assert component.state is DataState.MISSING_OR_CONSOLIDATED


def test_missing_component_cannot_be_constructed_as_a_numeric_zero() -> None:
    with pytest.raises(ValueError, match="MISSING_OR_CONSOLIDATED"):
        ICComponent(value=0.0, state=DataState.MISSING_OR_CONSOLIDATED)


def test_complete_financing_identity_computes_deterministic_invested_capital() -> None:
    node = build_financing_identity_invested_capital(AS_OF, _financing_components())

    assert node.method is ICMethod.FINANCING_IDENTITY
    assert node.value == pytest.approx(137.0)
    assert node.state is DataState.REPORTED_VALUE
    assert node.components["common_equity"].provenance == ["source:equity"]


def test_financing_identity_rejects_total_and_component_debt_double_counting() -> None:
    components = _financing_components()
    components["total_debt"] = _reported(50.0, "total-debt")

    with pytest.raises(AccountingError, match="DEBT_DOUBLE_COUNT"):
        build_financing_identity_invested_capital(AS_OF, components)


def test_financing_identity_rejects_total_and_component_securities_double_subtraction() -> None:
    components = _financing_components()
    components["total_marketable_securities"] = _reported(5.0, "total-securities")

    with pytest.raises(AccountingError, match="SECURITIES_DOUBLE_COUNT"):
        build_financing_identity_invested_capital(AS_OF, components)


def test_financing_identity_rejects_total_debt_and_lease_double_counting() -> None:
    components = _financing_components()
    components.pop("short_term_debt")
    components.pop("long_term_debt")
    components["total_debt"] = _reported(55.0, "debt-including-leases")

    with pytest.raises(AccountingError, match="LEASE_DOUBLE_COUNT"):
        build_financing_identity_invested_capital(AS_OF, components)


def test_missing_required_primary_component_fails_closed() -> None:
    components = _financing_components()
    components["common_equity"] = component_from_source(None)

    node = build_financing_identity_invested_capital(AS_OF, components)

    assert node.value is None
    assert node.state is DataState.MISSING_OR_CONSOLIDATED
    assert node.components["common_equity"].value is None


def test_complete_bottom_up_identity_includes_noncurrent_operating_liabilities() -> None:
    node = build_bottom_up_invested_capital(AS_OF, _bottom_up_components())

    assert node.method is ICMethod.BOTTOM_UP
    assert node.value == pytest.approx(130.0)


def test_missing_intangible_disclosure_leaves_bottom_up_incomplete() -> None:
    components = _bottom_up_components()
    components["net_intangibles"] = component_from_source(None)

    node = build_bottom_up_invested_capital(AS_OF, components)

    assert node.value is None
    assert node.state is DataState.MISSING_OR_CONSOLIDATED
    assert node.components["net_intangibles"].value is None


@pytest.mark.parametrize(
    ("top_down_value", "bottom_up_value", "status"),
    [
        (100.0, 105.0, ReconciliationStatus.ALIGNED),
        (100.0, 106.0, ReconciliationStatus.MATERIAL_GAP),
        (0.0, 0.0, ReconciliationStatus.ALIGNED),
        (0.0, 1.0, ReconciliationStatus.MATERIAL_GAP),
    ],
)
def test_reconciliation_uses_endpoint_local_gap_rules(
    top_down_value: float,
    bottom_up_value: float,
    status: ReconciliationStatus,
) -> None:
    top_down = build_financing_identity_invested_capital(
        AS_OF,
        {
            "common_equity": _reported(top_down_value, "equity"),
            "short_term_debt": _reported(0.0, "short-debt"),
            "long_term_debt": _reported(0.0, "long-debt"),
            "cash_and_equivalents": _reported(0.0, "cash"),
            "short_term_investments": _reported(0.0, "investments"),
            "long_term_marketable_securities": _reported(0.0, "securities"),
        },
    )
    bottom_up = build_bottom_up_invested_capital(
        AS_OF,
        {
            "current_assets": _reported(bottom_up_value, "current-assets"),
            "cash_and_equivalents": _reported(0.0, "cash"),
            "short_term_investments": _reported(0.0, "investments"),
            "operating_current_liabilities": _reported(0.0, "current-liabilities"),
            "net_ppe": _reported(0.0, "ppe"),
            "net_intangibles": _reported(0.0, "intangibles"),
            "other_noncurrent_operating_assets": _reported(0.0, "other-assets"),
            "other_noncurrent_operating_liabilities": _reported(0.0, "other-liabilities"),
        },
    )

    reconciliation = reconcile_invested_capital(AS_OF, top_down, bottom_up)

    assert reconciliation.status is status


def test_missing_bottom_up_is_insufficient_but_primary_average_remains_available() -> None:
    opening = reconcile_invested_capital(
        AS_OF,
        build_financing_identity_invested_capital(AS_OF, _financing_components()),
        None,
    )
    closing_components = _financing_components()
    closing_components["common_equity"] = _reported(200.0, "closing-equity")
    closing = reconcile_invested_capital(
        date(2027, 6, 27),
        build_financing_identity_invested_capital(date(2027, 6, 27), closing_components),
        None,
    )

    pair = InvestedCapitalPair(opening=opening, closing=closing)

    assert opening.status is ReconciliationStatus.INSUFFICIENT_DATA
    assert pair.average == pytest.approx(187.0)


def test_material_gap_fails_closed_for_average_without_affecting_other_endpoint_status() -> None:
    opening_top_down = build_financing_identity_invested_capital(AS_OF, _financing_components())
    opening_bottom_up = _bottom_up_components()
    opening_bottom_up["other_noncurrent_operating_assets"] = _reported(19.0, "aligned")
    opening = reconcile_invested_capital(
        AS_OF,
        opening_top_down,
        build_bottom_up_invested_capital(AS_OF, opening_bottom_up),
    )
    closing = reconcile_invested_capital(
        date(2027, 6, 27),
        build_financing_identity_invested_capital(date(2027, 6, 27), _financing_components()),
        build_bottom_up_invested_capital(date(2027, 6, 27), _bottom_up_components()),
    )

    pair = InvestedCapitalPair(opening=opening, closing=closing)

    assert opening.status is ReconciliationStatus.ALIGNED
    assert closing.status is ReconciliationStatus.MATERIAL_GAP
    with pytest.raises(ValueError, match="unresolved material reconciliation gap"):
        _ = pair.average
