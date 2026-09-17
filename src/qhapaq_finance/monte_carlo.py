"""Seeded FCFF valuation sampling over the canonical deterministic DCF."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace
from typing import Any

from .sensitivity import _cost_at_wacc
from .valuation import (
    MIN_TERMINAL_SPREAD,
    ResearchCase,
    ScenarioAssumptions,
    ValuationError,
    value_scenario,
)


class MonteCarloError(ValueError):
    """Raised when a Monte Carlo configuration or sampled valuation is invalid."""


def _finite(value: Any, field: str, error: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MonteCarloError(error)
    result = float(value)
    if not math.isfinite(result):
        raise MonteCarloError(error)
    return result


@dataclass(frozen=True)
class UniformDistribution:
    """A finite, inclusive uniform distribution; equal bounds represent a constant."""

    lower: float
    upper: float

    def __post_init__(self) -> None:
        lower = _finite(self.lower, "lower", "DISTRIBUTION_INVALID")
        upper = _finite(self.upper, "upper", "DISTRIBUTION_INVALID")
        if lower > upper:
            raise MonteCarloError("DISTRIBUTION_INVALID")

    def sample(self, rng: random.Random) -> float:
        return rng.uniform(self.lower, self.upper)

    def to_dict(self) -> dict[str, float | str]:
        return {"kind": "uniform", "lower": self.lower, "upper": self.upper}


@dataclass(frozen=True)
class MonteCarloAssumptions:
    explicit_growth: UniformDistribution
    wacc: UniformDistribution
    terminal_growth: UniformDistribution
    simulations: int
    seed: int
    max_attempts_per_simulation: int = 100

    def __post_init__(self) -> None:
        if (
            not isinstance(self.simulations, int)
            or isinstance(self.simulations, bool)
            or self.simulations < 1
        ):
            raise MonteCarloError("SIMULATION_CONFIGURATION_INVALID")
        if not isinstance(self.seed, int) or isinstance(self.seed, bool):
            raise MonteCarloError("SIMULATION_CONFIGURATION_INVALID")
        if (
            not isinstance(self.max_attempts_per_simulation, int)
            or isinstance(self.max_attempts_per_simulation, bool)
            or self.max_attempts_per_simulation < 1
        ):
            raise MonteCarloError("SIMULATION_CONFIGURATION_INVALID")

    def to_dict(self) -> dict[str, object]:
        return {
            "explicit_growth": self.explicit_growth.to_dict(),
            "wacc": self.wacc.to_dict(),
            "terminal_growth": self.terminal_growth.to_dict(),
            "simulations": self.simulations,
            "seed": self.seed,
            "max_attempts_per_simulation": self.max_attempts_per_simulation,
        }


@dataclass(frozen=True)
class MonteCarloResult:
    seed: int
    requested_simulations: int
    accepted_simulations: int
    rejected_draws: int
    mean_enterprise_value: float
    median_enterprise_value: float
    standard_deviation_enterprise_value: float
    p05_enterprise_value: float
    p25_enterprise_value: float
    p50_enterprise_value: float
    p75_enterprise_value: float
    p95_enterprise_value: float

    def to_dict(self) -> dict[str, float | int]:
        return dict(self.__dict__)


def _quantile(values: list[float], probability: float) -> float:
    """Use deterministic linear interpolation over sorted sample positions."""
    position = probability * (len(values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def _summary(
    values: list[float], assumptions: MonteCarloAssumptions, rejected: int
) -> MonteCarloResult:
    ordered = sorted(values)
    mean = sum(ordered) / len(ordered)
    variance = (
        0.0
        if ordered[0] == ordered[-1]
        else sum((value - mean) ** 2 for value in ordered) / len(ordered)
    )
    standard_deviation = math.sqrt(variance)
    summary_values = (
        mean,
        standard_deviation,
        *(_quantile(ordered, p) for p in (0.05, 0.25, 0.5, 0.75, 0.95)),
    )
    if not all(math.isfinite(value) for value in summary_values):
        raise MonteCarloError("NONFINITE_VALUATION_RESULT")
    return MonteCarloResult(
        seed=assumptions.seed,
        requested_simulations=assumptions.simulations,
        accepted_simulations=len(ordered),
        rejected_draws=rejected,
        mean_enterprise_value=mean,
        median_enterprise_value=_quantile(ordered, 0.5),
        standard_deviation_enterprise_value=standard_deviation,
        p05_enterprise_value=_quantile(ordered, 0.05),
        p25_enterprise_value=_quantile(ordered, 0.25),
        p50_enterprise_value=_quantile(ordered, 0.5),
        p75_enterprise_value=_quantile(ordered, 0.75),
        p95_enterprise_value=_quantile(ordered, 0.95),
    )


def run_fcff_monte_carlo(
    case: ResearchCase,
    scenario: ScenarioAssumptions,
    assumptions: MonteCarloAssumptions,
) -> MonteCarloResult:
    """Sample FCFF assumptions and value every accepted draw via ``value_scenario``."""
    rng = random.Random(assumptions.seed)
    enterprise_values: list[float] = []
    rejected_draws = 0
    for _ in range(assumptions.simulations):
        for _ in range(assumptions.max_attempts_per_simulation):
            growth = assumptions.explicit_growth.sample(rng)
            wacc = assumptions.wacc.sample(rng)
            terminal_growth = assumptions.terminal_growth.sample(rng)
            if wacc - terminal_growth < MIN_TERMINAL_SPREAD:
                rejected_draws += 1
                continue
            try:
                sampled_case = replace(case, capital_cost=_cost_at_wacc(case, wacc))
                sampled_scenario = replace(
                    scenario,
                    explicit_growth=growth,
                    terminal_growth=terminal_growth,
                )
                enterprise_value = value_scenario(sampled_case, sampled_scenario).enterprise_value
            except ValuationError:
                rejected_draws += 1
                continue
            if not math.isfinite(enterprise_value):
                raise MonteCarloError("NONFINITE_VALUATION_RESULT")
            enterprise_values.append(enterprise_value)
            break
        else:
            raise MonteCarloError("UNABLE_TO_GENERATE_VALID_SAMPLES")
    return _summary(enterprise_values, assumptions, rejected_draws)
