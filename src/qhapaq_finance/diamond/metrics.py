"""Pure financial derivations for Diamond Funnel.

The module consumes canonical observations only. It never performs network I/O,
provider field mapping, or filing-native accounting reconstruction.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import median

from .contracts import FiscalSlot, FundamentalObservation, FundamentalRecord


@dataclass(frozen=True, slots=True)
class CompressedMetrics:
    revenue_ttm: float | None
    operating_income_ttm: float | None
    operating_margin_ttm: float | None
    operating_cash_flow_ttm: float | None
    capex_ttm: float | None
    fcf_ttm: float | None
    fcf_margin_ttm: float | None
    cash_and_marketable_securities: float | None
    total_debt: float | None
    net_debt: float | None
    diluted_shares: float | None
    share_dilution_3y: float | None
    market_cap: float | None
    enterprise_value: float | None
    normalized_fcf_yield: float | None


@dataclass(frozen=True, slots=True)
class AnalyticalFeatures:
    normalized_fcf: float | None
    normalized_fcf_margin: float | None
    revenue_cagr_3y: float | None
    revenue_cagr_5y: float | None
    fcf_margin_trend: float | None
    operating_margin_trend: float | None
    effective_tax_rate: float | None
    roic_proxy: float | None
    cash_conversion: float | None
    recent_share_change: float | None
    net_debt_to_operating_income: float | None
    margin_dispersion: float | None
    fcf_margin_dispersion: float | None
    negative_fcf_ratio: float | None
    net_cash_indicator: float | None
    ebit_ev_yield: float | None
    peak_ttm_ratio: float | None


@dataclass(frozen=True, slots=True)
class FinancialFeatureSet:
    metrics: CompressedMetrics
    features: AnalyticalFeatures
    diagnostics: tuple[str, ...]


def observation(
    record: FundamentalRecord, metric_id: str, slot: FiscalSlot
) -> FundamentalObservation | None:
    return next(
        (
            item
            for item in record.observations
            if item.metric_id == metric_id and item.fiscal_slot is slot
        ),
        None,
    )


def value(record: FundamentalRecord, metric_id: str, slot: FiscalSlot) -> float | None:
    item = observation(record, metric_id, slot)
    return None if item is None else item.value


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    result = numerator / denominator
    return result if math.isfinite(result) else None


def _fcf(record: FundamentalRecord, slot: FiscalSlot) -> float | None:
    ocf = value(record, "operating_cash_flow", slot)
    capex = value(record, "capital_expenditures", slot)
    if ocf is None or capex is None:
        return None
    # Canonical capex is a positive outflow by contract.
    return ocf - capex


def _margin(record: FundamentalRecord, metric_id: str, slot: FiscalSlot) -> float | None:
    return _ratio(value(record, metric_id, slot), value(record, "revenue", slot))


def _median(values: list[float], *, minimum: int = 1) -> float | None:
    if len(values) < minimum:
        return None
    return float(median(values))


def _cagr(end: float | None, start: float | None, intervals: int) -> float | None:
    if end is None or start is None or end <= 0 or start <= 0 or intervals <= 0:
        return None
    result = (end / start) ** (1.0 / intervals) - 1.0
    return result if math.isfinite(result) else None


def _invested_capital_proxy(record: FundamentalRecord, slot: FiscalSlot) -> float | None:
    equity = value(record, "total_equity", slot)
    debt = value(record, "total_debt", slot)
    cash = value(record, "cash_and_equivalents", slot)
    securities = value(record, "marketable_securities", slot)
    if equity is None or debt is None or cash is None:
        return None
    return equity + debt - cash - (securities or 0.0)


def _dispersion(values: list[float]) -> float | None:
    if len(values) < 4:
        return None
    med = float(median(values))
    mad = float(median([abs(item - med) for item in values]))
    denominator = max(abs(med), 0.05)
    result = mad / denominator
    return result if math.isfinite(result) else None


def _compatible_share_basis(
    left: FundamentalObservation | None,
    right: FundamentalObservation | None,
) -> bool:
    if left is None or right is None:
        return False
    return bool(
        left.share_class_id
        and right.share_class_id
        and left.adjustment_basis_id
        and right.adjustment_basis_id
        and left.share_class_id == right.share_class_id
        and left.adjustment_basis_id == right.adjustment_basis_id
    )


def derive_financial_features(record: FundamentalRecord) -> FinancialFeatureSet:
    diagnostics: set[str] = set()

    revenue_ttm = value(record, "revenue", FiscalSlot.TTM)
    operating_income_ttm = value(record, "operating_income", FiscalSlot.TTM)
    ocf_ttm = value(record, "operating_cash_flow", FiscalSlot.TTM)
    capex_ttm = value(record, "capital_expenditures", FiscalSlot.TTM)
    fcf_ttm = _fcf(record, FiscalSlot.TTM)

    operating_margin_ttm = _ratio(operating_income_ttm, revenue_ttm)
    fcf_margin_ttm = _ratio(fcf_ttm, revenue_ttm)

    cash = value(record, "cash_and_equivalents", FiscalSlot.LATEST)
    marketable = value(record, "marketable_securities", FiscalSlot.LATEST)
    cash_and_marketable = None if cash is None else cash + (marketable or 0.0)
    debt = value(record, "total_debt", FiscalSlot.LATEST)
    net_debt = None if debt is None or cash_and_marketable is None else debt - cash_and_marketable
    market_cap = value(record, "market_cap", FiscalSlot.LATEST)
    enterprise_value = None if market_cap is None or net_debt is None else market_cap + net_debt

    provider_ev = value(record, "enterprise_value_provider", FiscalSlot.LATEST)
    if provider_ev is not None and enterprise_value is not None and enterprise_value != 0:
        if abs(provider_ev - enterprise_value) / abs(enterprise_value) > 0.10:
            diagnostics.add("EV_CONSISTENCY_WARN")

    fcf_history = {
        slot: _fcf(record, slot)
        for slot in (FiscalSlot.TTM, FiscalSlot.FY1, FiscalSlot.FY2, FiscalSlot.FY3)
    }
    normalized_values = [item for item in fcf_history.values() if item is not None]
    normalized_fcf = _median(normalized_values, minimum=3)
    normalized_fcf_yield = _ratio(normalized_fcf, market_cap)

    revenue_hist_for_norm = [
        item
        for item in (
            value(record, "revenue", FiscalSlot.FY1),
            value(record, "revenue", FiscalSlot.FY2),
            value(record, "revenue", FiscalSlot.FY3),
        )
        if item is not None and item > 0
    ]
    revenue_median = _median(revenue_hist_for_norm)
    normalized_fcf_margin = _ratio(normalized_fcf, revenue_median)

    revenue_fy1 = value(record, "revenue", FiscalSlot.FY1)
    revenue_fy4 = value(record, "revenue", FiscalSlot.FY4)
    revenue_fy5 = value(record, "revenue", FiscalSlot.FY5)
    revenue_cagr_3y = _cagr(revenue_fy1, revenue_fy4, 3)
    revenue_cagr_5y = _cagr(revenue_fy1, revenue_fy5, 4)

    fcf_margins: dict[FiscalSlot, float | None] = {}
    op_margins: dict[FiscalSlot, float | None] = {}
    for slot in (FiscalSlot.FY1, FiscalSlot.FY2, FiscalSlot.FY3, FiscalSlot.FY4, FiscalSlot.FY5):
        fcf_margins[slot] = _ratio(_fcf(record, slot), value(record, "revenue", slot))
        op_margins[slot] = _margin(record, "operating_income", slot)

    deltas: list[float] = []
    for newer, older in (
        (FiscalSlot.FY1, FiscalSlot.FY2),
        (FiscalSlot.FY2, FiscalSlot.FY3),
        (FiscalSlot.FY3, FiscalSlot.FY4),
    ):
        left = fcf_margins[newer]
        right = fcf_margins[older]
        if left is not None and right is not None:
            deltas.append(left - right)
    fcf_margin_trend = _median(deltas, minimum=2)

    op_fy1 = op_margins[FiscalSlot.FY1]
    op_fy3 = op_margins[FiscalSlot.FY3]
    operating_margin_trend = None if op_fy1 is None or op_fy3 is None else op_fy1 - op_fy3

    pretax = value(record, "pretax_income", FiscalSlot.FY1)
    tax_expense = value(record, "income_tax_expense", FiscalSlot.FY1)
    effective_tax_rate: float | None = None
    if pretax is not None and tax_expense is not None and pretax > 0 and tax_expense >= 0:
        candidate = tax_expense / pretax
        if 0 <= candidate <= 0.50:
            effective_tax_rate = candidate

    invested_fy1 = _invested_capital_proxy(record, FiscalSlot.FY1)
    invested_fy2 = _invested_capital_proxy(record, FiscalSlot.FY2)
    avg_invested = None
    if invested_fy1 is not None and invested_fy2 is not None:
        avg_invested = (invested_fy1 + invested_fy2) / 2.0
    op_income_fy1 = value(record, "operating_income", FiscalSlot.FY1)
    roic_proxy = None
    if (
        effective_tax_rate is not None
        and avg_invested is not None
        and avg_invested > 0
        and op_income_fy1 is not None
    ):
        roic_proxy = op_income_fy1 * (1.0 - effective_tax_rate) / avg_invested

    op_hist = [
        item
        for item in (
            value(record, "operating_income", FiscalSlot.FY1),
            value(record, "operating_income", FiscalSlot.FY2),
            value(record, "operating_income", FiscalSlot.FY3),
        )
        if item is not None
    ]
    op_median = _median(op_hist)
    cash_conversion = _ratio(normalized_fcf, op_median)

    latest_shares = observation(record, "shares_outstanding_latest", FiscalSlot.LATEST)
    fy1_end_shares = observation(record, "shares_outstanding_fy1_end", FiscalSlot.FY1)
    recent_share_change = None
    if latest_shares is not None and fy1_end_shares is not None:
        if (
            latest_shares.value > 0
            and fy1_end_shares.value > 0
            and _compatible_share_basis(latest_shares, fy1_end_shares)
        ):
            recent_share_change = latest_shares.value / fy1_end_shares.value - 1.0
            if recent_share_change >= 0.02:
                diagnostics.add("RECENT_DILUTION")
        else:
            diagnostics.add("CURRENT_SHARE_SERIES_INCONSISTENT")

    diluted_fy1 = observation(record, "diluted_shares", FiscalSlot.FY1)
    diluted_fy4 = observation(record, "diluted_shares", FiscalSlot.FY4)
    share_dilution_3y = None
    if diluted_fy1 is not None and diluted_fy4 is not None:
        compatible = bool(
            diluted_fy1.adjustment_basis_id
            and diluted_fy4.adjustment_basis_id
            and diluted_fy1.adjustment_basis_id == diluted_fy4.adjustment_basis_id
        )
        if diluted_fy1.value > 0 and diluted_fy4.value > 0 and compatible:
            share_dilution_3y = (diluted_fy1.value / diluted_fy4.value) ** (1.0 / 3.0) - 1.0
        else:
            diagnostics.add("SHARE_SERIES_INCONSISTENT")

    net_debt_to_operating_income = None
    ebit_ev_yield = None
    if operating_income_ttm is not None and operating_income_ttm <= 0:
        diagnostics.add("OPERATING_LOSS")
    elif operating_income_ttm is not None and operating_income_ttm > 0:
        if net_debt is not None:
            net_debt_to_operating_income = net_debt / operating_income_ttm
        if enterprise_value is not None and enterprise_value > 0:
            ebit_ev_yield = operating_income_ttm / enterprise_value

    op_margin_values = [item for item in op_margins.values() if item is not None]
    fcf_margin_values = [item for item in fcf_margins.values() if item is not None]
    margin_dispersion = _dispersion(op_margin_values)
    fcf_margin_dispersion = _dispersion(fcf_margin_values)

    fiscal_fcfs = [
        item
        for item in (
            _fcf(record, FiscalSlot.FY1),
            _fcf(record, FiscalSlot.FY2),
            _fcf(record, FiscalSlot.FY3),
            _fcf(record, FiscalSlot.FY4),
            _fcf(record, FiscalSlot.FY5),
        )
        if item is not None
    ]
    negative_fcf_ratio = None
    if fiscal_fcfs:
        negative_fcf_ratio = sum(item <= 0 for item in fiscal_fcfs) / len(fiscal_fcfs)
        if negative_fcf_ratio > 0:
            diagnostics.add("NEGATIVE_FCF_HISTORY")

    net_cash_indicator = None if net_debt is None else float(net_debt < 0)

    peak_ttm_ratio = None
    if fcf_ttm is not None and normalized_fcf is not None:
        peak_ttm_ratio = fcf_ttm / max(abs(normalized_fcf), 1e-12)
        if fcf_ttm > 0 and normalized_fcf > 0 and peak_ttm_ratio >= 1.75:
            diagnostics.add("CYCLICAL_PEAK_RISK")

    diluted_ttm = value(record, "diluted_shares", FiscalSlot.TTM)

    metrics = CompressedMetrics(
        revenue_ttm,
        operating_income_ttm,
        operating_margin_ttm,
        ocf_ttm,
        capex_ttm,
        fcf_ttm,
        fcf_margin_ttm,
        cash_and_marketable,
        debt,
        net_debt,
        diluted_ttm,
        share_dilution_3y,
        market_cap,
        enterprise_value,
        normalized_fcf_yield,
    )
    features = AnalyticalFeatures(
        normalized_fcf,
        normalized_fcf_margin,
        revenue_cagr_3y,
        revenue_cagr_5y,
        fcf_margin_trend,
        operating_margin_trend,
        effective_tax_rate,
        roic_proxy,
        cash_conversion,
        recent_share_change,
        net_debt_to_operating_income,
        margin_dispersion,
        fcf_margin_dispersion,
        negative_fcf_ratio,
        net_cash_indicator,
        ebit_ev_yield,
        peak_ttm_ratio,
    )
    return FinancialFeatureSet(metrics, features, tuple(sorted(diagnostics)))
