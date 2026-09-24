"""Bounded market-implied FCFF growth for Executive Shortlist."""

from __future__ import annotations

import math
from dataclasses import dataclass

from qhapaq_finance.valuation import ValuationError, present_value_fcff

from .contracts import ImpliedExpectationResult, ImpliedExpectationStatus

LOWER_BOUND = -0.30
UPPER_BOUND = 0.70
MAX_ITERATIONS = 50
RELATIVE_TOLERANCE = 0.001


class GoalSeekEvaluationError(RuntimeError):
    """The canonical FCFF engine failed to produce a valid evaluation."""


class GoalSeekConvergenceError(RuntimeError):
    """The bounded solver exhausted its explicit iteration budget."""


@dataclass(frozen=True)
class GoalSeekInputs:
    """Known inputs required by the canonical FCFF valuation engine."""

    observed_enterprise_value: float | None
    starting_fcff: float | None
    hurdle_rate: float | None
    terminal_growth_rate: float | None
    years: int | None


def _finite_or_none(value: float | None) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return value


def _valid_years(value: int | None) -> int | None:
    if value is None or isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def _result(
    inputs: GoalSeekInputs,
    *,
    status: ImpliedExpectationStatus,
    growth: float | None,
    solved_value: float | None,
    relative_error: float | None,
    iterations: int,
    reason: str | None,
) -> ImpliedExpectationResult:
    return ImpliedExpectationResult(
        implied_fcff_growth=growth,
        starting_fcff=_finite_or_none(inputs.starting_fcff),
        hurdle_rate=_finite_or_none(inputs.hurdle_rate),
        terminal_growth_rate=_finite_or_none(inputs.terminal_growth_rate),
        years=_valid_years(inputs.years),
        observed_enterprise_value=_finite_or_none(inputs.observed_enterprise_value),
        solved_enterprise_value=solved_value,
        relative_error=relative_error,
        lower_bound=LOWER_BOUND,
        upper_bound=UPPER_BOUND,
        iterations=iterations,
        status=status,
        reason=reason,
    )


def _unavailable(
    inputs: GoalSeekInputs,
    reason: str,
) -> ImpliedExpectationResult:
    return _result(
        inputs,
        status=ImpliedExpectationStatus.INPUTS_UNAVAILABLE,
        growth=None,
        solved_value=None,
        relative_error=None,
        iterations=0,
        reason=reason,
    )


def _evaluate(inputs: GoalSeekInputs, growth: float) -> float:
    assert inputs.starting_fcff is not None
    assert inputs.hurdle_rate is not None
    assert inputs.terminal_growth_rate is not None
    assert inputs.years is not None

    try:
        result = present_value_fcff(
            starting_fcff=inputs.starting_fcff,
            explicit_growth=growth,
            terminal_growth=inputs.terminal_growth_rate,
            wacc=inputs.hurdle_rate,
            years=inputs.years,
        )
    except ValuationError as exc:
        raise GoalSeekEvaluationError(f"canonical valuation failed: {exc}") from exc

    if not math.isfinite(result):
        raise GoalSeekEvaluationError("canonical valuation result must be finite")

    return result


def _error(value: float, observed: float) -> float:
    return abs(value - observed) / observed


def solve_implied_fcff_growth(
    inputs: GoalSeekInputs,
) -> ImpliedExpectationResult:
    """Solve explicit FCFF growth while all other DCF inputs stay fixed."""

    observed = inputs.observed_enterprise_value

    if observed is None or not math.isfinite(observed) or observed <= 0:
        return _unavailable(
            inputs,
            "observed enterprise value is unavailable",
        )

    required = (
        inputs.starting_fcff,
        inputs.hurdle_rate,
        inputs.terminal_growth_rate,
    )
    if any(value is None or not math.isfinite(value) for value in required):
        return _unavailable(
            inputs,
            "known valuation inputs are unavailable",
        )

    if _valid_years(inputs.years) is None:
        return _unavailable(
            inputs,
            "known valuation inputs are unavailable",
        )

    lower_value = _evaluate(inputs, LOWER_BOUND)
    upper_value = _evaluate(inputs, UPPER_BOUND)

    lower_residual = lower_value - observed
    upper_residual = upper_value - observed

    if lower_residual == 0.0:
        return _result(
            inputs,
            status=ImpliedExpectationStatus.SOLVED,
            growth=LOWER_BOUND,
            solved_value=lower_value,
            relative_error=0.0,
            iterations=0,
            reason=None,
        )

    if upper_residual == 0.0:
        return _result(
            inputs,
            status=ImpliedExpectationStatus.SOLVED,
            growth=UPPER_BOUND,
            solved_value=upper_value,
            relative_error=0.0,
            iterations=0,
            reason=None,
        )

    if (lower_residual > 0) == (upper_residual > 0):
        return _result(
            inputs,
            status=ImpliedExpectationStatus.NO_SOLUTION_IN_RANGE,
            growth=None,
            solved_value=None,
            relative_error=None,
            iterations=0,
            reason="no solution in configured FCFF growth range",
        )

    low = LOWER_BOUND
    high = UPPER_BOUND
    low_residual = lower_residual

    for iteration in range(1, MAX_ITERATIONS + 1):
        midpoint = (low + high) / 2.0
        midpoint_value = _evaluate(inputs, midpoint)
        midpoint_residual = midpoint_value - observed
        relative_error = _error(midpoint_value, observed)

        if relative_error <= RELATIVE_TOLERANCE:
            return _result(
                inputs,
                status=ImpliedExpectationStatus.SOLVED,
                growth=midpoint,
                solved_value=midpoint_value,
                relative_error=relative_error,
                iterations=iteration,
                reason=None,
            )

        if (midpoint_residual > 0) == (low_residual > 0):
            low = midpoint
            low_residual = midpoint_residual
        else:
            high = midpoint

    raise GoalSeekConvergenceError(
        f"FCFF goal seek did not converge within {MAX_ITERATIONS} iterations"
    )
