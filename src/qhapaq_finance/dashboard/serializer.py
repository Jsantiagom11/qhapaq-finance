"""Stable, presentation-only JSON contract for deterministic research cases."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..evidence import EvidenceKind, load_facts
from ..qcom_case import QCOM_AS_OF, qcom_audit
from ..sensitivity import sensitivity_matrices
from ..valuation import ResearchResult, analyze_case, load_fixture_case

COMPANY_NAMES = {
    "QCOM": "QUALCOMM Incorporated",
    "VRTX": "Vertex Pharmaceuticals",
    "CSCO": "Cisco Systems",
}


def _scenario(result: ResearchResult, name: str) -> dict[str, Any]:
    valuation = next(item for item in result.scenarios if item.name == name)
    assumptions = next(item for item in result.case.scenarios if item.name == name)
    return {
        "name": name.upper(),
        "intrinsic_value": valuation.intrinsic_value_per_share,
        "margin_of_safety": valuation.margin_of_safety,
        "explicit_growth": assumptions.explicit_growth,
        "terminal_growth": assumptions.terminal_growth,
        "wacc": result.case.capital_cost.wacc,
        "terminal_value_share": valuation.terminal_value_share,
        "terminal_spread": valuation.terminal_spread,
        "pv_explicit_period": valuation.pv_explicit_period,
        "pv_terminal_value": valuation.pv_terminal_value,
        "warnings": list(valuation.warnings),
    }


def _qcom_provenance(repository_root: str | Path) -> list[dict[str, Any]]:
    facts = load_facts(
        Path(repository_root) / "data/research/qcom/financial-evidence.json",
        repository_root,
        as_of=QCOM_AS_OF,
    )
    records: list[dict[str, Any]] = []
    for fact in facts.values():
        records.append(
            {
                "fact_id": fact.id,
                "metric": fact.concept,
                "value": fact.value,
                "unit": fact.unit,
                "classification": EvidenceKind.FACT.value,
                "period": f"{fact.fiscal_period} ended {fact.period_end.isoformat()}",
                "filing_accession": fact.filing.accession_number,
                "concept_tag": fact.method.split(";", maxsplit=1)[0],
                "selection_method": fact.method,
            }
        )
    return records


def build_company_artifact(ticker: str, repository_root: str | Path = ".") -> dict[str, Any]:
    """Serialize an already-valued ResearchResult without valuation recomputation."""
    result = analyze_case(load_fixture_case(ticker, repository_root))
    case, market, cost = result.case, result.case.market_snapshot, result.case.capital_cost
    scenarios = {name.lower(): _scenario(result, name) for name in ("bear", "base", "bull")}
    fixture = case.ticker != "QCOM"
    audit: dict[str, Any] = qcom_audit(repository_root) if not fixture else {}
    base = scenarios["base"]
    liquid_assets = market.liquid_assets
    artifact: dict[str, Any] = {
        "schema_version": "dashboard-research-v1",
        "identity": {
            "ticker": case.ticker,
            "company_name": COMPANY_NAMES[case.ticker],
            "status": "RESEARCH" if not fixture else "FIXTURE",
            "classification": "fixture" if fixture else "evidence-backed",
            "research_as_of": case.as_of_date.isoformat(),
            "latest_filing_accession": None if fixture else audit["latest_filing"],
            "market_snapshot_date": None if fixture else audit["capital_market_snapshot_date"],
        },
        "market": {
            "price": market.price,
            "market_equity": market.equity_value,
            "enterprise_value": market.enterprise_value,
        },
        "economics": {
            "revenue_ttm": audit.get("revenue"),
            "ebit_ttm": audit.get("ebit"),
            "ebit_margin": None
            if audit.get("revenue") is None
            else audit["ebit"] / audit["revenue"],
            "nopat": result.nopat,
            "normalized_fcff": result.normalized_fcff,
            "fcff_margin": None
            if audit.get("revenue") is None
            else result.normalized_fcff / audit["revenue"],
            "invested_capital": case.invested_capital,
            "roic": result.roic,
            "wacc": cost.wacc,
            "roic_minus_wacc": result.roic - cost.wacc,
            "fcff_yield": result.normalized_fcff / market.enterprise_value,
        },
        "valuation": {
            "scenarios": scenarios,
            "fcff_implied_discount_rate": result.fcff_implied_discount_rate,
            "reverse_dcf_implied_growth": result.reverse_implied_growth,
            "expectations": {
                "growth_difference_pp": result.reverse_implied_growth - base["explicit_growth"],
                "discount_rate_difference_pp": result.fcff_implied_discount_rate - cost.wacc,
            },
        },
        "buy_zone": {
            "fair_value": base["intrinsic_value"],
            "price_at_10_mos": base["intrinsic_value"] * 0.90,
            "price_at_20_mos": base["intrinsic_value"] * 0.80,
            "price_at_25_mos": base["intrinsic_value"] * 0.75,
            "price_at_30_mos": base["intrinsic_value"] * 0.70,
        },
        "decision_zones": {
            "current_price": market.price,
            "fair_value": base["intrinsic_value"],
            "mos_10": base["intrinsic_value"] * 0.90,
            "mos_20": base["intrinsic_value"] * 0.80,
            "mos_25": base["intrinsic_value"] * 0.75,
            "mos_30": base["intrinsic_value"] * 0.70,
            "classification": (
                "ABOVE FAIR VALUE"
                if market.price > base["intrinsic_value"]
                else "FAIR-VALUE ZONE"
                if market.price == base["intrinsic_value"]
                else "WATCH ZONE"
            ),
        },
        "decision": {
            "status": "RESEARCH" if not fixture else "FIXTURE",
            "interpretation": case.provenance,
            "thesis": list(case.thesis),
            "invalidation_conditions": list(case.invalidation_conditions),
            "research_gaps": ["No detailed multi-stage forecast or maintenance-capex split."],
            "risks": list(case.risk_notes),
            "data_quality_warnings": (
                [audit["data_quality_warnings"]]
                if not fixture
                else ["Illustrative fixture; not filing-derived."]
            ),
        },
        "bridges": {
            "ttm": None
            if fixture
            else {
                "formula": "TTM = FY - prior 9M + current 9M",
                "revenue": [44284, 33013, 32798, 44069],
                "ebit": [12355, 9437, 7302, 10220],
            },
            "fcff": {
                "ebit": case.financial_inputs.ebit,
                "tax_rate": case.financial_inputs.tax_rate,
                "nopat": result.nopat,
                "da": case.financial_inputs.depreciation_amortization,
                "capex": case.financial_inputs.capex,
                "change_nwc": case.financial_inputs.change_in_nwc,
                "reconstructed_fcff": result.reconstructed_fcff,
                "normalization_adjustments": sum(
                    item.amount for item in case.normalization_adjustments
                ),
                "normalized_fcff": result.normalized_fcff,
            },
            "operating_nwc": None
            if fixture
            else {
                "opening": audit["opening_operating_nwc"],
                "closing": audit["closing_operating_nwc"],
                "change": audit["change_operating_nwc"],
            },
            "liquidity": {
                "cash": market.cash_and_equivalents,
                "marketable_securities": market.marketable_securities,
            },
            "debt": market.debt,
            "senior_claims": market.other_senior_claims,
            "enterprise_to_equity": {
                "enterprise_value": market.enterprise_value,
                "liquid_assets": liquid_assets,
                "debt": market.debt,
                "senior_claims": market.other_senior_claims,
                "equity_value": market.equity_value,
                "shares": market.shares_outstanding,
            },
        },
        "provenance": [] if fixture else _qcom_provenance(repository_root),
        "sensitivity": sensitivity_matrices(case),
    }
    return artifact


def build_universe_artifact(
    tickers: tuple[str, ...], repository_root: str | Path = "."
) -> dict[str, Any]:
    companies = [build_company_artifact(ticker, repository_root) for ticker in tickers]
    return {
        "schema_version": "dashboard-universe-v1",
        "research_as_of": max(item["identity"]["research_as_of"] for item in companies),
        "companies": companies,
    }


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def write_artifacts(
    tickers: tuple[str, ...], output_dir: str | Path, repository_root: str | Path = "."
) -> dict[str, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    universe = build_universe_artifact(tickers, repository_root)
    written = {"universe": directory / "universe_summary.json"}
    written["universe"].write_text(canonical_json(universe), encoding="utf-8")
    for company in universe["companies"]:
        ticker = company["identity"]["ticker"].lower()
        path = directory / f"{ticker}_research.json"
        path.write_text(canonical_json(company), encoding="utf-8")
        written[ticker] = path
        if company["provenance"]:
            provenance = directory / f"{ticker}_provenance.json"
            provenance.write_text(
                canonical_json({"records": company["provenance"]}), encoding="utf-8"
            )
            written[f"{ticker}_provenance"] = provenance
    return written
