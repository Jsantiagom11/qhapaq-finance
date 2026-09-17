"""Regime-aware geometry for Qhapaq expectation-frontier trade-offs.

This module is deliberately independent from presentation and market-data code.
It routes smooth local problems through finite-difference IFT prediction while
falling back to bounded topology scanning whenever the declared economic regime
changes or derivatives are numerically unstable.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum, auto


class GeometryError(ValueError):
    """Raised when frontier geometry inputs violate the numeric contract."""


class RevenueConstraint(Enum):
    UNCONSTRAINED = auto()
    CAPACITY_BOUND = auto()


class CapitalRegime(Enum):
    INVESTING = auto()
    ZERO_GROWTH_CAPEX = auto()
    OVERCAPACITY = auto()


class TerminalRegime(Enum):
    VALID = auto()
    INVALID = auto()


@dataclass(frozen=True)
class DeclaredRegime:
    revenue: RevenueConstraint
    capital: CapitalRegime
    terminal: TerminalRegime


@dataclass(frozen=True)
class ValuationEvaluation:
    value: float
    regime: DeclaredRegime

    def __post_init__(self) -> None:
        if not math.isfinite(self.value):
            raise GeometryError("valuation value must be finite")


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    scale: float
    lower: float
    upper: float

    def __post_init__(self) -> None:
        if not self.name:
            raise GeometryError("parameter name must be present")
        for field_name, value in (
            ("scale", self.scale),
            ("lower", self.lower),
            ("upper", self.upper),
        ):
            if not math.isfinite(value):
                raise GeometryError(f"{field_name} must be finite")
        if self.scale <= 0:
            raise GeometryError("parameter scale must be positive")
        if self.lower >= self.upper:
            raise GeometryError("parameter lower bound must be below upper bound")

    def validate(self, value: float) -> None:
        if not math.isfinite(value):
            raise GeometryError(f"{self.name} must be finite")
        if not self.lower <= value <= self.upper:
            raise GeometryError(f"{self.name}={value} is outside [{self.lower}, {self.upper}]")


class DerivativeStatus(Enum):
    STABLE = auto()
    UNSTABLE = auto()
    NON_SMOOTH_BOUNDARY = auto()
    UNDEFINED = auto()


@dataclass(frozen=True)
class DerivativeResult:
    parameter: str
    value: float | None
    estimated_error: float
    regime_base: DeclaredRegime
    status: DerivativeStatus
    step_used: float


class GeometryRoute(Enum):
    IFT_ASSISTED = auto()
    TOPOLOGY = auto()


class TradeoffStatus(Enum):
    EXACT = auto()
    MULTIPLE_BRANCHES = auto()
    NO_FEASIBLE_ROOT = auto()
    OUTSIDE_DOMAIN = auto()


@dataclass(frozen=True)
class TradeoffResult:
    shock_parameter: str
    shock: float
    compensating_parameter: str
    route: GeometryRoute
    status: TradeoffStatus
    base_value: float
    shocked_value: float
    linear_compensation: float | None
    predictor: float | None
    candidate_roots: tuple[float, ...]
    selected_root: float | None
    exact_compensation: float | None
    nonlinearity_gap: float | None
    reanchored_value: float | None
    residual: float | None


ModelEvaluator = Callable[[Mapping[str, float]], ValuationEvaluation]


class FiniteDifferenceOracle:
    """Adaptive finite-difference derivatives guarded by declared regimes."""

    def __init__(
        self,
        evaluator: ModelEvaluator,
        specs: Mapping[str, ParameterSpec],
        *,
        rel_eps: float = 1e-4,
        max_relative_error: float = 0.05,
    ) -> None:
        if rel_eps <= 0 or not math.isfinite(rel_eps):
            raise GeometryError("rel_eps must be positive and finite")
        if max_relative_error <= 0 or not math.isfinite(max_relative_error):
            raise GeometryError("max_relative_error must be positive and finite")
        self._evaluate = evaluator
        self._specs = dict(specs)
        self._rel_eps = rel_eps
        self._max_relative_error = max_relative_error

    def _evaluation(self, params: Mapping[str, float]) -> ValuationEvaluation:
        result = self._evaluate(params)
        if result.regime.terminal is TerminalRegime.INVALID:
            raise GeometryError("cannot differentiate a terminal-invalid scenario")
        return result

    def _central_difference(
        self,
        params: Mapping[str, float],
        parameter: str,
        step: float,
        base_regime: DeclaredRegime,
    ) -> tuple[float | None, DerivativeStatus]:
        spec = self._specs[parameter]
        value = params[parameter]
        lower_value = value - step
        upper_value = value + step
        if lower_value < spec.lower or upper_value > spec.upper:
            return None, DerivativeStatus.UNDEFINED

        up = dict(params)
        down = dict(params)
        up[parameter] = upper_value
        down[parameter] = lower_value
        up_result = self._evaluation(up)
        down_result = self._evaluation(down)
        if up_result.regime != base_regime or down_result.regime != base_regime:
            return None, DerivativeStatus.NON_SMOOTH_BOUNDARY
        return (up_result.value - down_result.value) / (2.0 * step), DerivativeStatus.STABLE

    def derivative(self, params: Mapping[str, float], parameter: str) -> DerivativeResult:
        if parameter not in self._specs:
            raise GeometryError(f"missing ParameterSpec for {parameter}")
        if parameter not in params:
            raise GeometryError(f"missing parameter {parameter}")
        spec = self._specs[parameter]
        spec.validate(params[parameter])
        base = self._evaluation(params)
        step = self._rel_eps * max(abs(params[parameter]), spec.scale)

        d_h, status_h = self._central_difference(params, parameter, step, base.regime)
        if status_h is not DerivativeStatus.STABLE or d_h is None:
            return DerivativeResult(parameter, None, math.inf, base.regime, status_h, step)

        half_step = step / 2.0
        d_h2, status_h2 = self._central_difference(params, parameter, half_step, base.regime)
        if status_h2 is not DerivativeStatus.STABLE or d_h2 is None:
            return DerivativeResult(parameter, None, math.inf, base.regime, status_h2, half_step)

        richardson = (4.0 * d_h2 - d_h) / 3.0
        error = abs(richardson - d_h2)
        relative_error = error / max(abs(richardson), 1e-15)
        status = (
            DerivativeStatus.STABLE
            if relative_error <= self._max_relative_error
            else DerivativeStatus.UNSTABLE
        )
        return DerivativeResult(
            parameter=parameter,
            value=richardson,
            estimated_error=relative_error,
            regime_base=base.regime,
            status=status,
            step_used=half_step,
        )


@dataclass(frozen=True)
class _RootPoint:
    x: float
    residual: float


class RootTopologyScanner:
    """Bounded one-dimensional root discovery without a SciPy dependency.

    It discovers sign-changing roots and near-tangential roots.  The scanner is
    intentionally conservative: absence of a discovered root means only that no
    root was found at the configured resolution/tolerance.
    """

    def __init__(
        self,
        *,
        segments: int = 128,
        value_tolerance: float = 1e-9,
        x_tolerance: float = 1e-10,
        max_iterations: int = 256,
    ) -> None:
        if segments < 8:
            raise GeometryError("root scanner requires at least 8 segments")
        self._segments = segments
        self._value_tolerance = value_tolerance
        self._x_tolerance = x_tolerance
        self._max_iterations = max_iterations

    def _bisect(self, f: Callable[[float], float], a: float, b: float) -> float:
        fa, fb = f(a), f(b)
        if abs(fa) <= self._value_tolerance:
            return a
        if abs(fb) <= self._value_tolerance:
            return b
        if fa * fb > 0:
            raise GeometryError("bisection requires a sign-changing bracket")
        for _ in range(self._max_iterations):
            mid = (a + b) / 2.0
            fm = f(mid)
            if abs(fm) <= self._value_tolerance or abs(b - a) <= self._x_tolerance:
                return mid
            if fa * fm <= 0:
                b, fb = mid, fm
            else:
                a, fa = mid, fm
        raise GeometryError("root bisection did not converge")

    def _minimize_abs(self, f: Callable[[float], float], a: float, b: float) -> _RootPoint:
        # Golden-section minimization over |f| for tangential-root candidates.
        phi = (1.0 + math.sqrt(5.0)) / 2.0
        c = b - (b - a) / phi
        d = a + (b - a) / phi
        fc, fd = abs(f(c)), abs(f(d))
        for _ in range(self._max_iterations):
            if abs(b - a) <= self._x_tolerance:
                break
            if fc < fd:
                b, d, fd = d, c, fc
                c = b - (b - a) / phi
                fc = abs(f(c))
            else:
                a, c, fc = c, d, fd
                d = a + (b - a) / phi
                fd = abs(f(d))
        x = (a + b) / 2.0
        return _RootPoint(x=x, residual=abs(f(x)))

    @staticmethod
    def _deduplicate(values: list[float], tolerance: float) -> tuple[float, ...]:
        if not values:
            return ()
        result = [sorted(values)[0]]
        for value in sorted(values)[1:]:
            if abs(value - result[-1]) > tolerance:
                result.append(value)
        return tuple(result)

    def roots(
        self,
        f: Callable[[float], float],
        *,
        lower: float,
        upper: float,
    ) -> tuple[float, ...]:
        if lower >= upper:
            raise GeometryError("root domain lower bound must be below upper bound")
        step = (upper - lower) / self._segments
        xs = [lower + step * i for i in range(self._segments + 1)]
        ys = [f(x) for x in xs]
        if any(not math.isfinite(y) for y in ys):
            raise GeometryError("root objective must be finite across scan domain")

        roots: list[float] = []
        for i in range(self._segments):
            x0, x1 = xs[i], xs[i + 1]
            y0, y1 = ys[i], ys[i + 1]
            if abs(y0) <= self._value_tolerance:
                roots.append(x0)
            if y0 * y1 < 0:
                roots.append(self._bisect(f, x0, x1))
        if abs(ys[-1]) <= self._value_tolerance:
            roots.append(xs[-1])

        # Detect roots that touch zero without changing sign.
        for i in range(1, self._segments):
            if abs(ys[i]) < abs(ys[i - 1]) and abs(ys[i]) < abs(ys[i + 1]):
                candidate = self._minimize_abs(f, xs[i - 1], xs[i + 1])
                if candidate.residual <= self._value_tolerance:
                    roots.append(candidate.x)

        return self._deduplicate(roots, max(self._x_tolerance * 10, step * 1e-6))


class FrontierGeometryEngine:
    """Route expectation trade-offs through IFT or topology by declared regime."""

    def __init__(
        self,
        evaluator: ModelEvaluator,
        specs: Mapping[str, ParameterSpec],
        *,
        derivative_oracle: FiniteDifferenceOracle | None = None,
        topology_scanner: RootTopologyScanner | None = None,
        residual_tolerance: float = 1e-8,
    ) -> None:
        if residual_tolerance <= 0 or not math.isfinite(residual_tolerance):
            raise GeometryError("residual_tolerance must be positive and finite")
        self._evaluate = evaluator
        self._specs = dict(specs)
        self._oracle = derivative_oracle or FiniteDifferenceOracle(evaluator, specs)
        self._scanner = topology_scanner or RootTopologyScanner(value_tolerance=residual_tolerance)
        self._residual_tolerance = residual_tolerance

    def _validate_params(self, params: Mapping[str, float]) -> None:
        for name, spec in self._specs.items():
            if name not in params:
                raise GeometryError(f"missing parameter {name}")
            spec.validate(params[name])

    def _objective(
        self,
        shocked: Mapping[str, float],
        compensating_parameter: str,
        target_value: float,
    ) -> Callable[[float], float]:
        def objective(value: float) -> float:
            candidate = dict(shocked)
            candidate[compensating_parameter] = value
            return self._evaluate(candidate).value - target_value

        return objective

    def solve_tradeoff(
        self,
        params: Mapping[str, float],
        *,
        shock_parameter: str,
        shock: float,
        compensating_parameter: str,
        target_value: float | None = None,
    ) -> TradeoffResult:
        self._validate_params(params)
        if shock_parameter == compensating_parameter:
            raise GeometryError("shock and compensating parameters must differ")
        if shock_parameter not in self._specs or compensating_parameter not in self._specs:
            raise GeometryError("trade-off parameters require ParameterSpec entries")
        if not math.isfinite(shock):
            raise GeometryError("shock must be finite")

        base = self._evaluate(params)
        if base.regime.terminal is TerminalRegime.INVALID:
            raise GeometryError("cannot analyze terminal-invalid base scenario")
        target = base.value if target_value is None else target_value
        if not math.isfinite(target):
            raise GeometryError("target value must be finite")

        shock_spec = self._specs[shock_parameter]
        shocked_value = params[shock_parameter] + shock
        if not shock_spec.lower <= shocked_value <= shock_spec.upper:
            return TradeoffResult(
                shock_parameter,
                shock,
                compensating_parameter,
                GeometryRoute.TOPOLOGY,
                TradeoffStatus.OUTSIDE_DOMAIN,
                base.value,
                math.nan,
                None,
                None,
                (),
                None,
                None,
                None,
                None,
                None,
            )

        shocked = dict(params)
        shocked[shock_parameter] = shocked_value
        shocked_eval = self._evaluate(shocked)

        shock_derivative = self._oracle.derivative(params, shock_parameter)
        comp_derivative = self._oracle.derivative(params, compensating_parameter)
        derivatives_stable = (
            shock_derivative.status is DerivativeStatus.STABLE
            and comp_derivative.status is DerivativeStatus.STABLE
            and shock_derivative.value is not None
            and comp_derivative.value is not None
            and abs(comp_derivative.value) > 1e-15
        )

        linear_compensation: float | None = None
        predictor: float | None = None
        route = GeometryRoute.TOPOLOGY
        if derivatives_stable:
            assert shock_derivative.value is not None
            assert comp_derivative.value is not None
            linear_compensation = -(shock_derivative.value / comp_derivative.value) * shock
            predictor = params[compensating_parameter] + linear_compensation
            comp_spec = self._specs[compensating_parameter]
            if comp_spec.lower <= predictor <= comp_spec.upper:
                predicted = dict(shocked)
                predicted[compensating_parameter] = predictor
                predictor_eval = self._evaluate(predicted)
                if shocked_eval.regime == base.regime and predictor_eval.regime == base.regime:
                    route = GeometryRoute.IFT_ASSISTED

        objective = self._objective(shocked, compensating_parameter, target)
        comp_spec = self._specs[compensating_parameter]
        roots = self._scanner.roots(
            objective,
            lower=comp_spec.lower,
            upper=comp_spec.upper,
        )
        if not roots:
            return TradeoffResult(
                shock_parameter,
                shock,
                compensating_parameter,
                route,
                TradeoffStatus.NO_FEASIBLE_ROOT,
                base.value,
                shocked_eval.value,
                linear_compensation,
                predictor,
                (),
                None,
                None,
                None,
                None,
                None,
            )

        if route is GeometryRoute.IFT_ASSISTED and predictor is not None:
            anchor = predictor
        else:
            anchor = params[compensating_parameter]
        selected = min(roots, key=lambda root: abs(root - anchor))
        reanchored = dict(shocked)
        reanchored[compensating_parameter] = selected
        reanchored_eval = self._evaluate(reanchored)
        exact_compensation = selected - params[compensating_parameter]
        nonlinearity_gap = (
            exact_compensation - linear_compensation if linear_compensation is not None else None
        )
        residual = abs(reanchored_eval.value - target) / max(abs(target), 1e-15)
        status = TradeoffStatus.MULTIPLE_BRANCHES if len(roots) > 1 else TradeoffStatus.EXACT
        if residual > self._residual_tolerance:
            raise GeometryError("selected root does not satisfy residual tolerance")

        return TradeoffResult(
            shock_parameter=shock_parameter,
            shock=shock,
            compensating_parameter=compensating_parameter,
            route=route,
            status=status,
            base_value=base.value,
            shocked_value=shocked_eval.value,
            linear_compensation=linear_compensation,
            predictor=predictor,
            candidate_roots=roots,
            selected_root=selected,
            exact_compensation=exact_compensation,
            nonlinearity_gap=nonlinearity_gap,
            reanchored_value=reanchored_eval.value,
            residual=residual,
        )
