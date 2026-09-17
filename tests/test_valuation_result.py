import importlib
import importlib.util
import json
from pathlib import Path

import pytest

from qhapaq_finance.monte_carlo import (
    MonteCarloAssumptions,
    UniformDistribution,
    run_fcff_monte_carlo,
)
from qhapaq_finance.valuation import analyze_case, load_fixture_case

ROOT = Path(__file__).parents[1]


def _contract_module():
    spec = importlib.util.find_spec("qhapaq_finance.valuation_result")
    assert spec is not None, "valuation evidence contract must exist"
    return importlib.import_module("qhapaq_finance.valuation_result")


def _sources():
    case = load_fixture_case("QCOM", ROOT)
    deterministic = analyze_case(case)
    base = next(item for item in case.scenarios if item.name == "base")
    assumptions = MonteCarloAssumptions(
        explicit_growth=UniformDistribution(base.explicit_growth, base.explicit_growth),
        wacc=UniformDistribution(case.capital_cost.wacc, case.capital_cost.wacc),
        terminal_growth=UniformDistribution(base.terminal_growth, base.terminal_growth),
        simulations=20,
        seed=17,
    )
    return deterministic, assumptions, run_fcff_monte_carlo(case, base, assumptions)


def test_valuation_result_composes_existing_engine_outputs() -> None:
    module = _contract_module()
    deterministic, assumptions, monte_carlo = _sources()

    result = module.build_valuation_result(deterministic, assumptions, monte_carlo)
    base = next(item for item in deterministic.scenarios if item.name == "base")

    assert result.deterministic.enterprise_value == base.enterprise_value
    assert result.reverse_dcf.implied_growth == deterministic.reverse_implied_growth
    assert result.monte_carlo.p50_enterprise_value == monte_carlo.p50_enterprise_value


def test_valuation_result_preserves_monte_carlo_assumption_provenance() -> None:
    module = _contract_module()
    deterministic, assumptions, monte_carlo = _sources()

    result = module.build_valuation_result(deterministic, assumptions, monte_carlo)

    assert result.monte_carlo.seed == 17
    assert result.monte_carlo.simulations == 20
    assert result.monte_carlo.explicit_growth == module.DistributionEvidence("uniform", 0.06, 0.06)
    assert result.monte_carlo.wacc.lower == deterministic.case.capital_cost.wacc
    assert result.monte_carlo.terminal_growth.upper == 0.025


def test_valuation_result_declares_fcff_enterprise_value_wacc_basis() -> None:
    module = _contract_module()
    deterministic, assumptions, monte_carlo = _sources()
    payload = module.build_valuation_result(deterministic, assumptions, monte_carlo).to_dict()

    assert payload["basis"] == {
        "cash_flow": "FCFF",
        "market_value": "enterprise_value",
        "discount_rate": "WACC",
    }
    assert "equity_fcf" not in json.dumps(payload).lower()
    assert "cost_of_equity" not in json.dumps(payload).lower()


def test_valuation_result_serializes_json_safe_finite_values() -> None:
    module = _contract_module()
    deterministic, assumptions, monte_carlo = _sources()
    payload = module.build_valuation_result(deterministic, assumptions, monte_carlo).to_dict()

    encoded = json.dumps(payload, allow_nan=False, sort_keys=True)
    assert "NaN" not in encoded and "Infinity" not in encoded
    assert payload["monte_carlo"]["distribution_semantics"] == "model_scenario_distribution"


def test_valuation_result_keeps_zero_variance_coherence_visible() -> None:
    module = _contract_module()
    deterministic, assumptions, monte_carlo = _sources()
    result = module.build_valuation_result(deterministic, assumptions, monte_carlo)

    assert result.monte_carlo.p50_enterprise_value == pytest.approx(
        result.deterministic.enterprise_value
    )
