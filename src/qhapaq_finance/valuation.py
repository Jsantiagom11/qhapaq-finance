"""Deterministic FCFF/WACC valuation domain for reusable research cases.

All monetary inputs must use one consistent unit within a case (the shipped fixtures
use USD millions).  This module deliberately has no market-data or presentation
dependency.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

from . import capital_cost
from .accounting import InvestedCapitalPair
from .financial_primitives import calculate_fcff, calculate_nopat, calculate_roic
from .market_inputs import MarketProvenance, compatibility_market_provenance


class ValuationError(ValueError):
    """Raised when a valuation assumption is economically impossible."""


TERMINAL_VALUE_SHARE_WARNING = 0.75
MIN_TERMINAL_SPREAD = 1e-4


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValuationError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValuationError(f"{field} must be finite")
    return result


def _rate(value: Any, field: str) -> float:
    result = _number(value, field)
    if result <= -1.0 or result >= 1.0:
        raise ValuationError(f"{field} must be between -100% and 100%")
    return result


def _tax_rate(value: Any, field: str) -> float:
    result = _number(value, field)
    if not 0 <= result < 1:
        raise ValuationError(f"{field} must be between 0% and 100%")
    return result


def _positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValuationError(f"{field} must be a positive integer")
    return value


@dataclass(frozen=True)
class CapitalCost:
    risk_free_rate: float
    equity_risk_premium: float
    beta: float
    cost_of_equity: float
    pre_tax_cost_of_debt: float
    tax_rate: float
    market_equity: float
    debt: float
    equity_weight: float
    debt_weight: float
    wacc: float
    source_mode: str = "legacy"
    provenance: object | None = None

    @classmethod
    def from_assumptions(
        cls,
        *,
        risk_free_rate: float,
        equity_risk_premium: float,
        beta: float,
        pre_tax_cost_of_debt: float,
        tax_rate: float,
        market_equity: float,
        debt: float,
    ) -> CapitalCost:
        rf, erp, beta_value = (
            _rate(risk_free_rate, "risk_free_rate"),
            _rate(equity_risk_premium, "equity_risk_premium"),
            _number(beta, "beta"),
        )
        kd, tax = (
            _rate(pre_tax_cost_of_debt, "pre_tax_cost_of_debt"),
            _tax_rate(tax_rate, "tax_rate"),
        )
        equity, debt_value = _number(market_equity, "market_equity"), _number(debt, "debt")
        if beta_value < 0 or equity <= 0 or debt_value < 0:
            raise ValuationError(
                "beta must be non-negative; market_equity positive; debt non-negative"
            )
        if equity + debt_value <= 0:
            raise ValuationError("capital must be positive")
        ke, ew, dw, wacc = capital_cost._calculate_wacc_components(
            risk_free_rate=rf,
            equity_risk_premium=erp,
            beta=beta_value,
            pre_tax_cost_of_debt=kd,
            tax_rate=tax,
            market_equity=equity,
            debt=debt_value,
        )
        if ke <= -1 or not math.isfinite(ke):
            raise ValuationError("cost_of_equity is invalid")
        return cls(
            rf,
            erp,
            beta_value,
            ke,
            kd,
            tax,
            equity,
            debt_value,
            ew,
            dw,
            wacc,
            "legacy",
            None,
        )

    @classmethod
    def from_determination(cls, determination: object) -> CapitalCost:
        """Adapt a validated capital-cost domain result into the valuation engine."""
        provenance = getattr(determination, "provenance", None)
        if getattr(provenance, "source_mode", None) != "canonical":
            raise ValuationError("CANONICAL_CAPITAL_COST_REQUIRED")
        fields = (
            "risk_free_rate",
            "equity_risk_premium",
            "beta",
            "cost_of_equity",
            "pre_tax_cost_of_debt",
            "tax_rate",
            "market_equity",
            "debt",
            "equity_weight",
            "debt_weight",
            "wacc",
        )
        try:
            values = {field: float(getattr(determination, field)) for field in fields}
            return cls(
                risk_free_rate=values["risk_free_rate"],
                equity_risk_premium=values["equity_risk_premium"],
                beta=values["beta"],
                cost_of_equity=values["cost_of_equity"],
                pre_tax_cost_of_debt=values["pre_tax_cost_of_debt"],
                tax_rate=values["tax_rate"],
                market_equity=values["market_equity"],
                debt=values["debt"],
                equity_weight=values["equity_weight"],
                debt_weight=values["debt_weight"],
                wacc=values["wacc"],
                source_mode="canonical",
                provenance=provenance,
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValuationError("CANONICAL_CAPITAL_COST_INVALID") from exc


@dataclass(frozen=True)
class FcffInputs:
    ebit: float
    tax_rate: float
    depreciation_amortization: float
    capex: float
    change_in_nwc: float

    def reconstructed_fcff(self) -> float:
        return calculate_fcff(
            nopat=calculate_nopat(ebit=self.ebit, tax_rate=self.tax_rate),
            depreciation_amortization=self.depreciation_amortization,
            capex=self.capex,
            change_in_working_capital=self.change_in_nwc,
        )


@dataclass(frozen=True)
class NormalizationAdjustment:
    label: str
    amount: float


@dataclass(frozen=True)
class ScenarioAssumptions:
    name: str
    explicit_growth: float
    terminal_growth: float
    years: int


@dataclass(frozen=True)
class MarketSnapshot:
    price: float
    shares_outstanding: float
    cash_and_equivalents: float
    debt: float
    other_senior_claims: float = 0.0
    marketable_securities: float = 0.0

    @property
    def liquid_assets(self) -> float:
        """Cash plus separately represented marketable securities."""
        return self.cash_and_equivalents + self.marketable_securities

    @property
    def equity_value(self) -> float:
        return self.price * self.shares_outstanding

    @property
    def enterprise_value(self) -> float:
        return self.equity_value - self.liquid_assets + self.debt + self.other_senior_claims


@dataclass(frozen=True)
class ValuationInput:
    # Single pure input contract for the canonical valuation kernel.
    fcff: float
    nopat: float
    wacc: float
    market_equity: float
    debt: float
    cash: float
    marketable_securities: float
    invested_capital: InvestedCapitalPair | None
    reinvestment_rate: float | None = None
    other_senior_claims: float = 0.0


@dataclass(frozen=True)
class ValuationOutput:
    # Pure metrics; optional extensions disappear without invested capital.
    fcff: float
    wacc: float
    enterprise_value: float
    fcff_yield: float
    roic: float | None
    implied_growth_from_reinvestment: float | None
    roic_minus_wacc: float | None


def run_valuation(inputs: ValuationInput) -> ValuationOutput:
    # Run FCFF/WACC metrics without requiring invested-capital evidence.
    fcff = _number(inputs.fcff, "fcff")
    nopat = _number(inputs.nopat, "nopat")
    wacc = _rate(inputs.wacc, "wacc")
    if wacc < 0:
        raise ValuationError("wacc must be non-negative")

    market_equity = _number(inputs.market_equity, "market_equity")
    debt = _number(inputs.debt, "debt")
    cash = _number(inputs.cash, "cash")
    securities = _number(inputs.marketable_securities, "marketable_securities")
    senior_claims = _number(inputs.other_senior_claims, "other_senior_claims")

    if market_equity <= 0:
        raise ValuationError("market_equity must be positive")
    if min(debt, cash, securities, senior_claims) < 0:
        raise ValuationError("capital-structure inputs must be non-negative")

    enterprise_value = market_equity + debt + senior_claims - cash - securities
    if enterprise_value <= 0:
        raise ValuationError("enterprise_value must be positive")

    reinvestment_rate = None
    if inputs.reinvestment_rate is not None:
        reinvestment_rate = _number(inputs.reinvestment_rate, "reinvestment_rate")
        if not 0 <= reinvestment_rate <= 1:
            raise ValuationError("reinvestment_rate must be between 0% and 100%")

    roic = implied_growth = roic_minus_wacc = None
    if inputs.invested_capital is not None:
        try:
            roic = calculate_roic(
                nopat=nopat,
                invested_capital=inputs.invested_capital.average,
            )
        except ValueError as exc:
            raise ValuationError(str(exc)) from exc
        roic_minus_wacc = roic - wacc
        if reinvestment_rate is not None:
            implied_growth = reinvestment_rate * roic

    return ValuationOutput(
        fcff=fcff,
        wacc=wacc,
        enterprise_value=enterprise_value,
        fcff_yield=fcff / enterprise_value,
        roic=roic,
        implied_growth_from_reinvestment=implied_growth,
        roic_minus_wacc=roic_minus_wacc,
    )


@dataclass(frozen=True)
class ResearchCase:
    ticker: str
    as_of_date: date
    provenance: str
    financial_inputs: FcffInputs
    normalization_adjustments: tuple[NormalizationAdjustment, ...]
    capital_cost: CapitalCost
    invested_capital: float
    reinvestment_rate: float
    scenarios: tuple[ScenarioAssumptions, ...]
    market_snapshot: MarketSnapshot
    thesis: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    risk_notes: tuple[str, ...]
    market_provenance: MarketProvenance | None = None


@dataclass(frozen=True)
class ScenarioValuation:
    name: str
    enterprise_value: float
    equity_value: float
    intrinsic_value_per_share: float
    terminal_growth: float
    terminal_spread: float
    pv_explicit_period: float
    pv_terminal_value: float
    terminal_value_share: float
    margin_of_safety: float
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class ResearchResult:
    case: ResearchCase
    reconstructed_fcff: float
    normalized_fcff: float
    nopat: float
    roic: float
    implied_growth_from_reinvestment: float
    growth_consistency: str
    scenarios: tuple[ScenarioValuation, ...]
    fcff_implied_discount_rate: float
    reverse_implied_growth: float
    roic_minus_wacc: float
    expectation_growth_gap: float
    fcff_yield: float
    diagnostics: tuple[str, ...]


@dataclass(frozen=True)
class _FcffPresentValue:
    pv_explicit_period: float
    pv_terminal_value: float
    enterprise_value: float


def _validate_case(case: ResearchCase) -> None:
    if not case.ticker:
        raise ValuationError("ticker must be present")
    if _number(case.invested_capital, "invested_capital") <= 0:
        raise ValuationError("ticker must be present and invested_capital must be positive")
    if len({scenario.name for scenario in case.scenarios}) != 3 or {
        s.name for s in case.scenarios
    } != {"bear", "base", "bull"}:
        raise ValuationError("cases must provide exactly bear, base, and bull scenarios")
    if not 0 <= _number(case.reinvestment_rate, "reinvestment_rate") <= 1:
        raise ValuationError("reinvestment_rate must be between 0% and 100%")
    market = case.market_snapshot
    if (
        _number(market.shares_outstanding, "shares_outstanding") <= 0
        or _number(market.price, "market price") <= 0
    ):
        raise ValuationError("market price and shares_outstanding must be positive")
    for field, value in (
        ("cash_and_equivalents", market.cash_and_equivalents),
        ("marketable_securities", market.marketable_securities),
        ("debt", market.debt),
        ("other_senior_claims", market.other_senior_claims),
    ):
        if _number(value, field) < 0:
            raise ValuationError("cash, debt, and senior claims must be non-negative")
    if not math.isfinite(market.enterprise_value) or market.enterprise_value <= 0:
        raise ValuationError("market enterprise value must be positive and finite")
    for field, value in (
        ("ebit", case.financial_inputs.ebit),
        ("depreciation_amortization", case.financial_inputs.depreciation_amortization),
        ("capex", case.financial_inputs.capex),
        ("change_in_nwc", case.financial_inputs.change_in_nwc),
        ("invested_capital", case.invested_capital),
    ):
        _number(value, field)
    if case.financial_inputs.depreciation_amortization < 0 or case.financial_inputs.capex < 0:
        raise ValuationError("depreciation_amortization and capex must be non-negative")
    _tax_rate(case.financial_inputs.tax_rate, "financial_inputs.tax_rate")
    capital = case.capital_cost
    for field, value in (
        ("risk_free_rate", capital.risk_free_rate),
        ("equity_risk_premium", capital.equity_risk_premium),
        ("beta", capital.beta),
        ("cost_of_equity", capital.cost_of_equity),
        ("pre_tax_cost_of_debt", capital.pre_tax_cost_of_debt),
        ("tax_rate", capital.tax_rate),
        ("market_equity", capital.market_equity),
        ("debt", capital.debt),
        ("equity_weight", capital.equity_weight),
        ("debt_weight", capital.debt_weight),
        ("wacc", capital.wacc),
    ):
        _number(value, field)
    _rate(capital.risk_free_rate, "risk_free_rate")
    _rate(capital.equity_risk_premium, "equity_risk_premium")
    _rate(capital.pre_tax_cost_of_debt, "pre_tax_cost_of_debt")
    _tax_rate(capital.tax_rate, "tax_rate")
    if capital.market_equity <= 0 or capital.debt < 0 or capital.beta < 0:
        raise ValuationError(
            "capital structure must have positive equity and non-negative debt/beta"
        )
    if not math.isclose(capital.market_equity, market.equity_value, abs_tol=1e-9):
        raise ValuationError("capital market_equity must match the market snapshot")
    if not math.isclose(capital.debt, market.debt, abs_tol=1e-9):
        raise ValuationError("capital debt must match the market snapshot")
    if not math.isclose(capital.equity_weight + capital.debt_weight, 1.0, abs_tol=1e-9):
        raise ValuationError("debt/equity capital weights must sum to one")
    if capital.equity_weight < 0 or capital.debt_weight < 0 or capital.wacc <= 0:
        raise ValuationError("capital weights must be non-negative and WACC must be positive")
    expected_equity_weight = capital.market_equity / (capital.market_equity + capital.debt)
    expected_cost_of_equity = capital.risk_free_rate + capital.beta * capital.equity_risk_premium
    expected_wacc = expected_equity_weight * expected_cost_of_equity + (
        1 - expected_equity_weight
    ) * capital.pre_tax_cost_of_debt * (1 - capital.tax_rate)
    if not (
        math.isclose(capital.equity_weight, expected_equity_weight, abs_tol=1e-9)
        and math.isclose(capital.cost_of_equity, expected_cost_of_equity, abs_tol=1e-9)
        and math.isclose(capital.wacc, expected_wacc, abs_tol=1e-9)
    ):
        raise ValuationError("capital-cost components are not internally coherent")


def _value_fcff(
    *,
    starting_fcff: float,
    growth: float,
    terminal_growth: float,
    discount_rate: float,
    years: int,
) -> _FcffPresentValue:
    """Value FCFF through an explicit period plus a Gordon-growth terminal value."""
    starting_fcff = _number(starting_fcff, "starting_fcff")
    growth = _rate(growth, "growth")
    terminal_growth = _rate(terminal_growth, "terminal_growth")
    discount_rate = _rate(discount_rate, "discount_rate")
    _positive_int(years, "years")
    if discount_rate - terminal_growth < MIN_TERMINAL_SPREAD:
        raise ValuationError("terminal_growth must be at least 1 bp below discount_rate")
    pv_explicit_period, cash_flow = 0.0, starting_fcff
    for year in range(1, years + 1):
        cash_flow *= 1 + growth
        pv_explicit_period += cash_flow / (1 + discount_rate) ** year
    pv_terminal_value = (
        cash_flow
        * (1 + terminal_growth)
        / (discount_rate - terminal_growth)
        / (1 + discount_rate) ** years
    )
    enterprise_value = pv_explicit_period + pv_terminal_value
    if not math.isfinite(enterprise_value) or enterprise_value <= 0:
        raise ValuationError("FCFF present value must be positive and finite")
    return _FcffPresentValue(pv_explicit_period, pv_terminal_value, enterprise_value)


def value_scenario(case: ResearchCase, scenario: ScenarioAssumptions) -> ScenarioValuation:
    _validate_case(case)
    _positive_int(scenario.years, "scenario years")
    growth, terminal_growth, wacc = (
        _rate(scenario.explicit_growth, "explicit_growth"),
        _rate(scenario.terminal_growth, "terminal_growth"),
        case.capital_cost.wacc,
    )
    if wacc - terminal_growth < MIN_TERMINAL_SPREAD:
        raise ValuationError("terminal_growth must be at least 1 bp below discount_rate (WACC)")
    adjustments = tuple(
        _number(x.amount, "normalization adjustment") for x in case.normalization_adjustments
    )
    normalized = case.financial_inputs.reconstructed_fcff() + sum(adjustments)
    if not math.isfinite(normalized):
        raise ValuationError("normalized FCFF must be finite")
    present_value = _value_fcff(
        starting_fcff=normalized,
        growth=growth,
        terminal_growth=terminal_growth,
        discount_rate=wacc,
        years=scenario.years,
    )
    pv_explicit, pv_terminal, enterprise = (
        present_value.pv_explicit_period,
        present_value.pv_terminal_value,
        present_value.enterprise_value,
    )
    market = case.market_snapshot
    equity = enterprise + market.liquid_assets - market.debt - market.other_senior_claims
    if equity <= 0:
        raise ValuationError("enterprise-to-equity bridge produced non-positive equity value")
    share = pv_terminal / enterprise
    if not math.isfinite(share):
        raise ValuationError("terminal value share must be finite")
    warnings = (
        (f"terminal value share exceeds {TERMINAL_VALUE_SHARE_WARNING:.0%}",)
        if share > TERMINAL_VALUE_SHARE_WARNING
        else ()
    )
    intrinsic = equity / market.shares_outstanding
    return ScenarioValuation(
        scenario.name,
        enterprise,
        equity,
        intrinsic,
        terminal_growth,
        wacc - terminal_growth,
        pv_explicit,
        pv_terminal,
        share,
        margin_of_safety(market.price, intrinsic),
        warnings,
    )


def margin_of_safety(price: float, intrinsic_value: float) -> float:
    """Return valuation cushion; negative means price exceeds intrinsic value."""
    price, intrinsic_value = _number(price, "price"), _number(intrinsic_value, "intrinsic_value")
    if price <= 0 or intrinsic_value <= 0:
        raise ValuationError("price and intrinsic_value must be positive")
    return 1 - price / intrinsic_value


def valuation_cushion_prices(intrinsic_value: float) -> dict[str, float]:
    """Canonical prices for named margin-of-safety thresholds."""
    value = _number(intrinsic_value, "intrinsic_value")
    if value <= 0:
        raise ValuationError("intrinsic_value must be positive")
    return {
        "mos_10": value * 0.90,
        "mos_20": value * 0.80,
        "mos_25": value * 0.75,
        "mos_30": value * 0.70,
    }


def price_value_classification(price: float, intrinsic_value: float) -> str:
    cushion = margin_of_safety(price, intrinsic_value)
    if cushion < 0:
        return "ABOVE FAIR VALUE"
    if cushion == 0:
        return "FAIR-VALUE ZONE"
    return "WATCH ZONE"


def _pv_fcff(
    starting_fcff: float, growth: float, terminal_growth: float, discount_rate: float, years: int
) -> float:
    return _value_fcff(
        starting_fcff=starting_fcff,
        growth=growth,
        terminal_growth=terminal_growth,
        discount_rate=discount_rate,
        years=years,
    ).enterprise_value


def _bisect(target: float, evaluate: Any, lower: float, upper: float, label: str) -> float:
    target = _number(target, "solver target")
    if target <= 0:
        raise ValuationError("solver target must be positive")
    low_value, high_value = evaluate(lower), evaluate(upper)
    if not math.isfinite(low_value) or not math.isfinite(high_value):
        raise ValuationError(f"{label} solver endpoints must be finite")
    if not min(low_value, high_value) <= target <= max(low_value, high_value):
        raise ValuationError(f"no economically valid solution for {label} within configured bounds")
    if math.isclose(low_value, target, rel_tol=1e-10):
        return lower
    if math.isclose(high_value, target, rel_tol=1e-10):
        return upper
    increasing = high_value > low_value
    for _ in range(256):
        middle = (lower + upper) / 2
        value = evaluate(middle)
        if abs(value - target) / target <= 1e-10:
            return middle
        if (value < target) == increasing:
            lower = middle
        else:
            upper = middle
    raise ValuationError(f"{label} solver did not converge")


def solve_fcff_implied_discount_rate(
    *,
    market_enterprise_value: float,
    starting_fcff: float,
    explicit_growth: float,
    terminal_growth: float,
    years: int,
    lower: float | None = None,
    upper: float = 0.99,
) -> float:
    """Solve the FCFF discount rate implied by an observed enterprise value.

    This is an operating-enterprise valuation rate, not a shareholder expected return.
    """
    terminal = _rate(terminal_growth, "terminal_growth")
    return _bisect(
        market_enterprise_value,
        lambda rate: _pv_fcff(starting_fcff, explicit_growth, terminal, rate, years),
        (terminal + 2 * MIN_TERMINAL_SPREAD if lower is None else _rate(lower, "lower")),
        _rate(upper, "upper"),
        "FCFF-implied discount rate",
    )


def solve_fcff_implied_growth(
    *,
    market_enterprise_value: float,
    starting_fcff: float,
    wacc: float,
    terminal_growth: float,
    years: int,
    lower: float = -0.95,
    upper: float = 0.75,
) -> float:
    """Solve explicit FCFF growth implied by enterprise value under a fixed WACC."""
    return _bisect(
        market_enterprise_value,
        lambda growth: _pv_fcff(starting_fcff, growth, terminal_growth, wacc, years),
        _rate(lower, "lower"),
        _rate(upper, "upper"),
        "reverse DCF growth",
    )


def analyze_case(case: ResearchCase) -> ResearchResult:
    _validate_case(case)
    reconstructed = case.financial_inputs.reconstructed_fcff()
    normalized = reconstructed + sum(item.amount for item in case.normalization_adjustments)
    nopat = calculate_nopat(
        ebit=case.financial_inputs.ebit,
        tax_rate=case.financial_inputs.tax_rate,
    )
    roic = calculate_roic(nopat=nopat, invested_capital=case.invested_capital)
    implied_growth = case.reinvestment_rate * roic
    base = next(s for s in case.scenarios if s.name == "base")
    diagnostic = (
        "consistent"
        if abs(base.explicit_growth - implied_growth) <= 0.02
        else "review: growth differs materially from reinvestment × ROIC"
    )
    scenarios = tuple(value_scenario(case, scenario) for scenario in case.scenarios)
    market_enterprise = case.market_snapshot.enterprise_value
    fcff_implied_discount_rate = solve_fcff_implied_discount_rate(
        market_enterprise_value=market_enterprise,
        starting_fcff=normalized,
        explicit_growth=base.explicit_growth,
        terminal_growth=base.terminal_growth,
        years=base.years,
    )
    reverse_growth = solve_fcff_implied_growth(
        market_enterprise_value=market_enterprise,
        starting_fcff=normalized,
        wacc=case.capital_cost.wacc,
        terminal_growth=base.terminal_growth,
        years=base.years,
    )
    diagnostics = tuple(warning for scenario in scenarios for warning in scenario.warnings)
    return ResearchResult(
        case,
        reconstructed,
        normalized,
        nopat,
        roic,
        implied_growth,
        diagnostic,
        scenarios,
        fcff_implied_discount_rate,
        reverse_growth,
        roic - case.capital_cost.wacc,
        reverse_growth - base.explicit_growth,
        normalized / market_enterprise,
        diagnostics,
    )


def _required(payload: dict[str, Any], key: str) -> Any:
    if key not in payload:
        raise ValuationError(f"missing critical assumption: {key}")
    return payload[key]


def load_research_case(path: str | Path) -> ResearchCase:
    """Load a deterministic, explicitly labelled fixture; it is not live data."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValuationError(f"invalid research case: {path}") from exc
    if (
        raw.get("schema_version") != "0.1"
        or raw.get("fixture_label") != "deterministic example input; not live financial data"
    ):
        raise ValuationError("unsupported or unlabelled research-case fixture")
    financial = _required(raw, "financial_inputs")
    market = _required(raw, "market_snapshot")
    capital = _required(raw, "capital_cost_assumptions")
    if not all(isinstance(item, dict) for item in (financial, market, capital)):
        raise ValuationError("case inputs must be objects")
    fcff = FcffInputs(
        *(
            _number(_required(financial, field), field)
            for field in ("ebit", "tax_rate", "depreciation_amortization", "capex", "change_in_nwc")
        )
    )
    snapshot = MarketSnapshot(
        price=_number(_required(market, "price"), "price"),
        shares_outstanding=_number(_required(market, "shares_outstanding"), "shares_outstanding"),
        cash_and_equivalents=_number(
            _required(market, "cash_and_equivalents"), "cash_and_equivalents"
        ),
        debt=_number(_required(market, "debt"), "debt"),
        other_senior_claims=_number(market.get("other_senior_claims", 0.0), "other_senior_claims"),
    )
    cost = CapitalCost.from_assumptions(
        **{
            key: _number(_required(capital, key), key)
            for key in (
                "risk_free_rate",
                "equity_risk_premium",
                "beta",
                "pre_tax_cost_of_debt",
                "tax_rate",
            )
        },
        market_equity=snapshot.equity_value,
        debt=snapshot.debt,
    )
    adjustments = tuple(
        NormalizationAdjustment(str(item["label"]), _number(item["amount"], "adjustment amount"))
        for item in _required(raw, "normalization_adjustments")
    )
    scenarios = tuple(
        ScenarioAssumptions(
            str(item["name"]),
            _number(item["explicit_growth"], "explicit_growth"),
            _number(item["terminal_growth"], "terminal_growth"),
            _positive_int(item["years"], "years"),
        )
        for item in _required(raw, "scenarios")
    )
    return ResearchCase(
        str(_required(raw, "ticker")).upper(),
        date.fromisoformat(str(_required(raw, "as_of_date"))),
        str(_required(raw, "provenance")),
        fcff,
        adjustments,
        cost,
        _number(_required(raw, "invested_capital"), "invested_capital"),
        _number(_required(raw, "reinvestment_rate"), "reinvestment_rate"),
        scenarios,
        snapshot,
        tuple(raw.get("thesis", [])),
        tuple(raw.get("invalidation_conditions", [])),
        tuple(raw.get("risk_notes", [])),
    )


def load_fixture_case(ticker: str, repository_root: str | Path = ".") -> ResearchCase:
    """Compatibility entrypoint backed by the declarative domain registry."""
    from .universe import DomainRegistry

    registry = DomainRegistry(repository_root)
    case = registry.load_case(ticker)
    if registry.research(registry.issuer_for(ticker).id).get("kind") == "fixture":
        return replace(
            case,
            market_provenance=compatibility_market_provenance(
                root=repository_root,
                ticker=ticker,
                research_as_of=case.as_of_date,
                source_mode="fixture",
            ),
        )
    return case
