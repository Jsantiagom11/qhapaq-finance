"""Build the NVIDIA valuation case from frozen SEC-filing evidence."""

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
from .market import load_market_snapshot
from .valuation import (
    CapitalCost,
    FcffInputs,
    MarketSnapshot,
    NormalizationAdjustment,
    ResearchCase,
    ScenarioAssumptions,
)

NVDA_AS_OF = date(2026, 9, 8)
EXPECTED_TTM = {"revenue": 302_970.0, "ebit": 197_579.0}

# These identifiers select NVIDIA disclosures; all accounting arithmetic is generic.
NVDA_ACCOUNTING_SPEC = AccountingEvidenceSpec(
    revenue=TtmFactSpec("revenue_fy26", "revenue_h1fy26", "revenue_h1fy27"),
    ebit=TtmFactSpec("ebit_fy26", "ebit_h1fy26", "ebit_h1fy27"),
    depreciation_amortization=TtmFactSpec("da_fy26", "da_h1fy26", "da_h1fy27"),
    capex=TtmFactSpec("capex_fy26", "capex_h1fy26", "capex_h1fy27"),
    capex_source_sign="negative_cash_outflow",
    operating_nwc_opening_assets=("ar_q2fy26", "inventory_q2fy26"),
    operating_nwc_opening_liabilities=("ap_q2fy26", "accruals_q2fy26"),
    operating_nwc_closing_assets=("ar_q2fy27", "inventory_q2fy27"),
    operating_nwc_closing_liabilities=("ap_q2fy27", "accruals_q2fy27"),
    net_operating_assets_opening=("operating_assets_q2fy26",),
    net_operating_assets_closing=("operating_assets_q2fy27",),
    cash=("cash_q2fy27",),
    marketable_securities=("marketable_securities_q2fy27",),
    debt=("short_term_debt_q2fy27", "long_term_debt_q2fy27"),
    valuation_shares="shares_diluted_h1fy27",
    valuation_share_basis="diluted_weighted_average",
    require_ttm_endpoint_alignment=True,
)


def _accounting_snapshot(facts: dict[str, FinancialFact]) -> AccountingSnapshot:
    # Filing tax expense / pretax income is not asserted to be a durable operating-tax rate.
    return normalize_accounting_snapshot(facts, spec=NVDA_ACCOUNTING_SPEC, tax_rate=0.18)


def _require_reconciled(facts: dict[str, FinancialFact]) -> None:
    snapshot = _accounting_snapshot(facts)
    for name, expected in EXPECTED_TTM.items():
        if getattr(snapshot, name) != expected:
            raise ValueError(f"NVDA evidence reconciliation failed for TTM {name}")
    if snapshot.cash != 22_443 or snapshot.marketable_securities != 76_926:
        raise ValueError("NVDA evidence reconciliation failed for liquid assets")
    if snapshot.debt != 33_366:
        raise ValueError("NVDA evidence reconciliation failed for debt")


