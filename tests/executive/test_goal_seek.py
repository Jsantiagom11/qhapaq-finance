from __future__ import annotations

import importlib
import math
from types import ModuleType

import pytest


def _goal_seek() -> ModuleType:
    try:
        return importlib.import_module("qhapaq_finance.executive.goal_seek")
    except ModuleNotFoundError as exc:
        pytest.fail(f"goal seek module missing: {exc}", pytrace=False)


def _inputs(module: ModuleType, **overrides: object) -> object:
    values: dict[str, object] = {
        "observed_enterprise_value": 1_000.0,
        "starting_fcff": 100.0,
        "hurdle_rate": 0.094,
        "terminal_growth_rate": 0.03,
        "years": 10,
    }
    values.update(overrides)
    return module.GoalSeekInputs(**values)


def _canonical_value(
    *,
    growth: float,
    starting_fcff: float = 100.0,
    hurdle_rate: float = 0.094,
    terminal_growth_rate: float = 0.03,
    years: int = 10,
) -> float:
    valuation = importlib.import_module("qhapaq_finance.valuation")

    if not hasattr(valuation, "present_value_fcff"):
        pytest.fail(
            "canonical present_value_fcff boundary missing",
            pytrace=False,
        )

    return valuation.present_value_fcff(
        starting_fcff=starting_fcff,
        explicit_growth=growth,
        terminal_growth=terminal_growth_rate,
        wacc=hurdle_rate,
        years=years,
    )


def test_goal_seek_constants_are_v01_contract() -> None:
    module = _goal_seek()

    assert module.LOWER_BOUND == -0.30
    assert module.UPPER_BOUND == 0.70
    assert module.MAX_ITERATIONS == 50
    assert module.RELATIVE_TOLERANCE == 0.001


@pytest.mark.parametrize(
    "observed",
    (None, math.nan, math.inf, -math.inf, 0.0, -1.0),
)
def test_invalid_observed_enterprise_value_fails_closed(
    observed: float | None,
) -> None:
    module = _goal_seek()

    result = module.solve_implied_fcff_growth(_inputs(module, observed_enterprise_value=observed))

    assert result.status is module.ImpliedExpectationStatus.INPUTS_UNAVAILABLE
    assert result.implied_fcff_growth is None
    assert result.solved_enterprise_value is None


@pytest.mark.parametrize(
    "field",
    (
        "starting_fcff",
        "hurdle_rate",
        "terminal_growth_rate",
        "years",
    ),
)
def test_missing_known_input_fails_closed(field: str) -> None:
    module = _goal_seek()

    result = module.solve_implied_fcff_growth(_inputs(module, **{field: None}))

    assert result.status is module.ImpliedExpectationStatus.INPUTS_UNAVAILABLE
    assert result.implied_fcff_growth is None


def test_recovers_known_growth_through_canonical_fcff_engine() -> None:
    module = _goal_seek()
    target = _canonical_value(growth=0.123)

    result = module.solve_implied_fcff_growth(_inputs(module, observed_enterprise_value=target))

    assert result.status is module.ImpliedExpectationStatus.SOLVED
    assert result.implied_fcff_growth == pytest.approx(0.123, abs=0.002)
    assert result.relative_error is not None
    assert result.relative_error <= module.RELATIVE_TOLERANCE
    assert result.solved_enterprise_value is not None
    assert result.iterations <= module.MAX_ITERATIONS


@pytest.mark.parametrize("growth", (-0.30, 0.70))
def test_exact_endpoint_solution_precedes_bisection(
    growth: float,
) -> None:
    module = _goal_seek()
    target = _canonical_value(growth=growth)

    result = module.solve_implied_fcff_growth(_inputs(module, observed_enterprise_value=target))

    assert result.status is module.ImpliedExpectationStatus.SOLVED
    assert result.implied_fcff_growth == growth
    assert result.iterations == 0
    assert result.relative_error == 0.0


def test_target_outside_bounds_returns_no_solution() -> None:
    module = _goal_seek()

    target = _canonical_value(growth=0.80)

    result = module.solve_implied_fcff_growth(_inputs(module, observed_enterprise_value=target))

    assert result.status is module.ImpliedExpectationStatus.NO_SOLUTION_IN_RANGE
    assert result.implied_fcff_growth is None
    assert result.solved_enterprise_value is None
    assert result.iterations == 0


def test_non_finite_engine_result_raises_evaluation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _goal_seek()

    monkeypatch.setattr(
        module,
        "present_value_fcff",
        lambda **_kwargs: math.nan,
    )

    with pytest.raises(module.GoalSeekEvaluationError, match="finite"):
        module.solve_implied_fcff_growth(_inputs(module))


def test_canonical_valuation_error_is_wrapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _goal_seek()
    valuation = importlib.import_module("qhapaq_finance.valuation")

    def fail(**_kwargs: object) -> float:
        raise valuation.ValuationError("invalid canonical valuation")

    monkeypatch.setattr(module, "present_value_fcff", fail)

    with pytest.raises(
        module.GoalSeekEvaluationError,
        match="canonical valuation",
    ):
        module.solve_implied_fcff_growth(_inputs(module))


def test_unexpected_programming_error_is_not_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _goal_seek()

    def fail(**_kwargs: object) -> float:
        raise TypeError("programming defect")

    monkeypatch.setattr(module, "present_value_fcff", fail)

    with pytest.raises(TypeError, match="programming defect"):
        module.solve_implied_fcff_growth(_inputs(module))


def test_exhausted_iteration_budget_raises_convergence_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _goal_seek()

    def discontinuous(
        *,
        explicit_growth: float,
        **_kwargs: object,
    ) -> float:
        return 99.0 if explicit_growth < 0.20 else 101.0

    monkeypatch.setattr(module, "present_value_fcff", discontinuous)

    with pytest.raises(module.GoalSeekConvergenceError, match="50"):
        module.solve_implied_fcff_growth(_inputs(module, observed_enterprise_value=100.0))


def test_only_explicit_growth_changes_during_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _goal_seek()
    calls: list[dict[str, object]] = []

    def evaluator(**kwargs: object) -> float:
        calls.append(dict(kwargs))
        growth = float(kwargs["explicit_growth"])
        return 100.0 * (1.0 + growth)

    monkeypatch.setattr(module, "present_value_fcff", evaluator)

    result = module.solve_implied_fcff_growth(
        _inputs(
            module,
            observed_enterprise_value=110.0,
            starting_fcff=777.0,
            hurdle_rate=0.111,
            terminal_growth_rate=0.025,
            years=7,
        )
    )

    assert result.status is module.ImpliedExpectationStatus.SOLVED
    assert result.implied_fcff_growth == pytest.approx(0.10, abs=0.002)

    assert calls
    assert {call["starting_fcff"] for call in calls} == {777.0}
    assert {call["wacc"] for call in calls} == {0.111}
    assert {call["terminal_growth"] for call in calls} == {0.025}
    assert {call["years"] for call in calls} == {7}
    assert len({call["explicit_growth"] for call in calls}) > 1
