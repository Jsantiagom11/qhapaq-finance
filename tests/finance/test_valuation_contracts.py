from __future__ import annotations

import inspect
from dataclasses import replace

import pytest

from qhapaq_finance import valuation
from qhapaq_finance.accounting import InvestedCapitalPair


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

    full_reinvestment = run_valuation(replace(inputs, reinvestment_rate=1.0))
    assert full_reinvestment.implied_growth_from_reinvestment == pytest.approx(
        full_reinvestment.roic
    )

    for invalid_rate in (-0.01, 1.01):
        with pytest.raises(valuation.ValuationError, match="between 0% and 100%"):
            run_valuation(replace(inputs, reinvestment_rate=invalid_rate))
