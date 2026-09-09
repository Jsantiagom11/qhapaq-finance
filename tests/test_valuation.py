from dataclasses import replace
from pathlib import Path

import pytest

from qhapaq_finance import cli
from qhapaq_finance.valuation import (
    TERMINAL_VALUE_SHARE_WARNING,
    CapitalCost,
    FcffInputs,
    ValuationError,
    _pv_fcff,
    analyze_case,
    load_fixture_case,
    margin_of_safety,
    price_value_classification,
    solve_fcff_implied_discount_rate,
    solve_fcff_implied_growth,
    value_scenario,
)

ROOT = Path(__file__).parents[1]


def test_fcff_reconstruction_and_normalization_bridge_conservation() -> None:
    assert FcffInputs(100, 0.2, 10, 15, 5).reconstructed_fcff() == 70
    result = analyze_case(load_fixture_case("QCOM", ROOT))
    assert result.normalized_fcff == result.reconstructed_fcff + sum(
        item.amount for item in result.case.normalization_adjustments
    )


def test_cost_of_equity_market_value_weights_and_wacc() -> None:
    cost = CapitalCost.from_assumptions(
        risk_free_rate=0.04,
        equity_risk_premium=0.05,
        beta=1.2,
        pre_tax_cost_of_debt=0.04,
        tax_rate=0.2,
        market_equity=900,
        debt=100,
    )
    assert cost.cost_of_equity == pytest.approx(0.10)
    assert (cost.equity_weight, cost.debt_weight) == (0.9, 0.1)
    assert cost.wacc == pytest.approx(0.0932)


@pytest.mark.parametrize(
    "kwargs",
    (
        {"market_equity": 0, "debt": 0},
        {"market_equity": 100, "debt": -1},
        {"market_equity": float("nan"), "debt": 1},
        {"market_equity": float("inf"), "debt": 1},
    ),
)
def test_invalid_or_nonfinite_capital_structure_is_rejected(kwargs: dict[str, float]) -> None:
    assumptions = {
        "risk_free_rate": 0.04,
        "equity_risk_premium": 0.05,
        "beta": 1.0,
        "pre_tax_cost_of_debt": 0.04,
        "tax_rate": 0.2,
        "market_equity": 100,
        "debt": 10,
    }
    assumptions.update(kwargs)
    with pytest.raises(ValuationError):
        CapitalCost.from_assumptions(**assumptions)


def test_incoherent_capital_weights_are_rejected() -> None:
    case = load_fixture_case("QCOM", ROOT)
    bad_cost = replace(case.capital_cost, equity_weight=0.8, debt_weight=0.2)
    with pytest.raises(ValuationError, match="internally coherent"):
        analyze_case(replace(case, capital_cost=bad_cost))


def test_fcff_valuation_uses_wacc_and_rejects_terminal_boundary() -> None:
    case = load_fixture_case("QCOM", ROOT)
    base = next(item for item in case.scenarios if item.name == "base")
    result = value_scenario(case, base)
    higher_wacc = CapitalCost.from_assumptions(
        risk_free_rate=case.capital_cost.risk_free_rate,
        equity_risk_premium=0.07,
        beta=case.capital_cost.beta,
        pre_tax_cost_of_debt=case.capital_cost.pre_tax_cost_of_debt,
        tax_rate=case.capital_cost.tax_rate,
        market_equity=case.market_snapshot.equity_value,
        debt=case.market_snapshot.debt,
    )
    assert (
        value_scenario(replace(case, capital_cost=higher_wacc), base).enterprise_value
        < result.enterprise_value
    )
    assert result.terminal_spread == pytest.approx(case.capital_cost.wacc - base.terminal_growth)
    with pytest.raises(ValuationError, match="terminal_growth"):
        value_scenario(case, replace(base, terminal_growth=case.capital_cost.wacc))
    with pytest.raises(ValuationError, match="1 bp"):
        value_scenario(case, replace(base, terminal_growth=case.capital_cost.wacc - 0.00001))


@pytest.mark.parametrize("value", (float("nan"), float("inf"), float("-inf")))
def test_valuation_rejects_nonfinite_wacc_and_terminal_growth(value: float) -> None:
    case = load_fixture_case("QCOM", ROOT)
    base = next(item for item in case.scenarios if item.name == "base")
    with pytest.raises(ValuationError, match="finite"):
        value_scenario(case, replace(base, terminal_growth=value))
    with pytest.raises(ValuationError, match="finite"):
        value_scenario(replace(case, capital_cost=replace(case.capital_cost, wacc=value)), base)


