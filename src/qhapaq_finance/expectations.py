"""Expectation-implied valuation tools independent of market-data providers."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable


class ExpectationsError(ValueError):
    """Raised when reverse-DCF inputs are internally inconsistent."""


@dataclass(frozen=True)
class ReverseDcfInputs:
    """Equity-FCF reverse DCF assumptions.

    `starting_fcf` is an equity-cash-flow measure and `equity_value` is an equity value.
    `discount_rate` must therefore be interpreted as a cost of equity for this model,
    not WACC. The next year's FCF is starting_fcf * (1 + growth).
    """

    equity_value: float
    starting_fcf: float
    discount_rate: float
    terminal_growth: float
    years: int = 10


@dataclass(frozen=True)
class ReverseDcfResult:
    implied_fcf_growth: float
    equity_value: float
    solved_present_value: float
    starting_fcf: float
    discount_rate: float
    terminal_growth: float
    years: int


@dataclass(frozen=True)
class SensitivityPoint:
    discount_rate: float
    terminal_growth: float
    implied_fcf_growth: float


def _finite(value: float, field: str) -> float:
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ExpectationsError(f"{field} must be finite")
    return numeric


def validate_reverse_dcf(inputs: ReverseDcfInputs) -> ReverseDcfInputs:
    equity_value = _finite(inputs.equity_value, "equity_value")
    starting_fcf = _finite(inputs.starting_fcf, "starting_fcf")
    discount_rate = _finite(inputs.discount_rate, "discount_rate")
    terminal_growth = _finite(inputs.terminal_growth, "terminal_growth")
    if equity_value <= 0:
        raise ExpectationsError("equity_value must be positive")
    if starting_fcf <= 0:
        raise ExpectationsError("starting_fcf must be positive")
    if discount_rate <= -1:
        raise ExpectationsError("discount_rate must be greater than -100%")
    if terminal_growth <= -1:
        raise ExpectationsError("terminal_growth must be greater than -100%")
    if discount_rate <= terminal_growth:
        raise ExpectationsError("discount_rate must exceed terminal_growth")
    if not isinstance(inputs.years, int) or isinstance(inputs.years, bool) or inputs.years < 1:
        raise ExpectationsError("years must be a positive integer")
    return inputs


def present_value_equity_fcf(inputs: ReverseDcfInputs, *, growth: float) -> float:
    """Present value projected equity FCF plus a Gordon-growth terminal value."""
    validate_reverse_dcf(inputs)
    growth = _finite(growth, "growth")
    if growth <= -1:
        raise ExpectationsError("growth must be greater than -100%")

    present_value = 0.0
    cash_flow = inputs.starting_fcf
    discount_factor = 1.0
    for _ in range(inputs.years):
        cash_flow *= 1.0 + growth
        discount_factor *= 1.0 + inputs.discount_rate
        present_value += cash_flow / discount_factor

    terminal_cash_flow = cash_flow * (1.0 + inputs.terminal_growth)
    terminal_value = terminal_cash_flow / (inputs.discount_rate - inputs.terminal_growth)
    present_value += terminal_value / discount_factor
    if not math.isfinite(present_value) or present_value <= 0:
        raise ExpectationsError("reverse DCF produced a non-finite or non-positive value")
    return present_value


def solve_implied_fcf_growth(
    inputs: ReverseDcfInputs,
    *,
    lower: float = -0.95,
    upper: float = 0.50,
    tolerance: float = 1e-10,
    max_iterations: int = 256,
) -> ReverseDcfResult:
    """Solve the constant explicit-period FCF growth implied by current equity value.

    Uses deterministic bisection and expands the upper bound when necessary. This avoids
    an additional numerical dependency and gives stable results across environments.
    """
    validate_reverse_dcf(inputs)
    lower = _finite(lower, "lower")
    upper = _finite(upper, "upper")
    tolerance = _finite(tolerance, "tolerance")
    if lower <= -1 or upper <= lower:
        raise ExpectationsError("growth bounds must satisfy -1 < lower < upper")
    if tolerance <= 0:
        raise ExpectationsError("tolerance must be positive")
    if not isinstance(max_iterations, int) or max_iterations < 1:
        raise ExpectationsError("max_iterations must be a positive integer")

    target = inputs.equity_value
    low_value = present_value_equity_fcf(inputs, growth=lower)
    if low_value > target:
        raise ExpectationsError("equity_value implies growth below the configured lower bound")

    high = upper
    high_value = present_value_equity_fcf(inputs, growth=high)
    while high_value < target and high < 10.0:
        high = high * 2.0 + 0.10
        high_value = present_value_equity_fcf(inputs, growth=high)
    if high_value < target:
        raise ExpectationsError("equity_value implies growth above the supported search range")

    low = lower
    midpoint = (low + high) / 2.0
    midpoint_value = present_value_equity_fcf(inputs, growth=midpoint)
    for _ in range(max_iterations):
        midpoint = (low + high) / 2.0
        midpoint_value = present_value_equity_fcf(inputs, growth=midpoint)
        relative_error = abs(midpoint_value - target) / target
        if relative_error <= tolerance:
            break
        if midpoint_value < target:
            low = midpoint
        else:
            high = midpoint
    else:
        raise ExpectationsError("reverse DCF solver did not converge")

    return ReverseDcfResult(
        implied_fcf_growth=midpoint,
        equity_value=target,
        solved_present_value=midpoint_value,
        starting_fcf=inputs.starting_fcf,
        discount_rate=inputs.discount_rate,
        terminal_growth=inputs.terminal_growth,
        years=inputs.years,
    )


def reverse_dcf_sensitivity(
    *,
    equity_value: float,
    starting_fcf: float,
    years: int = 10,
    discount_rates: Iterable[float] = (0.08, 0.09, 0.10),
    terminal_growth_rates: Iterable[float] = (0.02, 0.03, 0.04),
) -> tuple[SensitivityPoint, ...]:
    """Return a deterministic hurdle grid across cost-of-equity and terminal assumptions."""
    rates = tuple(float(value) for value in discount_rates)
    terminal_rates = tuple(float(value) for value in terminal_growth_rates)
    if not rates or not terminal_rates:
        raise ExpectationsError("sensitivity grids must be non-empty")
    points: list[SensitivityPoint] = []
    for discount_rate in rates:
        for terminal_growth in terminal_rates:
            result = solve_implied_fcf_growth(
                ReverseDcfInputs(
                    equity_value=equity_value,
                    starting_fcf=starting_fcf,
                    discount_rate=discount_rate,
                    terminal_growth=terminal_growth,
                    years=years,
                )
            )
            points.append(
                SensitivityPoint(
                    discount_rate=discount_rate,
                    terminal_growth=terminal_growth,
                    implied_fcf_growth=result.implied_fcf_growth,
                )
            )
    return tuple(points)
