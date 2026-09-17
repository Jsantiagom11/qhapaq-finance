"""Stable, presentation-only JSON contract for deterministic research cases."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from ..evidence import EvidenceKind, load_facts
from ..explainability import explainability_contract
from ..research_result import build_canonical_research_result
from ..sensitivity import sensitivity_matrices
from ..universe import DomainRegistry
from ..valuation import load_fixture_case, price_value_classification, valuation_cushion_prices


def _evidence_provenance(
    repository_root: str | Path, evidence_path: Path, as_of: object
) -> list[dict[str, Any]]:
    facts = load_facts(
        Path(repository_root) / evidence_path,
        repository_root,
        as_of=as_of,  # type: ignore[arg-type]
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
    """Create the dashboard projection of the canonical research result.

    Display-only bridges and sensitivity remain here, but identity, readiness,
    provenance, and valuation truth are sourced from ``research-result-v1``.
    """
    canonical = build_canonical_research_result(ticker, repository_root)
    registry = DomainRegistry(repository_root)
    security = registry.security(ticker)
    case = load_fixture_case(ticker, repository_root)
    market, cost = case.market_snapshot, case.capital_cost
    canonical_scenarios = cast(dict[str, dict[str, object]], canonical.valuation["scenarios"])
    scenarios = {
        name: {
            "name": name.upper(),
            "intrinsic_value": value["intrinsic_value_per_share"],
            "margin_of_safety": value["margin_of_safety"],
            "explicit_growth": value["explicit_growth"],
            "terminal_growth": value["terminal_growth"],
            "wacc": canonical.valuation["wacc"],
            "terminal_value_share": value["terminal_value_share"],
            "terminal_spread": value["terminal_spread"],
            "pv_explicit_period": value["pv_explicit_period"],
            "pv_terminal_value": value["pv_terminal_value"],
            "warnings": value["warnings"],
        }
        for name, value in canonical_scenarios.items()
    }
    support = registry.audit(case.ticker)
    fixture = support is None
    audit: dict[str, Any] = support[2](repository_root) if support is not None else {}  # type: ignore[operator]
    base = scenarios["base"]
    liquid_assets = market.liquid_assets
    fair_value = cast(float, base["intrinsic_value"])
    cushion_prices = valuation_cushion_prices(fair_value)
    artifact: dict[str, Any] = {
        "schema_version": "dashboard-research-v1",
        "canonical_result_identity": canonical.content_identity,
        "identity": {
            "ticker": case.ticker,
            "company_name": registry.issuer_for(security.ticker).display_name,
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
            "provenance": case.market_provenance.to_dict()
            if case.market_provenance is not None
            else {"source_mode": "fixture" if fixture else "legacy"},
        },
        "economics": {
            "revenue_ttm": audit.get("revenue"),
            "ebit_ttm": audit.get("ebit"),
            "nopat": canonical.valuation["nopat"],
            "normalized_fcff": canonical.valuation["normalized_fcff"],
            "invested_capital": case.invested_capital,
            "roic": canonical.valuation["roic"],
            "wacc": canonical.valuation["wacc"],
            "roic_minus_wacc": canonical.valuation["roic_minus_wacc"],
            "fcff_yield": canonical.valuation["fcff_yield"],
        },
        "valuation": {
            "scenarios": scenarios,
            "fcff_implied_discount_rate": canonical.market_comparison["fcff_implied_discount_rate"],
            "reverse_dcf_implied_growth": canonical.reverse_valuation["implied_growth"],
            "expectations": {
                "growth_difference_pp": canonical.reverse_valuation["expectation_growth_gap"],
                "discount_rate_difference_pp": cast(
                    float, canonical.market_comparison["fcff_implied_discount_rate"]
                )
                - cost.wacc,
            },
        },
        "buy_zone": {
            "fair_value": fair_value,
            "price_at_10_mos": cushion_prices["mos_10"],
            "price_at_20_mos": cushion_prices["mos_20"],
            "price_at_25_mos": cushion_prices["mos_25"],
            "price_at_30_mos": cushion_prices["mos_30"],
        },
        "decision_zones": {
            "current_price": market.price,
            "fair_value": fair_value,
            **cushion_prices,
            "classification": price_value_classification(market.price, fair_value),
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
                "formula": audit["ttm_formula"],
                "labels": audit["ttm_labels"],
                "revenue": audit["ttm_revenue_values"],
                "ebit": audit["ttm_ebit_values"],
            },
            "fcff": {
                "ebit": case.financial_inputs.ebit,
                "tax_rate": case.financial_inputs.tax_rate,
                "nopat": canonical.valuation["nopat"],
                "da": case.financial_inputs.depreciation_amortization,
                "capex": case.financial_inputs.capex,
                "change_nwc": case.financial_inputs.change_in_nwc,
                "reconstructed_fcff": canonical.valuation["reconstructed_fcff"],
                "normalization_adjustments": sum(
                    item.amount for item in case.normalization_adjustments
                ),
                "normalized_fcff": canonical.valuation["normalized_fcff"],
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
        "provenance": (
            [] if support is None else _evidence_provenance(repository_root, support[0], support[1])
        ),
        "sensitivity": sensitivity_matrices(case),
    }
    # The dashboard has one deterministic artifact.  Explainability is a
    # semantic projection of it, not a novice-only second dataset.
    artifact["explainability"] = explainability_contract(artifact)
    # These values are deliberately projected, rather than independently
    # serialized domain semantics by the dashboard.
    artifact["identity"].update(
        {
            "ticker": canonical.security["ticker"],
            "company_name": canonical.issuer["display_name"],
            "research_as_of": canonical.research_as_of.isoformat(),
        }
    )
    artifact["market"].update(
        {
            "price": canonical.market_comparison["price"],
            "market_equity": canonical.market_comparison["market_equity"],
            "enterprise_value": canonical.market_comparison["enterprise_value"],
            "provenance": canonical.market_provenance.to_dict(),
        }
    )
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