def test_invalid_case_numeric_and_sign_assumptions_are_rejected() -> None:
    case = load_fixture_case("QCOM", ROOT)
    with pytest.raises(ValuationError, match="market price"):
        analyze_case(
            replace(case, market_snapshot=replace(case.market_snapshot, price=float("nan")))
        )
    with pytest.raises(ValuationError, match="non-negative"):
        analyze_case(replace(case, financial_inputs=replace(case.financial_inputs, capex=-1)))
    with pytest.raises(ValuationError, match="invested_capital"):
        analyze_case(replace(case, invested_capital=0))
    with pytest.raises(ValuationError, match="positive integer"):
        value_scenario(case, replace(case.scenarios[0], years=True))


def test_roic_and_growth_reinvestment_consistency_diagnostic() -> None:
    result = analyze_case(load_fixture_case("VRTX", ROOT))
    assert result.roic == pytest.approx(result.nopat / result.case.invested_capital)
    assert result.implied_growth_from_reinvestment == pytest.approx(
        result.roic * result.case.reinvestment_rate
    )
    assert result.growth_consistency == "consistent"


def test_terminal_value_share_uses_present_values_and_threshold_is_strict() -> None:
    case = load_fixture_case("VRTX", ROOT)
    base = next(item for item in case.scenarios if item.name == "base")
    valuation = value_scenario(case, base)
    assert valuation.terminal_value_share == pytest.approx(
        valuation.pv_terminal_value / valuation.enterprise_value
    )
    assert valuation.terminal_value_share < TERMINAL_VALUE_SHARE_WARNING
    assert not valuation.warnings
    assert value_scenario(case, replace(base, terminal_growth=0.06)).warnings


def test_terminal_warning_does_not_fire_at_exact_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import qhapaq_finance.valuation as valuation_module

    case = load_fixture_case("VRTX", ROOT)
    base = next(item for item in case.scenarios if item.name == "base")
    share = value_scenario(case, base).terminal_value_share
    monkeypatch.setattr(valuation_module, "TERMINAL_VALUE_SHARE_WARNING", share)
    assert not value_scenario(case, base).warnings


def test_enterprise_to_equity_bridge_and_margin_of_safety() -> None:
    result = analyze_case(load_fixture_case("CSCO", ROOT))
    case = result.case
    base = next(item for item in result.scenarios if item.name == "base")
    market = result.case.market_snapshot
    assert base.equity_value == pytest.approx(
        base.enterprise_value + market.cash_and_equivalents - market.debt
    )
    assert base.margin_of_safety == pytest.approx(1 - market.price / base.intrinsic_value_per_share)
    with pytest.raises(ValuationError, match="non-positive equity value"):
        value_scenario(
            replace(case, market_snapshot=replace(market, other_senior_claims=1e9)),
            next(item for item in case.scenarios if item.name == "bear"),
        )


@pytest.mark.parametrize(
    ("field", "multiplier", "direction"),
    (
        ("cash_and_equivalents", 1.25, "higher"),
        ("marketable_securities", 1.25, "higher"),
        ("debt", 1.25, "lower"),
        ("shares_outstanding", 2.0, "lower"),
    ),
)
def test_enterprise_to_equity_bridge_monotonicity(
    field: str, multiplier: float, direction: str
) -> None:
    case = load_fixture_case("QCOM", ROOT)
    base = next(item for item in case.scenarios if item.name == "base")
    baseline = value_scenario(case, base).intrinsic_value_per_share
    market_update = {field: getattr(case.market_snapshot, field) * multiplier}
    changed_market = replace(case.market_snapshot, **market_update)
    changed_case = replace(case, market_snapshot=changed_market)
    if field in {"debt", "shares_outstanding"}:
        changed_case = replace(
            changed_case,
            capital_cost=CapitalCost.from_assumptions(
                risk_free_rate=case.capital_cost.risk_free_rate,
                equity_risk_premium=case.capital_cost.equity_risk_premium,
                beta=case.capital_cost.beta,
                pre_tax_cost_of_debt=case.capital_cost.pre_tax_cost_of_debt,
                tax_rate=case.capital_cost.tax_rate,
                market_equity=changed_market.equity_value,
                debt=changed_market.debt,
            ),
        )
    changed = value_scenario(changed_case, base).intrinsic_value_per_share
    assert changed > baseline if direction == "higher" else changed < baseline


