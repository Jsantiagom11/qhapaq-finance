import importlib
import importlib.util
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from qhapaq_finance.valuation import load_fixture_case, value_scenario

ROOT = Path(__file__).parents[1]


def _monte_carlo_module():
    spec = importlib.util.find_spec("qhapaq_finance.monte_carlo")
    assert spec is not None, "Monte Carlo module must provide the FCFF sampling boundary"
    return importlib.import_module("qhapaq_finance.monte_carlo")


def _base_case_and_scenario():
    case = load_fixture_case("QCOM", ROOT)
    return case, next(item for item in case.scenarios if item.name == "base")


def _assumptions(module, case, scenario, **overrides):
    values = {
        "explicit_growth": module.UniformDistribution(
            scenario.explicit_growth, scenario.explicit_growth
        ),
        "wacc": module.UniformDistribution(case.capital_cost.wacc, case.capital_cost.wacc),
        "terminal_growth": module.UniformDistribution(
            scenario.terminal_growth, scenario.terminal_growth
        ),
        "simulations": 20,
        "seed": 17,
        "max_attempts_per_simulation": 10,
    }
    values.update(overrides)
    return module.MonteCarloAssumptions(**values)


def test_zero_variance_collapse_matches_the_canonical_dcf() -> None:
    module = _monte_carlo_module()
    case, scenario = _base_case_and_scenario()
    deterministic = value_scenario(case, scenario).enterprise_value

    result = module.run_fcff_monte_carlo(case, scenario, _assumptions(module, case, scenario))

    for value in (
        result.mean_enterprise_value,
        result.p05_enterprise_value,
        result.p25_enterprise_value,
        result.p50_enterprise_value,
        result.p75_enterprise_value,
        result.p95_enterprise_value,
    ):
        assert value == pytest.approx(deterministic)
    assert result.standard_deviation_enterprise_value == 0.0


def test_same_seed_produces_identical_summary() -> None:
    module = _monte_carlo_module()
    case, scenario = _base_case_and_scenario()
    assumptions = _assumptions(
        module,
        case,
        scenario,
        explicit_growth=module.UniformDistribution(0.02, 0.08),
        wacc=module.UniformDistribution(0.08, 0.10),
        terminal_growth=module.UniformDistribution(0.02, 0.03),
        simulations=40,
        seed=123,
    )

    assert module.run_fcff_monte_carlo(case, scenario, assumptions) == module.run_fcff_monte_carlo(
        case, scenario, assumptions
    )


def test_requested_simulations_are_all_accepted_when_draws_are_valid() -> None:
    module = _monte_carlo_module()
    case, scenario = _base_case_and_scenario()
    result = module.run_fcff_monte_carlo(
        case,
        scenario,
        _assumptions(module, case, scenario, simulations=37),
    )

    assert result.requested_simulations == 37
    assert result.accepted_simulations == 37
    assert result.rejected_draws == 0


def test_invalid_terminal_draws_are_rejected_then_resampled() -> None:
    module = _monte_carlo_module()
    case, scenario = _base_case_and_scenario()
    result = module.run_fcff_monte_carlo(
        case,
        scenario,
        _assumptions(
            module,
            case,
            scenario,
            terminal_growth=module.UniformDistribution(0.07, 0.10),
            simulations=12,
            seed=7,
            max_attempts_per_simulation=100,
        ),
    )

    assert result.accepted_simulations == 12
    assert result.rejected_draws > 0


def test_impossible_terminal_domain_fails_closed() -> None:
    module = _monte_carlo_module()
    case, scenario = _base_case_and_scenario()
    assumptions = _assumptions(
        module,
        case,
        scenario,
        terminal_growth=module.UniformDistribution(0.10, 0.10),
        max_attempts_per_simulation=3,
    )

    with pytest.raises(module.MonteCarloError, match="UNABLE_TO_GENERATE_VALID_SAMPLES"):
        module.run_fcff_monte_carlo(case, scenario, assumptions)


@pytest.mark.parametrize("value", (math.nan, math.inf, -math.inf))
def test_nonfinite_distribution_bounds_fail_closed(value: float) -> None:
    module = _monte_carlo_module()

    with pytest.raises(module.MonteCarloError, match="DISTRIBUTION_INVALID"):
        module.UniformDistribution(value, 0.05)


def test_monte_carlo_delegates_each_accepted_draw_to_value_scenario(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _monte_carlo_module()
    case, scenario = _base_case_and_scenario()
    calls = 0

    def canonical_value(case, scenario):
        nonlocal calls
        calls += 1
        return SimpleNamespace(enterprise_value=123_456.0)

    monkeypatch.setattr(module, "value_scenario", canonical_value)
    result = module.run_fcff_monte_carlo(
        case,
        scenario,
        _assumptions(module, case, scenario, simulations=4),
    )

    assert calls == 4
    assert result.mean_enterprise_value == 123_456.0


def test_monte_carlo_rejects_a_nonfinite_canonical_valuation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _monte_carlo_module()
    case, scenario = _base_case_and_scenario()
    monkeypatch.setattr(
        module,
        "value_scenario",
        lambda case, scenario: SimpleNamespace(enterprise_value=math.inf),
    )

    with pytest.raises(module.MonteCarloError, match="NONFINITE_VALUATION_RESULT"):
        module.run_fcff_monte_carlo(
            case,
            scenario,
            _assumptions(module, case, scenario, max_attempts_per_simulation=2),
        )
