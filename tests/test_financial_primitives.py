import math

import pytest

from qhapaq_finance.financial_primitives import (
    FinancialPrimitiveError,
    calculate_change_nwc,
    calculate_effective_tax_rate,
    calculate_fcff,
    calculate_net_working_capital,
    calculate_nopat,
    calculate_roic,
)


def test_working_capital_and_effective_tax_are_explicit_fail_closed_primitives() -> None:
    opening = calculate_net_working_capital(
        operating_current_assets=120, operating_current_liabilities=80
    )
    closing = calculate_net_working_capital(
        operating_current_assets=150, operating_current_liabilities=95
    )
    assert calculate_change_nwc(opening_nwc=opening, closing_nwc=closing) == 15
    assert calculate_effective_tax_rate(tax_expense=20, pretax_income=100) == 0.2


@pytest.mark.parametrize(
    "function, kwargs",
    (
        (
            calculate_net_working_capital,
            {"operating_current_assets": float("nan"), "operating_current_liabilities": 1},
        ),
        (calculate_change_nwc, {"opening_nwc": 1, "closing_nwc": float("nan")}),
        (calculate_effective_tax_rate, {"tax_expense": 1, "pretax_income": 0}),
    ),
)
def test_working_capital_and_effective_tax_reject_invalid_inputs(
    function: object, kwargs: dict[str, float]
) -> None:
    with pytest.raises(FinancialPrimitiveError):
        function(**kwargs)  # type: ignore[operator]


def test_nopat_uses_the_canonical_operating_tax_formula() -> None:
    assert calculate_nopat(ebit=100.0, tax_rate=0.0) == 100.0
    assert calculate_nopat(ebit=100.0, tax_rate=0.2) == 80.0


@pytest.mark.parametrize("ebit, tax_rate", ((math.nan, 0.2), (100.0, math.inf), (100.0, 1.0)))
def test_nopat_fails_closed_for_invalid_inputs(ebit: float, tax_rate: float) -> None:
    with pytest.raises(FinancialPrimitiveError):
        calculate_nopat(ebit=ebit, tax_rate=tax_rate)


def test_fcff_uses_canonical_positive_cash_use_signs() -> None:
    assert (
        calculate_fcff(
            nopat=80.0,
            depreciation_amortization=10.0,
            capex=15.0,
            change_in_working_capital=5.0,
        )
        == 70.0
    )


@pytest.mark.parametrize(
    "field",
    ("nopat", "depreciation_amortization", "capex", "change_in_working_capital"),
)
def test_fcff_rejects_nonfinite_inputs(field: str) -> None:
    inputs = {
        "nopat": 80.0,
        "depreciation_amortization": 10.0,
        "capex": 15.0,
        "change_in_working_capital": 5.0,
    }
    inputs[field] = math.nan
    with pytest.raises(FinancialPrimitiveError):
        calculate_fcff(**inputs)


def test_roic_uses_canonical_nopat_and_rejects_invalid_capital() -> None:
    assert calculate_roic(nopat=20.0, invested_capital=100.0) == 0.2
    with pytest.raises(FinancialPrimitiveError):
        calculate_roic(nopat=20.0, invested_capital=0.0)
