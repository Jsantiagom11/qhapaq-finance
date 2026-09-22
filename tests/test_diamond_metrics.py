from __future__ import annotations

from dataclasses import replace

import pytest

from qhapaq_finance.diamond.contracts import FiscalSlot
from qhapaq_finance.diamond.metrics import derive_financial_features

try:
    from tests.diamond_helpers import rich_record
except ModuleNotFoundError:
    from diamond_helpers import rich_record


def _replace_observation(record, metric_id: str, slot: FiscalSlot, **changes):
    items = []
    for item in record.observations:
        if item.metric_id == metric_id and item.fiscal_slot is slot:
            items.append(replace(item, **changes))
        else:
            items.append(item)
    return replace(record, observations=tuple(items))


def test_fcf_is_ocf_minus_positive_capex() -> None:
    record = rich_record("AAA")
    record = _replace_observation(record, "operating_cash_flow", FiscalSlot.TTM, value=120.0)
    record = _replace_observation(record, "capital_expenditures", FiscalSlot.TTM, value=35.0)
    result = derive_financial_features(record)
    assert result.metrics.fcf_ttm == pytest.approx(85.0)


def test_normalized_fcf_is_median_of_ttm_and_fy1_to_fy3() -> None:
    record = rich_record("AAA")
    targets = {
        FiscalSlot.TTM: (220.0, 20.0),
        FiscalSlot.FY1: (120.0, 20.0),
        FiscalSlot.FY2: (100.0, 20.0),
        FiscalSlot.FY3: (80.0, 20.0),
    }
    for slot, (ocf, capex) in targets.items():
        record = _replace_observation(record, "operating_cash_flow", slot, value=ocf)
        record = _replace_observation(record, "capital_expenditures", slot, value=capex)
    # FCF values are 200, 100, 80, 60 -> median 90.
    assert derive_financial_features(record).features.normalized_fcf == pytest.approx(90.0)


def test_growth_feature_uses_fcf_margin_trend_not_absolute_fcf_growth() -> None:
    record = rich_record("AAA", scale=1.0, growth=0.0)
    margins = {
        FiscalSlot.FY1: 0.12,
        FiscalSlot.FY2: 0.10,
        FiscalSlot.FY3: 0.09,
        FiscalSlot.FY4: 0.09,
    }
    for slot, margin in margins.items():
        revenue = next(
            item.value
            for item in record.observations
            if item.metric_id == "revenue" and item.fiscal_slot is slot
        )
        capex = next(
            item.value
            for item in record.observations
            if item.metric_id == "capital_expenditures" and item.fiscal_slot is slot
        )
        record = _replace_observation(
            record,
            "operating_cash_flow",
            slot,
            value=revenue * margin + capex,
        )
    assert derive_financial_features(record).features.fcf_margin_trend == pytest.approx(0.01)


def test_recent_share_change_requires_matching_share_basis() -> None:
    record = rich_record("AAA", recent_share_change=0.025)
    record = _replace_observation(
        record,
        "shares_outstanding_latest",
        FiscalSlot.LATEST,
        adjustment_basis_id="split-v2",
    )
    result = derive_financial_features(record)
    assert result.features.recent_share_change is None
    assert "CURRENT_SHARE_SERIES_INCONSISTENT" in result.diagnostics


def test_recent_dilution_diagnostic_starts_at_two_percent() -> None:
    result = derive_financial_features(rich_record("AAA", recent_share_change=0.02))
    assert result.features.recent_share_change == pytest.approx(0.02)
    assert "RECENT_DILUTION" in result.diagnostics


def test_operating_loss_does_not_create_favorable_leverage_or_ebit_yield() -> None:
    record = rich_record("AAA")
    record = _replace_observation(record, "operating_income", FiscalSlot.TTM, value=-10.0)
    result = derive_financial_features(record)
    assert result.features.net_debt_to_operating_income is None
    assert result.features.ebit_ev_yield is None
    assert "OPERATING_LOSS" in result.diagnostics


def test_nonpositive_revenue_endpoint_does_not_fabricate_cagr() -> None:
    record = rich_record("AAA")
    record = _replace_observation(record, "revenue", FiscalSlot.FY4, value=0.0)
    assert derive_financial_features(record).features.revenue_cagr_3y is None


def test_negative_fcf_is_preserved() -> None:
    record = rich_record("AAA")
    record = _replace_observation(record, "operating_cash_flow", FiscalSlot.TTM, value=10.0)
    record = _replace_observation(record, "capital_expenditures", FiscalSlot.TTM, value=30.0)
    assert derive_financial_features(record).metrics.fcf_ttm == pytest.approx(-20.0)
