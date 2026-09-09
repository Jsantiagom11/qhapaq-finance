"""Deterministic valuation sensitivity using the canonical valuation engine."""

from __future__ import annotations

from dataclasses import replace

from .valuation import CapitalCost, ResearchCase, ScenarioAssumptions, value_scenario


def _grid(base: float) -> tuple[float, ...]:
    return tuple(base + delta for delta in (-0.01, -0.005, 0.0, 0.005, 0.01))


def _cost_at_wacc(case: ResearchCase, target_wacc: float) -> CapitalCost:
    """Shift risk-free and debt cost coherently to attain a requested WACC."""
    cost = case.capital_cost
    multiplier = cost.equity_weight + cost.debt_weight * (1 - cost.tax_rate)
    shift = (target_wacc - cost.wacc) / multiplier
    return CapitalCost.from_assumptions(
        risk_free_rate=cost.risk_free_rate + shift,
        equity_risk_premium=cost.equity_risk_premium,
        beta=cost.beta,
        pre_tax_cost_of_debt=cost.pre_tax_cost_of_debt + shift,
        tax_rate=cost.tax_rate,
        market_equity=cost.market_equity,
        debt=cost.debt,
    )


def _cell(case: ResearchCase, scenario: ScenarioAssumptions, wacc: float) -> float | None:
    if scenario.terminal_growth >= wacc:
        return None
    adjusted = replace(case, capital_cost=_cost_at_wacc(case, wacc))
    return value_scenario(adjusted, scenario).intrinsic_value_per_share


def sensitivity_matrices(case: ResearchCase) -> dict[str, object]:
    """Return typed numeric grids; invalid terminal cells are explicit ``None``."""
    base = next(item for item in case.scenarios if item.name == "base")
    wacc_axis = _grid(case.capital_cost.wacc)
    terminal_axis = _grid(base.terminal_growth)
    growth_axis = _grid(base.explicit_growth)
    terminal_cells = [
        [_cell(case, replace(base, terminal_growth=terminal), wacc) for terminal in terminal_axis]
        for wacc in wacc_axis
    ]
    growth_cells = [
        [_cell(case, replace(base, explicit_growth=growth), wacc) for growth in growth_axis]
        for wacc in wacc_axis
    ]
    return {
        "wacc_terminal_growth": {
            "row_axis": wacc_axis,
            "column_axis": terminal_axis,
            "cells": terminal_cells,
        },
        "wacc_explicit_growth": {
            "row_axis": wacc_axis,
            "column_axis": growth_axis,
            "cells": growth_cells,
        },
    }
