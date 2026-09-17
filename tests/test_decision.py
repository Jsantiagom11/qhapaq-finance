from __future__ import annotations

import importlib
import importlib.util
import json
from dataclasses import replace
from pathlib import Path

from qhapaq_finance.monte_carlo import (
    MonteCarloAssumptions,
    UniformDistribution,
    run_fcff_monte_carlo,
)
from qhapaq_finance.research_result import build_canonical_research_result
from qhapaq_finance.valuation import analyze_case, load_fixture_case
from qhapaq_finance.valuation_result import ValuationBasis, build_valuation_result

ROOT = Path(__file__).parents[1]


def _decision_module():
    spec = importlib.util.find_spec("qhapaq_finance.decision")
    assert spec is not None, "decision engine must exist"
    return importlib.import_module("qhapaq_finance.decision")


def _sources():
    case = load_fixture_case("QCOM", ROOT)
    deterministic = analyze_case(case)
    base = next(item for item in case.scenarios if item.name == "base")
    assumptions = MonteCarloAssumptions(
        explicit_growth=UniformDistribution(base.explicit_growth, base.explicit_growth),
        wacc=UniformDistribution(case.capital_cost.wacc, case.capital_cost.wacc),
        terminal_growth=UniformDistribution(base.terminal_growth, base.terminal_growth),
        simulations=10,
        seed=17,
    )
    return (
        build_valuation_result(
            deterministic,
            assumptions,
            run_fcff_monte_carlo(case, base, assumptions),
        ),
        build_canonical_research_result("QCOM", ROOT),
    )


def _research_with(
    research,
    *,
    margin_of_safety: float | None = 0.30,
    roic_minus_wacc: float | None = 0.06,
    expectation_growth_gap: float | None = -0.01,
    ready: bool = True,
):
    base = dict(research.valuation["scenarios"]["base"])
    base["margin_of_safety"] = margin_of_safety
    valuation = dict(research.valuation)
    valuation["scenarios"] = {**research.valuation["scenarios"], "base": base}
    valuation["roic_minus_wacc"] = roic_minus_wacc
    reverse = dict(research.reverse_valuation)
    reverse["expectation_growth_gap"] = expectation_growth_gap
    readiness = dict(research.readiness)
    readiness["deterministic_research_ready"] = ready
    readiness["valuation_ready"] = ready
    return replace(research, valuation=valuation, reverse_valuation=reverse, readiness=readiness)


def test_hard_gate_failure_rejects_even_when_soft_evidence_is_excellent() -> None:
    module = _decision_module()
    valuation, research = _sources()

    result = module.evaluate_decision(
        module.DecisionInput(valuation, _research_with(research, ready=False))
    )

    assert result.status is module.DecisionStatus.REJECT
    assert result.total_score is None
    assert any(not gate.passed and gate.name == "canonical_evidence" for gate in result.hard_gates)


def test_low_score_after_passing_gates_is_watch_not_reject() -> None:
    module = _decision_module()
    valuation, research = _sources()

    result = module.evaluate_decision(
        module.DecisionInput(
            valuation,
            _research_with(
                research,
                margin_of_safety=-0.10,
                roic_minus_wacc=-0.01,
                expectation_growth_gap=0.10,
            ),
        )
    )

    assert result.status is module.DecisionStatus.WATCH
    assert result.total_score == 0.0
    assert all(gate.passed for gate in result.hard_gates)


def test_high_score_after_passing_gates_is_eligible() -> None:
    module = _decision_module()
    valuation, research = _sources()

    result = module.evaluate_decision(module.DecisionInput(valuation, _research_with(research)))

    assert result.status is module.DecisionStatus.ELIGIBLE
    assert result.total_score == 1.0


def test_basis_mismatch_is_a_hard_reject() -> None:
    module = _decision_module()
    valuation, research = _sources()
    wrong_basis = replace(
        valuation,
        basis=ValuationBasis("equity_fcf", "equity_value", "cost_of_equity"),
    )

    result = module.evaluate_decision(module.DecisionInput(wrong_basis, _research_with(research)))

    assert result.status is module.DecisionStatus.REJECT
    assert any(not gate.passed and gate.name == "valuation_basis" for gate in result.hard_gates)


def test_invalid_monte_carlo_semantics_is_a_hard_reject() -> None:
    module = _decision_module()
    valuation, research = _sources()
    invalid_semantics = replace(
        valuation,
        monte_carlo=replace(valuation.monte_carlo, distribution_semantics="empirical_probability"),
    )

    result = module.evaluate_decision(
        module.DecisionInput(invalid_semantics, _research_with(research))
    )

    assert result.status is module.DecisionStatus.REJECT
    assert any(not gate.passed and gate.name == "model_semantics" for gate in result.hard_gates)


def test_missing_hard_evidence_rejects() -> None:
    module = _decision_module()
    valuation, research = _sources()

    result = module.evaluate_decision(
        module.DecisionInput(valuation, _research_with(research, ready=False))
    )

    assert result.status is module.DecisionStatus.REJECT
    assert "deterministic_research_ready" in result.missing_evidence


def test_unready_canonical_valuation_is_hard_evidence_failure() -> None:
    module = _decision_module()
    valuation, research = _sources()
    readiness = dict(research.readiness)
    readiness["valuation_ready"] = False

    result = module.evaluate_decision(
        module.DecisionInput(valuation, replace(research, readiness=readiness))
    )

    assert result.status is module.DecisionStatus.REJECT
    assert "valuation_ready" in result.missing_evidence


def test_missing_soft_evidence_is_watch_without_silent_zero() -> None:
    module = _decision_module()
    valuation, research = _sources()

    result = module.evaluate_decision(
        module.DecisionInput(valuation, _research_with(research, margin_of_safety=None))
    )

    assert result.status is module.DecisionStatus.WATCH
    assert result.total_score is None
    assert "margin_of_safety" in result.missing_evidence
    assert "margin_of_safety" not in {item.name for item in result.dimension_scores}


def test_decision_consumes_supplied_evidence_without_recalculating_finance(monkeypatch) -> None:
    module = _decision_module()
    valuation, research = _sources()

    monkeypatch.setattr(
        "qhapaq_finance.valuation.value_scenario",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("DCF recalculated")),
    )
    monkeypatch.setattr(
        "qhapaq_finance.financial_primitives.calculate_roic",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("ROIC recalculated")),
    )

    result = module.evaluate_decision(module.DecisionInput(valuation, _research_with(research)))

    assert result.status is module.DecisionStatus.ELIGIBLE


def test_decision_is_deterministic_and_json_safe() -> None:
    module = _decision_module()
    valuation, research = _sources()
    decision_input = module.DecisionInput(valuation, _research_with(research))

    first = module.evaluate_decision(decision_input)
    second = module.evaluate_decision(decision_input)
    payload = first.to_dict()

    assert first == second
    assert json.dumps(payload, allow_nan=False, sort_keys=True)
    assert payload["policy"] == {"name": "qhapaq_core", "version": "0.1"}
