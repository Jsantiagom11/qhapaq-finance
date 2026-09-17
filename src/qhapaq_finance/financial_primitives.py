"""Pure, fail-closed financial primitives shared by research consumers."""

from __future__ import annotations

import math
from typing import Any


class FinancialPrimitiveError(ValueError):
    """Raised when a financial primitive cannot produce a finite result."""


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FinancialPrimitiveError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise FinancialPrimitiveError(f"{field} must be finite")
    return result


def _tax_rate(value: Any) -> float:
    result = _number(value, "tax_rate")
    if not 0 <= result < 1:
        raise FinancialPrimitiveError("tax_rate must be between 0% and 100%")
    return result


def calculate_nopat(*, ebit: float, tax_rate: float) -> float:
    """Return operating profit after tax for finite inputs and a valid tax rate."""
    result = _number(ebit, "ebit") * (1 - _tax_rate(tax_rate))
    if not math.isfinite(result):
        raise FinancialPrimitiveError("nopat must be finite")
    return result


def calculate_fcff(
    *,
    nopat: float,
    depreciation_amortization: float,
    capex: float,
    change_in_working_capital: float,
) -> float:
    """Return FCFF when capex and working-capital increases are cash uses."""
    normalized_nopat = _number(nopat, "nopat")
    da = _number(depreciation_amortization, "depreciation_amortization")
    normalized_capex = _number(capex, "capex")
    change_in_nwc = _number(change_in_working_capital, "change_in_working_capital")
    if da < 0:
        raise FinancialPrimitiveError("depreciation_amortization must be non-negative")
    if normalized_capex < 0:
        raise FinancialPrimitiveError("capex must be a non-negative cash use")
    result = normalized_nopat + da - normalized_capex - change_in_nwc
    if not math.isfinite(result):
        raise FinancialPrimitiveError("fcff must be finite")
    return result


def calculate_roic(*, nopat: float, invested_capital: float) -> float:
    """Return return on invested capital; zero or negative capital is invalid."""
    normalized_capital = _number(invested_capital, "invested_capital")
    if normalized_capital <= 0:
        raise FinancialPrimitiveError("invested_capital must be positive")
    result = _number(nopat, "nopat") / normalized_capital
    if not math.isfinite(result):
        raise FinancialPrimitiveError("roic must be finite")
    return result


def calculate_net_working_capital(
    *, operating_current_assets: float, operating_current_liabilities: float
) -> float:
    """Return declared operating current assets less operating liabilities."""
    return _number(operating_current_assets, "operating_current_assets") - _number(
        operating_current_liabilities, "operating_current_liabilities"
    )


def calculate_change_nwc(*, opening_nwc: float, closing_nwc: float) -> float:
    """Return the cash-use convention: closing operating NWC minus opening NWC."""
    return _number(closing_nwc, "closing_nwc") - _number(opening_nwc, "opening_nwc")


def calculate_effective_tax_rate(*, tax_expense: float, pretax_income: float) -> float:
    """Derive an effective tax rate only with a positive pretax denominator."""
    expense = _number(tax_expense, "tax_expense")
    income = _number(pretax_income, "pretax_income")
    if income <= 0:
        raise FinancialPrimitiveError("pretax_income must be positive")
    return _tax_rate(expense / income)
