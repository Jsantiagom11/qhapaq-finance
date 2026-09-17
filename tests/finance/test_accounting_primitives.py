from __future__ import annotations

from datetime import date

import pytest

from qhapaq_finance.accounting import (
    AccountingError,
    AccountingSnapshot,
    InvestedCapitalPair,
)


def test_invested_capital_pair_accepts_two_complete_endpoints() -> None:
    pair = InvestedCapitalPair(opening=100.0, closing=120.0)

    assert pair.opening.top_down.value == 100.0
    assert pair.closing.top_down.value == 120.0
    assert pair.average == pytest.approx(110.0)


def test_invested_capital_pair_allows_both_endpoints_to_be_absent() -> None:
    assert InvestedCapitalPair.from_optional(None, None) is None


@pytest.mark.parametrize(
    ("opening", "closing"),
    ((100.0, None), (None, 120.0)),
)
def test_invested_capital_pair_rejects_a_partial_pair(
    opening: float | None,
    closing: float | None,
) -> None:
    with pytest.raises(AccountingError, match="PARTIAL_INVESTED_CAPITAL_PAIR"):
        InvestedCapitalPair.from_optional(opening, closing)


def test_accounting_snapshot_keeps_fcff_when_invested_capital_is_unavailable() -> None:
    snapshot = AccountingSnapshot(
        period_label="TTM",
        period_end=date(2026, 6, 27),
        unit="USD million",
        revenue=1_000.0,
        ebit=200.0,
        tax_rate=0.25,
        income_tax_expense=50.0,
        pretax_income=200.0,
        depreciation_amortization=40.0,
        capex=60.0,
        change_in_working_capital=20.0,
        invested_capital=None,
        cash=100.0,
        marketable_securities=30.0,
        debt=80.0,
        valuation_shares=10.0,
        valuation_share_basis="common_shares_outstanding",
        source_lineage=("revenue", "ebit", "da", "capex", "nwc", "cash", "debt"),
    )

    assert snapshot.invested_capital is None
    assert snapshot.nopat == pytest.approx(150.0)
    assert snapshot.fcff == pytest.approx(110.0)
    assert snapshot.cash == 100.0
    assert snapshot.marketable_securities == 30.0
    assert snapshot.debt == 80.0
