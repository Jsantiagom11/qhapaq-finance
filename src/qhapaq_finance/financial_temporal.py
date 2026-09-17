"""Financial period invariants shared by accounting and promotion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


class FinancialTemporalError(ValueError):
    """Raised when a financial period violates kernel invariants."""


@dataclass(frozen=True, slots=True)
class TTMWindow:
    period_start: date
    period_end: date

    def __post_init__(self) -> None:
        if self.period_start >= self.period_end:
            raise FinancialTemporalError("TTM_WINDOW_INVALID")

    @property
    def opening_balance_date(self) -> date:
        return self.period_start - timedelta(days=1)

    @property
    def closing_balance_date(self) -> date:
        return self.period_end