def test_bear_base_bull_are_independent() -> None:
    result = analyze_case(load_fixture_case("QCOM", ROOT))
    scenarios = {item.name: item for item in result.scenarios}
    assert (
        scenarios["bear"].intrinsic_value_per_share
        < scenarios["base"].intrinsic_value_per_share
        < scenarios["bull"].intrinsic_value_per_share
    )


@pytest.mark.parametrize("ticker", ["VRTX", "CSCO"])
def test_second_company_synthetic_gate_is_deterministic_and_financially_coherent(
    ticker: str,
) -> None:
    """These are intentionally labelled fixtures, not empirical company evidence."""
    first = analyze_case(load_fixture_case(ticker, ROOT))
    second = analyze_case(load_fixture_case(ticker, ROOT))
    valuations = {item.name: item for item in first.scenarios}
    assert first == second
    assert (
        valuations["bear"].intrinsic_value_per_share < valuations["base"].intrinsic_value_per_share
    )
    assert (
        valuations["base"].intrinsic_value_per_share < valuations["bull"].intrinsic_value_per_share
    )


def test_cushion_and_price_value_classification_share_one_financial_contract() -> None:
    assert margin_of_safety(80, 100) == pytest.approx(0.20)
    assert margin_of_safety(120, 100) == pytest.approx(-0.20)
    assert price_value_classification(120, 100) == "ABOVE FAIR VALUE"
    assert price_value_classification(100, 100) == "FAIR-VALUE ZONE"
    assert price_value_classification(80, 100) == "WATCH ZONE"


def test_reverse_dcf_convergence_boundary_and_no_solution() -> None:
    case = load_fixture_case("QCOM", ROOT)
    base = next(item for item in case.scenarios if item.name == "base")
    target = _pv_fcff(100, 0.05, base.terminal_growth, case.capital_cost.wacc, base.years)
    assert solve_fcff_implied_growth(
        market_enterprise_value=target,
        starting_fcff=100,
        wacc=case.capital_cost.wacc,
        terminal_growth=base.terminal_growth,
        years=base.years,
    ) == pytest.approx(0.05)
    boundary = _pv_fcff(100, -0.95, base.terminal_growth, case.capital_cost.wacc, base.years)
    assert (
        solve_fcff_implied_growth(
            market_enterprise_value=boundary,
            starting_fcff=100,
            wacc=case.capital_cost.wacc,
            terminal_growth=base.terminal_growth,
            years=base.years,
        )
        == -0.95
    )
    with pytest.raises(ValuationError, match="reverse DCF growth"):
        solve_fcff_implied_growth(
            market_enterprise_value=1e30,
            starting_fcff=100,
            wacc=case.capital_cost.wacc,
            terminal_growth=base.terminal_growth,
            years=base.years,
        )


def test_fcff_implied_discount_rate_convergence_and_no_solution() -> None:
    target = _pv_fcff(100, 0.05, 0.03, 0.09, 8)
    assert solve_fcff_implied_discount_rate(
        market_enterprise_value=target,
        starting_fcff=100,
        explicit_growth=0.05,
        terminal_growth=0.03,
        years=8,
    ) == pytest.approx(0.09)
    with pytest.raises(ValuationError, match="FCFF-implied discount rate"):
        solve_fcff_implied_discount_rate(
            market_enterprise_value=1e30,
            starting_fcff=100,
            explicit_growth=0.05,
            terminal_growth=0.03,
            years=8,
        )


@pytest.mark.parametrize("ticker", ["QCOM", "VRTX", "CSCO"])
def test_triad_fixture_loading(ticker: str) -> None:
    result = analyze_case(load_fixture_case(ticker, ROOT))
    assert result.case.ticker == ticker
    assert {item.name for item in result.scenarios} == {"bear", "base", "bull"}


def test_triad_comparison_and_cli_regression(capsys: pytest.CaptureFixture[str]) -> None:
    cli.main(["research", "QCOM"])
    assert "fcff_implied_discount_rate=" in capsys.readouterr().out
    cli.main(["compare", "QCOM", "VRTX", "CSCO"])
    output = capsys.readouterr().out
    assert "fcff_implied_discount_rate" in output
    assert all(ticker in output for ticker in ("QCOM", "VRTX", "CSCO"))
