"""Pure, threshold-governed interpretation of deterministic research artifacts."""
# ruff: noqa: E501

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class SignalCode(StrEnum):
    ABOVE_FAIR_VALUE = "ABOVE_FAIR_VALUE"
    BELOW_FAIR_VALUE = "BELOW_FAIR_VALUE"
    AT_FAIR_VALUE = "AT_FAIR_VALUE"
    MARKET_EXPECTATIONS_ABOVE_BASE = "MARKET_EXPECTATIONS_ABOVE_BASE"
    MARKET_EXPECTATIONS_BELOW_BASE = "MARKET_EXPECTATIONS_BELOW_BASE"
    HIGH_TERMINAL_DEPENDENCE = "HIGH_TERMINAL_DEPENDENCE"
    STRONG_VALUE_CREATION = "STRONG_VALUE_CREATION"
    WEAK_VALUE_CREATION = "WEAK_VALUE_CREATION"
    SENSITIVITY_FRAGILE = "SENSITIVITY_FRAGILE"


@dataclass(frozen=True)
class InterpretationThresholds:
    """Centralized policy thresholds; ratio values use decimal representation."""

    high_terminal_value_share: float = 0.70
    strong_roic_wacc_spread: float = 0.05
    weak_roic_wacc_spread: float = 0.00
    fragile_sensitivity_downside: float = 0.20


@dataclass(frozen=True)
class DeterministicInterpretation:
    valuation_status: SignalCode
    price_fair_value_distance: float
    margin_of_safety: float
    market_expectations_status: SignalCode
    market_implied_growth_gap_pp: float
    terminal_value_dependence: SignalCode | None
    terminal_value_share: float
    value_creation_status: SignalCode
    roic_wacc_spread: float
    sensitivity_status: SignalCode | None
    sensitivity_downside: float
    thresholds: InterpretationThresholds

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def interpret_artifact(
    artifact: dict[str, Any], thresholds: InterpretationThresholds | None = None
) -> DeterministicInterpretation:
    """Interpret precomputed artifact values without recalculating valuation outputs."""
    thresholds = thresholds or InterpretationThresholds()
    market = artifact["market"]
    base = artifact["valuation"]["scenarios"]["base"]
    economics = artifact["economics"]
    expectations = artifact["valuation"]["expectations"]
    price, fair_value = float(market["price"]), float(base["intrinsic_value"])
    distance = price / fair_value - 1.0
    margin = float(base["margin_of_safety"])
    gap = float(expectations["growth_difference_pp"])
    terminal_share = float(base["terminal_value_share"])
    spread = float(economics["roic_minus_wacc"])
    matrix = artifact["sensitivity"]["wacc_terminal_growth"]["cells"]
    center = float(matrix[len(matrix) // 2][len(matrix[0]) // 2])
    worst = min(float(cell) for row in matrix for cell in row)
    downside = worst / center - 1.0
    return DeterministicInterpretation(
        valuation_status=(
            SignalCode.ABOVE_FAIR_VALUE
            if distance > 0
            else SignalCode.BELOW_FAIR_VALUE
            if distance < 0
            else SignalCode.AT_FAIR_VALUE
        ),
        price_fair_value_distance=distance,
        margin_of_safety=margin,
        market_expectations_status=(
            SignalCode.MARKET_EXPECTATIONS_ABOVE_BASE
            if gap > 0
            else SignalCode.MARKET_EXPECTATIONS_BELOW_BASE
        ),
        market_implied_growth_gap_pp=gap,
        terminal_value_dependence=(
            SignalCode.HIGH_TERMINAL_DEPENDENCE
            if terminal_share >= thresholds.high_terminal_value_share
            else None
        ),
        terminal_value_share=terminal_share,
        value_creation_status=(
            SignalCode.STRONG_VALUE_CREATION
            if spread >= thresholds.strong_roic_wacc_spread
            else SignalCode.WEAK_VALUE_CREATION
            if spread <= thresholds.weak_roic_wacc_spread
            else SignalCode.STRONG_VALUE_CREATION
        ),
        roic_wacc_spread=spread,
        sensitivity_status=(
            SignalCode.SENSITIVITY_FRAGILE
            if downside <= -thresholds.fragile_sensitivity_downside
            else None
        ),
        sensitivity_downside=downside,
        thresholds=thresholds,
    )
