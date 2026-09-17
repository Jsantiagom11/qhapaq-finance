from datetime import date

import pytest

from qhapaq_finance.financial_temporal import FinancialTemporalError, TTMWindow


def test_ttm_window_derives_opening_balance_date_from_period_start() -> None:
    """A one-day opening offset prevents using a flow-start balance as opening capital."""
    window = TTMWindow(period_start=date(2025, 6, 29), period_end=date(2026, 6, 27))

    assert window.opening_balance_date == date(2025, 6, 28)


def test_ttm_window_exposes_period_end_as_closing_balance_date() -> None:
    window = TTMWindow(period_start=date(2025, 6, 29), period_end=date(2026, 6, 27))

    assert window.closing_balance_date == date(2026, 6, 27)


@pytest.mark.parametrize(
    ("period_start", "period_end"),
    (
        (date(2026, 6, 27), date(2026, 6, 27)),
        (date(2026, 6, 28), date(2026, 6, 27)),
    ),
)
def test_ttm_window_rejects_empty_or_reversed_period(period_start: date, period_end: date) -> None:
    with pytest.raises(FinancialTemporalError, match="TTM_WINDOW_INVALID"):
        TTMWindow(period_start=period_start, period_end=period_end)
