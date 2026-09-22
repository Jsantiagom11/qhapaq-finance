from __future__ import annotations

from datetime import date, timedelta

from qhapaq_finance.diamond.contracts import (
    FiscalSlot,
    FundamentalObservation,
    FundamentalPeriodType,
    FundamentalRecord,
    Methodology,
    PeriodKind,
    UnitKind,
)

AS_OF = date(2026, 9, 20)
PERIOD_END = date(2026, 6, 30)


def obs(
    metric_id: str = "revenue",
    slot: FiscalSlot = FiscalSlot.TTM,
    value: float = 100.0,
    *,
    period_start: date | None = date(2025, 7, 1),
    period_end: date = PERIOD_END,
    period_kind: PeriodKind = PeriodKind.DURATION,
    unit_kind: UnitKind = UnitKind.CURRENCY,
    share_class_id: str | None = None,
    adjustment_basis_id: str | None = None,
) -> FundamentalObservation:
    return FundamentalObservation(
        metric_id,
        slot,
        value,
        period_start,
        period_end,
        period_kind,
        unit_kind,
        "fixture",
        f"fixture:{metric_id}:{slot.value}",
        share_class_id,
        adjustment_basis_id,
    )


def make_record(
    ticker: str = "AAA",
    *,
    peer_group_id: str = "Technology",
    data_as_of: date = AS_OF,
    fundamental_period_end: date = PERIOD_END,
    methodology: Methodology = Methodology.OPERATING_COMPANY,
    market_age_trading_days: int | None = 1,
    observations: tuple[FundamentalObservation, ...] | None = None,
    sector: str | None = "Information Technology",
) -> FundamentalRecord:
    return FundamentalRecord(
        ticker=ticker,
        security_id=f"issuer-{ticker.lower()}:{ticker}",
        issuer_id=f"issuer-{ticker.lower()}",
        company_name=f"{ticker} Corp",
        currency="USD",
        peer_group_id=peer_group_id,
        sector=sector,
        industry_group="Software",
        methodology=methodology,
        fiscal_year_end="06-30",
        data_as_of=data_as_of,
        fundamental_period_type=FundamentalPeriodType.TTM,
        fundamental_period_end=fundamental_period_end,
        market_age_trading_days=market_age_trading_days,
        provider="fixture",
        provider_identity=f"fixture:{ticker}",
        observations=observations or (),
    )


