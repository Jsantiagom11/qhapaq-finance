from __future__ import annotations

import inspect
import math
from dataclasses import replace

import pytest

from qhapaq_finance import valuation
from qhapaq_finance.accounting import InvestedCapitalPair

pytestmark = pytest.mark.fast


def _contract():
    if not hasattr(valuation, "ValuationInput") or not hasattr(valuation, "run_valuation"):
        pytest.fail("ValuationInput/run_valuation contract missing")
    return valuation.ValuationInput, valuation.run_valuation


def test_run_valuation_has_one_unified_input_contract() -> None:
    _, run_valuation = _contract()

    assert list(inspect.signature(run_valuation).parameters) == ["inputs"]


def test_run_valuation_without_invested_capital_preserves_fcff_wacc_and_ev() -> None:
    ValuationInput, run_valuation = _contract()

    result = run_valuation(
        ValuationInput(
            fcff=110.0,
            nopat=150.0,
            wacc=0.09,
            market_equity=1_000.0,
            debt=100.0,
            cash=80.0,
            marketable_securities=20.0,
            invested_capital=None,
            reinvestment_rate=0.40,
        )
    )

    assert result.fcff == pytest.approx(110.0)
    assert result.wacc == pytest.approx(0.09)
    assert result.enterprise_value == pytest.approx(1_000.0)
    assert result.fcff_yield == pytest.approx(0.11)
    assert result.roic is None
    assert result.implied_growth_from_reinvestment is None
    assert result.roic_minus_wacc is None


def test_run_valuation_with_invested_capital_adds_optional_extensions() -> None:
    ValuationInput, run_valuation = _contract()

    result = run_valuation(
        ValuationInput(
            fcff=110.0,
            nopat=150.0,
            wacc=0.09,
            market_equity=1_000.0,
            debt=100.0,
            cash=80.0,
            marketable_securities=20.0,
            invested_capital=InvestedCapitalPair(opening=400.0, closing=600.0),
            reinvestment_rate=0.40,
        )
    )

    assert result.enterprise_value == pytest.approx(1_000.0)
    assert result.roic == pytest.approx(0.30)
    assert result.implied_growth_from_reinvestment == pytest.approx(0.12)
    assert result.roic_minus_wacc == pytest.approx(0.21)


def test_run_valuation_enforces_closed_reinvestment_rate_boundary() -> None:
    ValuationInput, run_valuation = _contract()
    inputs = ValuationInput(
        fcff=110.0,
        nopat=150.0,
        wacc=0.09,
        market_equity=1_000.0,
        debt=100.0,
        cash=80.0,
        marketable_securities=20.0,
        invested_capital=InvestedCapitalPair(opening=400.0, closing=600.0),
    )

    for reinvestment_rate, expected_growth in ((0.0, 0.0), (1.0, 0.30)):
        result = run_valuation(replace(inputs, reinvestment_rate=reinvestment_rate))
        assert result.roic == pytest.approx(0.30)
        assert result.implied_growth_from_reinvestment == pytest.approx(expected_growth)

    for invalid_rate in (-0.01, 1.01):
        with pytest.raises(valuation.ValuationError, match="between 0% and 100%"):
            run_valuation(replace(inputs, reinvestment_rate=invalid_rate))


@pytest.mark.parametrize(
    ("invalid_rate", "message"),
    ((True, "must be numeric"), (math.nan, "must be finite"), (math.inf, "must be finite")),
)
def test_run_valuation_preserves_numeric_reinvestment_rate_guard(
    invalid_rate: object,
    message: str,
) -> None:
    ValuationInput, run_valuation = _contract()
    inputs = ValuationInput(
        fcff=110.0,
        nopat=150.0,
        wacc=0.09,
        market_equity=1_000.0,
        debt=100.0,
        cash=80.0,
        marketable_securities=20.0,
        invested_capital=InvestedCapitalPair(opening=400.0, closing=600.0),
    )

    with pytest.raises(valuation.ValuationError, match=message):
        run_valuation(replace(inputs, reinvestment_rate=invalid_rate))
