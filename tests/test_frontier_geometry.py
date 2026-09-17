import pytest

from qhapaq_finance.frontier_geometry import (
    CapitalRegime,
    DeclaredRegime,
    FrontierGeometryEngine,
    GeometryRoute,
    ParameterSpec,
    RevenueConstraint,
    RootTopologyScanner,
    TerminalRegime,
    TradeoffStatus,
    ValuationEvaluation,
)

SMOOTH = DeclaredRegime(
    RevenueConstraint.UNCONSTRAINED,
    CapitalRegime.INVESTING,
    TerminalRegime.VALID,
)
CAPACITY_BOUND = DeclaredRegime(
    RevenueConstraint.CAPACITY_BOUND,
    CapitalRegime.INVESTING,
    TerminalRegime.VALID,
)


def _specs() -> dict[str, ParameterSpec]:
    return {
        "growth": ParameterSpec("growth", scale=0.05, lower=-0.20, upper=0.50),
        "margin": ParameterSpec("margin", scale=0.10, lower=0.01, upper=0.80),
    }


def test_smooth_tradeoff_uses_ift_prediction_and_exact_reanchoring() -> None:
    def evaluator(params: dict[str, float]) -> ValuationEvaluation:
        # V = 100 + 200*g + 400*m.  Along V=constant, dm/dg = -0.5.
        return ValuationEvaluation(100 + 200 * params["growth"] + 400 * params["margin"], SMOOTH)

    engine = FrontierGeometryEngine(evaluator, _specs())
    result = engine.solve_tradeoff(
        {"growth": 0.10, "margin": 0.30},
        shock_parameter="growth",
        shock=-0.02,
        compensating_parameter="margin",
    )

    assert result.route is GeometryRoute.IFT_ASSISTED
    assert result.status is TradeoffStatus.EXACT
    assert result.linear_compensation == pytest.approx(0.01, abs=1e-8)
    assert result.exact_compensation == pytest.approx(0.01, abs=1e-8)
    assert result.nonlinearity_gap == pytest.approx(0.0, abs=1e-8)
    assert result.residual == pytest.approx(0.0, abs=1e-10)


def test_regime_change_routes_to_topology_and_finds_exact_root() -> None:
    def evaluator(params: dict[str, float]) -> ValuationEvaluation:
        growth = params["growth"]
        margin = params["margin"]
        regime = SMOOTH if growth < 0.20 else CAPACITY_BOUND
        # Continuous value but declared economic regime changes at growth=20%.
        return ValuationEvaluation(100 + 100 * growth + 200 * margin, regime)

    engine = FrontierGeometryEngine(evaluator, _specs())
    result = engine.solve_tradeoff(
        {"growth": 0.19, "margin": 0.30},
        shock_parameter="growth",
        shock=0.02,
        compensating_parameter="margin",
    )

    assert result.route is GeometryRoute.TOPOLOGY
    assert result.status is TradeoffStatus.EXACT
    assert result.selected_root == pytest.approx(0.29, abs=1e-8)
    assert result.residual == pytest.approx(0.0, abs=1e-10)


def test_topology_scanner_detects_two_interior_roots_with_same_sign_at_domain_edges() -> None:
    scanner = RootTopologyScanner(segments=128, value_tolerance=1e-10)
    roots = scanner.roots(lambda x: (x - 0.25) * (x - 0.75), lower=0.0, upper=1.0)
    assert roots == pytest.approx((0.25, 0.75), abs=1e-8)


def test_topology_scanner_detects_tangential_root_without_sign_change() -> None:
    scanner = RootTopologyScanner(segments=128, value_tolerance=1e-9)
    roots = scanner.roots(lambda x: (x - 0.4) ** 2, lower=0.0, upper=1.0)
    assert len(roots) == 1
    assert roots[0] == pytest.approx(0.4, abs=1e-6)


def test_multiple_roots_are_exposed_instead_of_hidden() -> None:
    specs = {
        "shock": ParameterSpec("shock", scale=0.10, lower=-1.0, upper=1.0),
        "comp": ParameterSpec("comp", scale=0.10, lower=-1.0, upper=1.0),
    }

    def evaluator(params: dict[str, float]) -> ValuationEvaluation:
        # Base target is zero. A -0.25 shock requires comp in {-0.5, +0.5}.
        value = params["shock"] + params["comp"] ** 2
        return ValuationEvaluation(value, SMOOTH)

    engine = FrontierGeometryEngine(evaluator, specs)
    result = engine.solve_tradeoff(
        {"shock": 0.0, "comp": 0.0},
        shock_parameter="shock",
        shock=-0.25,
        compensating_parameter="comp",
    )

    assert result.status is TradeoffStatus.MULTIPLE_BRANCHES
    assert result.candidate_roots == pytest.approx((-0.5, 0.5), abs=1e-6)


def test_no_feasible_root_is_explicit() -> None:
    def evaluator(params: dict[str, float]) -> ValuationEvaluation:
        return ValuationEvaluation(params["growth"] + params["margin"], SMOOTH)

    engine = FrontierGeometryEngine(evaluator, _specs())
    result = engine.solve_tradeoff(
        {"growth": 0.40, "margin": 0.02},
        shock_parameter="growth",
        shock=0.05,
        compensating_parameter="margin",
    )

    assert result.status is TradeoffStatus.NO_FEASIBLE_ROOT
    assert result.selected_root is None


def test_shock_outside_domain_fails_without_running_root_solver() -> None:
    def evaluator(params: dict[str, float]) -> ValuationEvaluation:
        return ValuationEvaluation(params["growth"] + params["margin"], SMOOTH)

    engine = FrontierGeometryEngine(evaluator, _specs())
    result = engine.solve_tradeoff(
        {"growth": 0.49, "margin": 0.30},
        shock_parameter="growth",
        shock=0.02,
        compensating_parameter="margin",
    )

    assert result.status is TradeoffStatus.OUTSIDE_DOMAIN
    assert result.selected_root is None
