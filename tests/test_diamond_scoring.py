from __future__ import annotations

import pytest

from qhapaq_finance.diamond.metrics import derive_financial_features
from qhapaq_finance.diamond.scoring import score_categories

try:
    from tests.diamond_helpers import rich_record
except ModuleNotFoundError:
    from diamond_helpers import rich_record


def _features():
    return derive_financial_features(rich_record("AAA"))


def test_quality_requires_three_components_and_roic_or_cash_conversion() -> None:
    scores = score_categories(
        _features(),
        {
            "normalized_fcf_margin": 80.0,
            "margin_dispersion": 70.0,
            "fcf_margin_dispersion": 60.0,
        },
        market_fresh=True,
    )
    assert scores.quality is None


def test_quality_renormalizes_only_available_weights() -> None:
    scores = score_categories(
        _features(),
        {
            "roic_proxy": 80.0,
            "normalized_fcf_margin": 60.0,
            "margin_dispersion": 40.0,
        },
        market_fresh=True,
    )
    expected = (0.35 * 80 + 0.25 * 60 + 0.10 * 40) / (0.35 + 0.25 + 0.10)
    assert scores.quality == pytest.approx(expected)


def test_growth_requires_revenue_cagr_3y() -> None:
    scores = score_categories(
        _features(),
        {"revenue_cagr_5y": 90.0, "fcf_margin_trend": 80.0, "operating_margin_trend": 70.0},
        market_fresh=True,
    )
    assert scores.growth is None


def test_recent_dilution_percentile_changes_capital_score() -> None:
    common = {
        "net_debt_to_operating_income": 70.0,
        "share_dilution_3y": 80.0,
        "roic_proxy": 75.0,
        "net_cash_indicator": 60.0,
    }
    good = score_categories(_features(), {**common, "recent_share_change": 90.0}, market_fresh=True)
    bad = score_categories(_features(), {**common, "recent_share_change": 10.0}, market_fresh=True)
    assert good.capital is not None and bad.capital is not None
    assert good.capital > bad.capital


def test_stale_market_data_nulls_price_only() -> None:
    percentiles = {
        "roic_proxy": 80.0,
        "normalized_fcf_margin": 70.0,
        "cash_conversion": 60.0,
        "margin_dispersion": 50.0,
        "fcf_margin_dispersion": 40.0,
        "normalized_fcf_yield": 90.0,
        "ebit_ev_yield": 80.0,
    }
    scores = score_categories(_features(), percentiles, market_fresh=False)
    assert scores.price is None
    assert scores.quality is not None


def test_price_requires_normalized_fcf_yield_even_if_ebit_yield_exists() -> None:
    scores = score_categories(_features(), {"ebit_ev_yield": 90.0}, market_fresh=True)
    assert scores.price is None
