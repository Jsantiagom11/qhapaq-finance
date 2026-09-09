"""Build the QCOM valuation case from frozen SEC-filing evidence."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from .evidence import DerivedFact, FinancialFact, load_facts, reconstruct_ttm
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


def _ttm(facts: dict[str, FinancialFact], name: str) -> DerivedFact:
    return reconstruct_ttm(
        annual=facts[f"{name}_fy25"],
        prior_ytd=facts[f"{name}_9m25"],
        current_ytd=facts[f"{name}_9m26"],
        identifier=f"ttm_{name}_q3fy26",
    )


def _operating_nwc(facts: dict[str, FinancialFact], suffix: str) -> float:
    """AR + inventory - trade AP - accrued operating liabilities; excludes cash/debt."""
    return (
        facts[f"ar_{suffix}"].value
        + facts[f"inventory_{suffix}"].value
        - facts[f"ap_{suffix}"].value
        - facts[f"accruals_{suffix}"].value
    )


def _require_reconciled(facts: dict[str, FinancialFact]) -> None:
    """Hard gate: QCOM cannot enter valuation with unreconciled primary bridges."""
    for name, expected in EXPECTED_TTM.items():
        if _ttm(facts, name).value != expected:
            raise ValueError(f"QCOM evidence reconciliation failed for TTM {name}")
    if facts["cash_q3fy26"].value + facts["marketable_securities_q3fy26"].value != 8_304:
        raise ValueError("QCOM evidence reconciliation failed for liquid assets")
    if facts["short_term_debt_q3fy26"].value + facts["long_term_debt_q3fy26"].value != 15_270:
        raise ValueError("QCOM evidence reconciliation failed for debt")


def load_qcom_case(repository_root: str | Path = ".") -> ResearchCase:
    root = Path(repository_root)
    facts = load_facts(root / "data/research/qcom/financial-evidence.json", root, as_of=QCOM_AS_OF)
    _require_reconciled(facts)
    ebit, da, capex = (_ttm(facts, name) for name in ("ebit", "da", "capex"))
    opening_nwc, closing_nwc = _operating_nwc(facts, "fy25"), _operating_nwc(facts, "q3fy26")
    change_nwc = closing_nwc - opening_nwc
    # Tax, scenarios and market-risk inputs are explicit analyst assumptions, not SEC facts.
    tax_rate = 0.18
    market = MarketSnapshot(
        price=168.6358,
        shares_outstanding=facts["shares_cover_q3fy26"].value,
        cash_and_equivalents=facts["cash_q3fy26"].value,
        marketable_securities=facts["marketable_securities_q3fy26"].value,
        debt=(facts["short_term_debt_q3fy26"].value + facts["long_term_debt_q3fy26"].value),
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
    invested_capital = (
        (opening_nwc + facts["net_operating_assets_fy25"].value)
        + (closing_nwc + facts["net_operating_assets_q3fy26"].value)
    ) / 2
    return ResearchCase(
        "QCOM",
        QCOM_AS_OF,
        (
            "EVIDENCE-BACKED: frozen SEC 10-K/10-Q facts; derived TTM = FY2025 - 9M FY2025 "
            "+ 9M FY2026."
        ),
        FcffInputs(ebit.value, tax_rate, da.value, capex.value, change_nwc),
        (
            NormalizationAdjustment(
                "No discretionary normalization; uncertain adjustments default to zero", 0.0
            ),
        ),
        cost,
        invested_capital,
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
        "revenue": _ttm(facts, "revenue").value,
        "ebit": _ttm(facts, "ebit").value,
        "ttm_revenue_bridge": "44,284 - 33,013 + 32,798 = 44,069",
        "ttm_ebit_bridge": "12,355 - 9,437 + 7,302 = 10,220",
        "ttm_source_fact_selection": selections,
        "opening_operating_nwc": _operating_nwc(facts, "fy25"),
        "closing_operating_nwc": _operating_nwc(facts, "q3fy26"),
        "change_operating_nwc": _operating_nwc(facts, "q3fy26") - _operating_nwc(facts, "fy25"),
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
