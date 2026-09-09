"""Build the QCOM valuation case from frozen SEC-filing evidence."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from .accounting import (
    AccountingEvidenceSpec,
    AccountingSnapshot,
    TtmFactSpec,
    normalize_accounting_snapshot,
)
from .evidence import FinancialFact, load_facts
from .valuation import (
    CapitalCost,
    FcffInputs,
    MarketSnapshot,
    NormalizationAdjustment,
    ResearchCase,
    ScenarioAssumptions,
)

QCOM_AS_OF = date(2026, 9, 8)
EXPECTED_TTM = {"revenue": 44_069.0, "ebit": 10_220.0}

# These identifiers are a company-specific evidence selection, not financial logic.
QCOM_ACCOUNTING_SPEC = AccountingEvidenceSpec(
    revenue=TtmFactSpec("revenue_fy25", "revenue_9m25", "revenue_9m26"),
    ebit=TtmFactSpec("ebit_fy25", "ebit_9m25", "ebit_9m26"),
    depreciation_amortization=TtmFactSpec("da_fy25", "da_9m25", "da_9m26"),
    capex=TtmFactSpec("capex_fy25", "capex_9m25", "capex_9m26"),
    capex_source_sign="negative_cash_outflow",
    operating_nwc_opening_assets=("ar_fy25", "inventory_fy25"),
    operating_nwc_opening_liabilities=("ap_fy25", "accruals_fy25"),
    operating_nwc_closing_assets=("ar_q3fy26", "inventory_q3fy26"),
    operating_nwc_closing_liabilities=("ap_q3fy26", "accruals_q3fy26"),
    net_operating_assets_opening=("net_operating_assets_fy25",),
    net_operating_assets_closing=("net_operating_assets_q3fy26",),
    cash=("cash_q3fy26",),
    marketable_securities=("marketable_securities_q3fy26",),
    debt=("short_term_debt_q3fy26", "long_term_debt_q3fy26"),
    valuation_shares="shares_cover_q3fy26",
    valuation_share_basis="common_shares_outstanding",
)


def _accounting_snapshot(facts: dict[str, FinancialFact]) -> AccountingSnapshot:
    # Tax is an explicit assumption, because it is not a normalized operating tax fact.
    return normalize_accounting_snapshot(facts, spec=QCOM_ACCOUNTING_SPEC, tax_rate=0.18)


def _require_reconciled(facts: dict[str, FinancialFact]) -> None:
    """Hard gate: QCOM cannot enter valuation with unreconciled primary bridges."""
    snapshot = _accounting_snapshot(facts)
    assert snapshot.cash is not None
    assert snapshot.marketable_securities is not None
    assert snapshot.debt is not None
    for name, expected in EXPECTED_TTM.items():
        if getattr(snapshot, name) != expected:
            raise ValueError(f"QCOM evidence reconciliation failed for TTM {name}")
    if snapshot.cash + snapshot.marketable_securities != 8_304:
        raise ValueError("QCOM evidence reconciliation failed for liquid assets")
    if snapshot.debt != 15_270:
        raise ValueError("QCOM evidence reconciliation failed for debt")


def load_qcom_case(repository_root: str | Path = ".") -> ResearchCase:
    root = Path(repository_root)
    facts = load_facts(root / "data/research/qcom/financial-evidence.json", root, as_of=QCOM_AS_OF)
    _require_reconciled(facts)
    snapshot = _accounting_snapshot(facts)
    # Tax, scenarios and market-risk inputs are explicit analyst assumptions, not SEC facts.
    tax_rate = snapshot.tax_rate
    assert tax_rate is not None
    assert snapshot.valuation_shares is not None
    assert snapshot.cash is not None
    assert snapshot.marketable_securities is not None
    assert snapshot.debt is not None
    market = MarketSnapshot(
        price=168.6358,
        shares_outstanding=snapshot.valuation_shares,
        cash_and_equivalents=snapshot.cash,
        marketable_securities=snapshot.marketable_securities,
        debt=snapshot.debt,
    )
    cost = CapitalCost.from_assumptions(
        risk_free_rate=0.04,
        equity_risk_premium=0.05,
        beta=1.10,
        pre_tax_cost_of_debt=0.045,
        tax_rate=tax_rate,
        market_equity=market.equity_value,
        debt=market.debt,
    )
    assert snapshot.ebit is not None and snapshot.depreciation_amortization is not None
    assert snapshot.capex is not None and snapshot.change_in_working_capital is not None
    assert snapshot.invested_capital is not None
    return ResearchCase(
        "QCOM",
        QCOM_AS_OF,
        (
            "EVIDENCE-BACKED: frozen SEC 10-K/10-Q facts; derived TTM = FY2025 - 9M FY2025 "
            "+ 9M FY2026."
        ),
        FcffInputs(
            snapshot.ebit,
            tax_rate,
            snapshot.depreciation_amortization,
            snapshot.capex,
            snapshot.change_in_working_capital,
        ),
        (
            NormalizationAdjustment(
                "No discretionary normalization; uncertain adjustments default to zero", 0.0
            ),
        ),
        cost,
        snapshot.invested_capital,
        0.32,
        (
            ScenarioAssumptions("bear", 0.01, 0.02, 8),
            ScenarioAssumptions("base", 0.06, 0.025, 8),
            ScenarioAssumptions("bull", 0.10, 0.03, 8),
        ),
        market,
        (
            "Licensing and semiconductor economics can generate cash conversion; "
            "TTM evidence is volatile.",
        ),
        ("Sustained licensing pressure or a severe handset-cycle impairment.",),
        (
            "SBC is in EBIT and CFO reconciliation; it is not separately subtracted from FCFF."
            " Cover-page shares as of 2026-07-27 are used for market equity, not EPS averages.",
        ),
    )


def qcom_audit(repository_root: str | Path = ".") -> dict[str, object]:
    facts = load_facts(
        Path(repository_root) / "data/research/qcom/financial-evidence.json",
        repository_root,
        as_of=QCOM_AS_OF,
    )
    _require_reconciled(facts)
    snapshot = _accounting_snapshot(facts)
    selected = (
        "revenue_fy25",
        "ebit_fy25",
        "revenue_9m25",
        "ebit_9m25",
        "revenue_9m26",
        "ebit_9m26",
    )
    selections = " | ".join(
        f"{fact.id}: {fact.concept}={fact.value:g}; {fact.fiscal_period} ended "
        f"{fact.period_end}; {fact.method}"
        for fact in (facts[identifier] for identifier in selected)
    )
    return {
        "evidence_as_of": QCOM_AS_OF.isoformat(),
        "latest_filing": facts["cash_q3fy26"].filing.accession_number,
        "ttm_period": "FY2025 - 9M FY2025 + 9M FY2026, ended 2026-06-28",
        "ttm_formula": "TTM = FY - prior 9M + current 9M",
        "ttm_labels": ("FY", "Prior 9M", "Current 9M", "TTM"),
        "ttm_revenue_values": (44_284, 33_013, 32_798, 44_069),
        "ttm_ebit_values": (12_355, 9_437, 7_302, 10_220),
        "revenue": snapshot.revenue,
        "ebit": snapshot.ebit,
        "ttm_revenue_bridge": "44,284 - 33,013 + 32,798 = 44,069",
        "ttm_ebit_bridge": "12,355 - 9,437 + 7,302 = 10,220",
        "ttm_source_fact_selection": selections,
        "opening_operating_nwc": 8229,
        "closing_operating_nwc": 8704,
        "change_operating_nwc": snapshot.change_in_working_capital,
        "normalization_adjustments": "0; uncertain discretionary adjustments default to zero",
        "capital_market_snapshot_date": "2026-09-04",
        "cash_and_equivalents": facts["cash_q3fy26"].value,
        "marketable_securities": facts["marketable_securities_q3fy26"].value,
        "cash_and_marketable_securities": 8_304,
        "debt_bridge": "short-term debt 2,489 + long-term debt 12,781 = 15,270",
        "share_count_semantics": (
            "1,057m balance-sheet shares at 2026-06-28; 1,050m cover-page shares at 2026-07-27 "
            "used for market equity"
        ),
        "invested_capital_convention": "average operating NWC plus net operating assets",
        "data_quality_warnings": (
            "Market price and WACC inputs are frozen external/analyst inputs; "
            "they are not SEC accounting facts."
        ),
        "sbc_treatment": (
            "Included in EBIT; CFO add-back is not added again in FCFF; "
            "dilution handled by period-end shares."
        ),
    }