def rich_record(
    ticker: str,
    *,
    scale: float = 1.0,
    growth: float = 0.10,
    op_margin: float = 0.25,
    fcf_margin: float = 0.18,
    dilution: float = 0.00,
    recent_share_change: float = 0.00,
    peer_group_id: str = "Technology",
    methodology: Methodology = Methodology.OPERATING_COMPANY,
    period_end: date = PERIOD_END,
    market_age_trading_days: int | None = 1,
) -> FundamentalRecord:
    observations: list[FundamentalObservation] = []
    slots = (FiscalSlot.FY1, FiscalSlot.FY2, FiscalSlot.FY3, FiscalSlot.FY4, FiscalSlot.FY5)
    fiscal_ends = {
        FiscalSlot.FY1: date(2026, 6, 30),
        FiscalSlot.FY2: date(2025, 6, 30),
        FiscalSlot.FY3: date(2024, 6, 30),
        FiscalSlot.FY4: date(2023, 6, 30),
        FiscalSlot.FY5: date(2022, 6, 30),
    }
    for index, slot in enumerate(slots):
        end = fiscal_ends[slot]
        start = date(end.year - 1, 7, 1)
        revenue = 1000.0 * scale / ((1.0 + growth) ** index)
        operating = revenue * (op_margin - index * 0.002)
        fcf = revenue * (fcf_margin - index * 0.003)
        capex = revenue * 0.05
        ocf = fcf + capex
        for metric, amount in (
            ("revenue", revenue),
            ("operating_income", operating),
            ("net_income", operating * 0.78),
            ("operating_cash_flow", ocf),
            ("capital_expenditures", capex),
            ("pretax_income", operating * 0.95),
            ("income_tax_expense", operating * 0.95 * 0.21),
        ):
            observations.append(obs(metric, slot, amount, period_start=start, period_end=end))
        for metric, amount in (
            ("cash_and_equivalents", 180.0 * scale / (1 + index * 0.05)),
            ("marketable_securities", 40.0 * scale),
            ("total_debt", 220.0 * scale * (1 + index * 0.02)),
            ("total_equity", 600.0 * scale / (1 + index * 0.04)),
        ):
            observations.append(
                obs(
                    metric,
                    slot,
                    amount,
                    period_start=None,
                    period_end=end,
                    period_kind=PeriodKind.INSTANT,
                )
            )
        share_value = 100.0 * scale / ((1.0 + dilution) ** max(0, 3 - index))
        observations.append(
            obs(
                "diluted_shares",
                slot,
                share_value,
                period_start=start,
                period_end=end,
                unit_kind=UnitKind.SHARES,
                share_class_id="COMMON",
                adjustment_basis_id="split-v1",
            )
        )

    ttm_revenue = 1000.0 * scale * (1.0 + growth * 0.4)
    ttm_operating = ttm_revenue * op_margin
    ttm_fcf = ttm_revenue * fcf_margin
    ttm_capex = ttm_revenue * 0.05
    ttm_ocf = ttm_fcf + ttm_capex
    start = period_end - timedelta(days=364)
    for metric, amount in (
        ("revenue", ttm_revenue),
        ("operating_income", ttm_operating),
        ("net_income", ttm_operating * 0.78),
        ("operating_cash_flow", ttm_ocf),
        ("capital_expenditures", ttm_capex),
    ):
        observations.append(
            obs(metric, FiscalSlot.TTM, amount, period_start=start, period_end=period_end)
        )
    observations.append(
        obs(
            "diluted_shares",
            FiscalSlot.TTM,
            100.0 * scale * (1.0 + recent_share_change),
            period_start=start,
            period_end=period_end,
            unit_kind=UnitKind.SHARES,
            share_class_id="COMMON",
            adjustment_basis_id="split-v1",
        )
    )

    latest_end = AS_OF
    market_cap = 5000.0 * scale * (1.0 + growth)
    latest_values = (
        ("cash_and_equivalents", 190.0 * scale),
        ("marketable_securities", 45.0 * scale),
        ("total_debt", 210.0 * scale),
        ("market_cap", market_cap),
        ("enterprise_value_provider", market_cap - 25.0 * scale),
        ("price", 50.0 * (1.0 + growth)),
    )
    for metric, amount in latest_values:
        observations.append(
            obs(
                metric,
                FiscalSlot.LATEST,
                amount,
                period_start=None,
                period_end=latest_end,
                period_kind=PeriodKind.INSTANT,
            )
        )
    observations.append(
        obs(
            "shares_outstanding_latest",
            FiscalSlot.LATEST,
            100.0 * scale * (1.0 + recent_share_change),
            period_start=None,
            period_end=latest_end,
            period_kind=PeriodKind.INSTANT,
            unit_kind=UnitKind.SHARES,
            share_class_id="COMMON",
            adjustment_basis_id="split-v1",
        )
    )
    observations.append(
        obs(
            "shares_outstanding_fy1_end",
            FiscalSlot.FY1,
            100.0 * scale,
            period_start=None,
            period_end=date(2026, 6, 30),
            period_kind=PeriodKind.INSTANT,
            unit_kind=UnitKind.SHARES,
            share_class_id="COMMON",
            adjustment_basis_id="split-v1",
        )
    )
    return make_record(
        ticker,
        peer_group_id=peer_group_id,
        methodology=methodology,
        fundamental_period_end=period_end,
        market_age_trading_days=market_age_trading_days,
        observations=tuple(observations),
        sector=peer_group_id,
    )