def load_nvda_case(repository_root: str | Path = ".") -> ResearchCase:
    root = Path(repository_root)
    facts = load_facts(root / "data/research/nvda/financial-evidence.json", root, as_of=NVDA_AS_OF)
    _require_reconciled(facts)
    snapshot = _accounting_snapshot(facts)
    assert snapshot.tax_rate is not None
    assert snapshot.ebit is not None and snapshot.depreciation_amortization is not None
    assert snapshot.capex is not None and snapshot.change_in_working_capital is not None
    assert snapshot.invested_capital is not None and snapshot.valuation_shares is not None
    assert snapshot.cash is not None and snapshot.marketable_securities is not None
    assert snapshot.debt is not None
    frozen_market = load_market_snapshot(root / "data/research/nvda/market-2026-09-04.json")
    if frozen_market.ticker != "NVDA":
        raise ValueError("NVDA market snapshot ticker mismatch")
    market = MarketSnapshot(
        price=frozen_market.price,
        shares_outstanding=snapshot.valuation_shares,
        cash_and_equivalents=snapshot.cash,
        marketable_securities=snapshot.marketable_securities,
        debt=snapshot.debt,
    )
    cost = CapitalCost.from_assumptions(
        risk_free_rate=0.04,
        equity_risk_premium=0.05,
        beta=1.30,
        pre_tax_cost_of_debt=0.045,
        tax_rate=snapshot.tax_rate,
        market_equity=market.equity_value,
        debt=market.debt,
    )
    return ResearchCase(
        "NVDA",
        NVDA_AS_OF,
        (
            "EVIDENCE-BACKED: frozen SEC FY2026 10-K and Q2 FY2027 10-Q facts; derived "
            "TTM = FY2026 - H1 FY2026 + H1 FY2027."
        ),
        FcffInputs(
            snapshot.ebit,
            snapshot.tax_rate,
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
        0.25,
        (
            ScenarioAssumptions("bear", 0.07, 0.02, 8),
            ScenarioAssumptions("base", 0.15, 0.03, 8),
            ScenarioAssumptions("bull", 0.22, 0.035, 8),
        ),
        market,
        ("AI-infrastructure demand supports exceptional current operating cash generation.",),
        ("A material demand-duration or cash-conversion deterioration.",),
        (
            "Tax rate, WACC, beta, risk premiums, reinvestment and scenario growth are analyst "
            "assumptions. Invested capital includes operating NWC plus net PP&E and intangibles; "
            "it excludes goodwill, leases and financial investments as an explicit classification "
            "policy.",
        ),
    )


def _obsolete_pre_period_alignment_audit(repository_root: str | Path = ".") -> dict[str, object]:
    facts = load_facts(
        Path(repository_root) / "data/research/nvda/financial-evidence.json",
        repository_root,
        as_of=NVDA_AS_OF,
    )
    _require_reconciled(facts)
    snapshot = _accounting_snapshot(facts)
    assert snapshot.valuation_shares is not None
    frozen_market = load_market_snapshot(
        Path(repository_root) / "data/research/nvda/market-2026-09-04.json"
    )
    # The balance-sheet comparison is intentionally surfaced as a six-month
    # trade-working-capital bridge.  It must not be mistaken for a TTM cash-flow
    # input merely because the income-statement lines are TTM.
    opening_trade_nwc = 38_466 + 21_403 - 9_812 - 21_352
    closing_trade_nwc = 63_059 + 31_575 - 15_059 - 26_960
    opening_operating_assets = 10_383 + 3_306
    closing_operating_assets = 14_285 + 2_998
    return {
        "evidence_as_of": NVDA_AS_OF.isoformat(),
        "latest_filing": facts["cash_q2fy27"].filing.accession_number,
        "ttm_period": "FY2026 - H1 FY2026 + H1 FY2027, ended 2026-07-26",
        "ttm_formula": "TTM = FY - prior H1 + current H1",
        "ttm_labels": ("FY", "Prior H1", "Current H1", "TTM"),
        "ttm_revenue_values": (215_938, 90_805, 177_837, 302_970),
        "ttm_ebit_values": (130_387, 50_078, 117_270, 197_579),
        "revenue": snapshot.revenue,
        "ebit": snapshot.ebit,
        "ttm_revenue_bridge": "215,938 - 90,805 + 177,837 = 302,970",
        "ttm_ebit_bridge": "130,387 - 50,078 + 117,270 = 197,579",
        "flow_period_compatibility": {
            "revenue": "FY2026 - H1 FY2026 + H1 FY2027; all durations end 2026-07-26",
            "ebit": "GAAP operating income; same FY/H1 reconstruction as revenue",
            "depreciation_amortization": "2,843 - 1,280 + 2,124 = 3,687; same TTM window",
            "capex": "6,042 - 3,122 + 4,434 = 7,354; positive cash-use convention",
            "nwc": (
                "28,705 at 2026-01-25 to 52,615 at 2026-07-26: a six-month "
                "balance movement, not a TTM movement"
            ),
        },
        "operating_tax_basis": "ASSUMPTION: 18%; no normalized operating tax fact asserted",
        "operating_nwc": {
            "included_current_assets": ("accounts receivable", "inventory"),
            "included_current_liabilities": (
                "accounts payable",
                "accrued and other current liabilities",
            ),
            "excluded": (
                "cash and cash equivalents",
                "marketable debt securities",
                "marketable equity securities",
                "prepaid and other assets (not captured as balance-sheet facts)",
                "other long-term liabilities (not captured as balance-sheet facts)",
                "debt",
            ),
            "opening": opening_trade_nwc,
            "closing": closing_trade_nwc,
            "change": closing_trade_nwc - opening_trade_nwc,
            "balance_window": "2026-01-25 to 2026-07-26 (six months)",
            "ttm_compatible": False,
            "conclusion": (
                "23,910 is arithmetically correct for the narrowly defined trade NWC set, "
                "but is not economically defensible as TTM FCFF change in operating NWC."
            ),
        },
        "opening_operating_nwc": opening_trade_nwc,
        "closing_operating_nwc": closing_trade_nwc,
        "change_operating_nwc": snapshot.change_in_working_capital,
        "invested_capital": {
            "included": {
                "opening_trade_nwc": opening_trade_nwc,
                "opening_net_ppe": 10_383,
                "opening_net_identifiable_intangibles": 3_306,
                "closing_trade_nwc": closing_trade_nwc,
                "closing_net_ppe": 14_285,
                "closing_net_identifiable_intangibles": 2_998,
            },
            "opening_net_operating_assets": opening_operating_assets,
            "closing_net_operating_assets": closing_operating_assets,
            "opening_net_operating_capital": opening_trade_nwc + opening_operating_assets,
            "closing_net_operating_capital": closing_trade_nwc + closing_operating_assets,
            "reported_average": snapshot.invested_capital,
            "average_treatment": "simple average of 2026-01-25 and 2026-07-26 balances",
            "excluded": (
                "cash and cash equivalents",
                "marketable debt securities",
                "marketable equity securities",
                "short-term and long-term debt",
                (
                    "goodwill (not separately represented in frozen evidence; "
                    "policy exclusion cannot be reconciled)"
                ),
                "lease assets/liabilities",
                "prepaid/other assets and other long-term liabilities",
            ),
            "ttm_compatible": False,
            "conclusion": (
                "56,146 is arithmetically correct for the stated six-month endpoint average, "
                "not an average invested-capital denominator matched to TTM NOPAT."
            ),
        },
        "liquid_assets": {
            "cash": 22_443,
            "marketable_debt_securities": 34_143,
            "marketable_equity_securities": 42_783,
            "total": 99_369,
            "treatment": (
                "All three are excluded from operating capital and included once as liquid assets "
                "in the enterprise-to-equity bridge; no double counting."
            ),
        },
        "market_enterprise_to_equity": {
            "enterprise_value": frozen_market.price * snapshot.valuation_shares - 99_369 + 33_366,
            "eligible_liquid_assets": 99_369,
            "debt": 33_366,
            "equity_value": frozen_market.price * snapshot.valuation_shares,
        },
        "share_count": {
            "value": snapshot.valuation_shares,
            "unit": "million shares",
            "period": "2026-08-21",
            "status": (
                "FACT: cover-page common shares outstanding. It is not a GAAP "
                "diluted weighted-average share count, so the current per-share "
                "valuation is not fully diluted-evidence complete."
            ),
        },
        "golden_case_status": "NOT_READY",
        "closure_gaps": (
            "Matched TTM opening operating-capital balances are absent from frozen evidence.",
            (
                "A fully diluted share count suitable for intrinsic value per share "
                "is absent from frozen evidence."
            ),
        ),
        "capital_market_snapshot_date": "2026-09-04",
        "market_price": frozen_market.price,
        "data_quality_warnings": (
            "Market price is frozen external evidence; WACC inputs and the 18% operating tax rate "
            "are analyst assumptions. NVDA valuation golden outputs are not accepted "
            "pending closure gaps."
        ),
    }


def nvda_audit(repository_root: str | Path = ".") -> dict[str, object]:
    """Return the period-aligned, evidence-complete NVDA financial-core record."""
    facts = load_facts(
        Path(repository_root) / "data/research/nvda/financial-evidence.json",
        repository_root,
        as_of=NVDA_AS_OF,
    )
    _require_reconciled(facts)
    snapshot = _accounting_snapshot(facts)
    frozen_market = load_market_snapshot(
        Path(repository_root) / "data/research/nvda/market-2026-09-04.json"
    )
    assert snapshot.valuation_shares is not None and snapshot.invested_capital is not None
    opening_nwc = 27_808 + 14_962 - 9_064 - 15_193
    closing_nwc = 63_059 + 31_575 - 15_059 - 26_960
    opening_assets, closing_assets = 9_141 + 755, 14_285 + 2_998
    opening_capital, closing_capital = opening_nwc + opening_assets, closing_nwc + closing_assets
    liquid_assets = 22_443 + 34_143 + 42_783
    equity_value = frozen_market.price * snapshot.valuation_shares
    return {
        "evidence_as_of": NVDA_AS_OF.isoformat(),
        "latest_filing": facts["cash_q2fy27"].filing.accession_number,
        "ttm_period": "2025-07-28 to 2026-07-26; opening balance sheet 2025-07-27",
        "ttm_formula": "FY2026 - H1 FY2026 + H1 FY2027",
        "ttm_labels": ("FY", "Prior H1", "Current H1", "TTM"),
        "ttm_revenue_values": (215_938, 90_805, 177_837, 302_970),
        "ttm_ebit_values": (130_387, 50_078, 117_270, 197_579),
        "revenue": snapshot.revenue,
        "ebit": snapshot.ebit,
        "ttm_revenue_bridge": "215,938 - 90,805 + 177,837 = 302,970",
        "ttm_ebit_bridge": "130,387 - 50,078 + 117,270 = 197,579",
        "flow_period_compatibility": {
            "revenue": "FY2026 - H1 FY2026 + H1 FY2027, 2025-07-28 to 2026-07-26",
            "ebit": "same TTM window",
            "depreciation_amortization": "2,843 - 1,280 + 2,124 = 3,687",
            "capex": "6,042 - 3,122 + 4,434 = 7,354; positive cash-use convention",
            "nwc": "2025-07-27 opening balance sheet to 2026-07-26 closing balance sheet",
        },
        "operating_tax_basis": "ASSUMPTION: 18%; no normalized operating tax fact asserted",
        "operating_nwc": {
            "included_current_assets": ("accounts receivable", "inventory"),
            "included_current_liabilities": (
                "accounts payable",
                "accrued and other current liabilities",
            ),
            "excluded": (
                "cash",
                "marketable debt securities",
                "marketable equity securities",
                "prepaids",
                "debt",
                "goodwill",
                "lease assets/liabilities",
                "deferred tax assets",
                "other assets/liabilities",
            ),
            "opening": opening_nwc,
            "closing": closing_nwc,
            "change": closing_nwc - opening_nwc,
            "balance_window": "2025-07-27 to 2026-07-26 (TTM-aligned)",
            "ttm_compatible": True,
        },
        "opening_operating_nwc": opening_nwc,
        "closing_operating_nwc": closing_nwc,
        "change_operating_nwc": snapshot.change_in_working_capital,
        "invested_capital": {
            "included": {
                "opening_trade_nwc": opening_nwc,
                "opening_net_ppe_and_intangibles": opening_assets,
                "closing_trade_nwc": closing_nwc,
                "closing_net_ppe_and_intangibles": closing_assets,
            },
            "opening_net_operating_capital": opening_capital,
            "closing_net_operating_capital": closing_capital,
            "reported_average": snapshot.invested_capital,
            "average_treatment": (
                "simple average of 2025-07-27 and 2026-07-26 operating-capital endpoints"
            ),
            "excluded": (
                "cash",
                "marketable debt securities",
                "marketable equity securities",
                "debt",
                "goodwill",
                "leases",
                "prepaids",
                "deferred tax assets",
                "other assets/liabilities",
            ),
            "ttm_compatible": True,
        },
        "liquid_assets": {
            "cash": 22_443,
            "marketable_debt_securities": 34_143,
            "marketable_equity_securities": 42_783,
            "total": liquid_assets,
            "treatment": (
                "excluded from operating capital and included once in enterprise-to-equity bridge"
            ),
        },
        "market_enterprise_to_equity": {
            "enterprise_value": equity_value - liquid_assets + 33_366,
            "eligible_liquid_assets": liquid_assets,
            "debt": 33_366,
            "equity_value": equity_value,
        },
        "share_count": {
            "value": snapshot.valuation_shares,
            "unit": "million shares",
            "period": "six months ended 2026-07-26",
            "basis": snapshot.valuation_share_basis,
            "status": (
                "FACT: GAAP diluted weighted-average shares; used as a period-weighted "
                "valuation-share proxy, not represented as current fully diluted shares."
            ),
        },
        "golden_case_status": "READY",
        "closure_gaps": (),
        "capital_market_snapshot_date": "2026-09-04",
        "market_price": frozen_market.price,
        "data_quality_warnings": (
            "Market price is frozen external evidence; WACC inputs and the 18% operating tax "
            "rate are analyst assumptions.",
        ),
    }
