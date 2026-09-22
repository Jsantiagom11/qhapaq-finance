"""Deterministic category compression for Diamond Funnel."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .metrics import FinancialFeatureSet


@dataclass(frozen=True, slots=True)
class CategoryScores:
    quality: float | None
    growth: float | None
    capital: float | None
    price: float | None


def _weighted(
    percentiles: Mapping[str, float | None],
    weights: Mapping[str, float],
    *,
    minimum_present: int,
    required_all: tuple[str, ...] = (),
    required_any: tuple[str, ...] = (),
) -> float | None:
    if any(percentiles.get(name) is None for name in required_all):
        return None
    if required_any and not any(percentiles.get(name) is not None for name in required_any):
        return None
    available = [
        (name, percentiles.get(name)) for name in weights if percentiles.get(name) is not None
    ]
    if len(available) < minimum_present:
        return None
    denominator = sum(weights[name] for name, _ in available)
    if denominator <= 0:
        return None
    numerator = sum(weights[name] * float(value) for name, value in available if value is not None)
    return numerator / denominator


def score_categories(
    features: FinancialFeatureSet,
    percentiles: Mapping[str, float | None],
    *,
    market_fresh: bool,
) -> CategoryScores:
    quality = _weighted(
        percentiles,
        {
            "roic_proxy": 0.35,
            "normalized_fcf_margin": 0.25,
            "cash_conversion": 0.20,
            "margin_dispersion": 0.10,
            "fcf_margin_dispersion": 0.10,
        },
        minimum_present=3,
        required_any=("roic_proxy", "cash_conversion"),
    )
    growth = _weighted(
        percentiles,
        {
            "revenue_cagr_5y": 0.45,
            "revenue_cagr_3y": 0.25,
            "fcf_margin_trend": 0.20,
            "operating_margin_trend": 0.10,
        },
        minimum_present=2,
        required_all=("revenue_cagr_3y",),
    )
    capital = _weighted(
        percentiles,
        {
            "net_debt_to_operating_income": 0.35,
            "share_dilution_3y": 0.20,
            "recent_share_change": 0.15,
            "roic_proxy": 0.20,
            "net_cash_indicator": 0.10,
        },
        minimum_present=2,
        required_all=("share_dilution_3y",),
    )
    price = None
    if market_fresh and percentiles.get("normalized_fcf_yield") is not None:
        price = _weighted(
            percentiles,
            {"normalized_fcf_yield": 0.60, "ebit_ev_yield": 0.40},
            minimum_present=1,
            required_all=("normalized_fcf_yield",),
        )
    return CategoryScores(quality, growth, capital, price)
