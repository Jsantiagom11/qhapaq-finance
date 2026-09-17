"""Typed valuation-evidence contract composed from existing valuation engines."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .monte_carlo import MonteCarloAssumptions, MonteCarloResult, UniformDistribution
from .valuation import ResearchResult, ScenarioValuation


class ValuationResultError(ValueError):
    """Raised when valuation evidence cannot be represented safely."""


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValuationResultError(f"{field} must be finite")
    result = float(value)
    if not math.isfinite(result):
        raise ValuationResultError(f"{field} must be finite")
    return result


@dataclass(frozen=True)
class ValuationBasis:
    cash_flow: str = "FCFF"
    market_value: str = "enterprise_value"
    discount_rate: str = "WACC"

    def to_dict(self) -> dict[str, str]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class DeterministicValuationEvidence:
    enterprise_value: float
    equity_value: float
    per_share_value: float
    explicit_growth: float
    terminal_growth: float
    wacc: float
    forecast_years: int

    def to_dict(self) -> dict[str, float | int]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class ReverseDcfEvidence:
    implied_growth: float
    target_enterprise_value: float

    def to_dict(self) -> dict[str, float]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class DistributionEvidence:
    distribution_type: str
    lower: float
    upper: float

    def to_dict(self) -> dict[str, float | str]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class MonteCarloValuationEvidence:
    distribution_semantics: str
    seed: int
    simulations: int
    accepted_simulations: int
    rejected_draws: int
    explicit_growth: DistributionEvidence
    wacc: DistributionEvidence
    terminal_growth: DistributionEvidence
    mean_enterprise_value: float
    standard_deviation_enterprise_value: float
    p05_enterprise_value: float
    p25_enterprise_value: float
    p50_enterprise_value: float
    p75_enterprise_value: float
    p95_enterprise_value: float

    def to_dict(self) -> dict[str, object]:
        return {
            "distribution_semantics": self.distribution_semantics,
            "seed": self.seed,
            "simulations": self.simulations,
            "accepted_simulations": self.accepted_simulations,
            "rejected_draws": self.rejected_draws,
            "explicit_growth": self.explicit_growth.to_dict(),
            "wacc": self.wacc.to_dict(),
            "terminal_growth": self.terminal_growth.to_dict(),
            "mean_enterprise_value": self.mean_enterprise_value,
            "standard_deviation_enterprise_value": self.standard_deviation_enterprise_value,
            "p05_enterprise_value": self.p05_enterprise_value,
            "p25_enterprise_value": self.p25_enterprise_value,
            "p50_enterprise_value": self.p50_enterprise_value,
            "p75_enterprise_value": self.p75_enterprise_value,
            "p95_enterprise_value": self.p95_enterprise_value,
        }


@dataclass(frozen=True)
class ValuationResult:
    """Evidence handoff for future policy consumers; it contains no recommendation."""

    basis: ValuationBasis
    deterministic: DeterministicValuationEvidence
    reverse_dcf: ReverseDcfEvidence
    monte_carlo: MonteCarloValuationEvidence

    def to_dict(self) -> dict[str, object]:
        return {
            "basis": self.basis.to_dict(),
            "deterministic": self.deterministic.to_dict(),
            "reverse_dcf": self.reverse_dcf.to_dict(),
            "monte_carlo": self.monte_carlo.to_dict(),
        }


def _distribution(distribution: UniformDistribution) -> DistributionEvidence:
    return DistributionEvidence(
        "uniform",
        _finite(distribution.lower, "lower"),
        _finite(distribution.upper, "upper"),
    )


def _base_scenario(result: ResearchResult) -> tuple[ScenarioValuation, float, int]:
    scenario = next((item for item in result.scenarios if item.name == "base"), None)
    assumptions = next((item for item in result.case.scenarios if item.name == "base"), None)
    if scenario is None or assumptions is None:
        raise ValuationResultError("BASE_SCENARIO_REQUIRED")
    return scenario, _finite(assumptions.explicit_growth, "explicit_growth"), assumptions.years


def build_valuation_result(
    deterministic_result: ResearchResult,
    monte_carlo_assumptions: MonteCarloAssumptions,
    monte_carlo_result: MonteCarloResult,
) -> ValuationResult:
    """Compose precomputed FCFF valuation evidence without rerunning any engine."""
    base, explicit_growth, years = _base_scenario(deterministic_result)
    if monte_carlo_result.accepted_simulations != monte_carlo_result.requested_simulations:
        raise ValuationResultError("MONTE_CARLO_SAMPLE_INCOMPLETE")
    deterministic = DeterministicValuationEvidence(
        _finite(base.enterprise_value, "enterprise_value"),
        _finite(base.equity_value, "equity_value"),
        _finite(base.intrinsic_value_per_share, "per_share_value"),
        explicit_growth,
        _finite(base.terminal_growth, "terminal_growth"),
        _finite(deterministic_result.case.capital_cost.wacc, "wacc"),
        years,
    )
    reverse = ReverseDcfEvidence(
        _finite(deterministic_result.reverse_implied_growth, "implied_growth"),
        _finite(
            deterministic_result.case.market_snapshot.enterprise_value,
            "target_enterprise_value",
        ),
    )
    monte_carlo = MonteCarloValuationEvidence(
        "model_scenario_distribution",
        monte_carlo_result.seed,
        monte_carlo_result.requested_simulations,
        monte_carlo_result.accepted_simulations,
        monte_carlo_result.rejected_draws,
        _distribution(monte_carlo_assumptions.explicit_growth),
        _distribution(monte_carlo_assumptions.wacc),
        _distribution(monte_carlo_assumptions.terminal_growth),
        _finite(monte_carlo_result.mean_enterprise_value, "monte_carlo_mean"),
        _finite(monte_carlo_result.standard_deviation_enterprise_value, "monte_carlo_stddev"),
        _finite(monte_carlo_result.p05_enterprise_value, "monte_carlo_p05"),
        _finite(monte_carlo_result.p25_enterprise_value, "monte_carlo_p25"),
        _finite(monte_carlo_result.p50_enterprise_value, "monte_carlo_p50"),
        _finite(monte_carlo_result.p75_enterprise_value, "monte_carlo_p75"),
        _finite(monte_carlo_result.p95_enterprise_value, "monte_carlo_p95"),
    )
    return ValuationResult(ValuationBasis(), deterministic, reverse, monte_carlo)
