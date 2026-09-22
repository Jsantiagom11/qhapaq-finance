"""Stable JSON and CSV projections for Diamond Funnel results."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict

from .engine import SCHEMA_VERSION, DiamondResult

METRIC_KEYS = (
    "revenue_ttm",
    "operating_income_ttm",
    "operating_margin_ttm",
    "operating_cash_flow_ttm",
    "capex_ttm",
    "fcf_ttm",
    "fcf_margin_ttm",
    "cash_and_marketable_securities",
    "total_debt",
    "net_debt",
    "diluted_shares",
    "share_dilution_3y",
    "market_cap",
    "enterprise_value",
    "normalized_fcf_yield",
)

CSV_COLUMNS = (
    "ticker",
    "company_name",
    "data_as_of",
    "methodology",
    "peer_scope",
    "peer_count",
    *METRIC_KEYS,
    "quality",
    "growth",
    "capital",
    "price",
    "compounder",
    "quality_value",
    "inflection",
    "research_priority",
    "surfaced_by",
    "diagnostics",
)


def _ordered_results(results: tuple[DiamondResult, ...]) -> list[DiamondResult]:
    return sorted(
        results,
        key=lambda item: (
            item.archetypes.research_priority is None,
            -(item.archetypes.research_priority or 0.0),
            item.ticker,
        ),
    )


def diamond_result_dict(result: DiamondResult) -> dict[str, object]:
    metrics = asdict(result.metrics)
    if tuple(metrics) != METRIC_KEYS:
        raise ValueError("DIAMOND_METRIC_SCHEMA_DRIFT")
    scores = {
        "quality": result.scores.quality,
        "growth": result.scores.growth,
        "capital": result.scores.capital,
        "price": result.scores.price,
        "compounder": result.archetypes.compounder,
        "quality_value": result.archetypes.quality_value,
        "inflection": result.archetypes.inflection,
        "research_priority": result.archetypes.research_priority,
    }
    return {
        "schema_version": result.schema_version,
        "ticker": result.ticker,
        "company_name": result.company_name,
        "sector": result.sector,
        "data_as_of": result.data_as_of.isoformat(),
        "provider": result.provider,
        "provider_identity": result.provider_identity,
        "methodology": result.methodology.value,
        "peer_scope": result.peer_scope,
        "peer_count": result.peer_count,
        "metrics": metrics,
        "scores": scores,
        "surfaced_by": (
            result.archetypes.surfaced_by.value if result.archetypes.surfaced_by else None
        ),
        "percentiles": dict(result.percentiles),
        "diagnostics": list(result.diagnostics),
        "coverage": dict(result.coverage),
    }


def canonical_diamond_json(results: tuple[DiamondResult, ...]) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "results": [diamond_result_dict(item) for item in _ordered_results(results)],
    }
    return (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )


def diamond_csv(results: tuple[DiamondResult, ...]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for result in _ordered_results(results):
        metrics = asdict(result.metrics)
        row: dict[str, object] = {
            "ticker": result.ticker,
            "company_name": result.company_name,
            "data_as_of": result.data_as_of.isoformat(),
            "methodology": result.methodology.value,
            "peer_scope": result.peer_scope,
            "peer_count": result.peer_count,
            **metrics,
            "quality": result.scores.quality,
            "growth": result.scores.growth,
            "capital": result.scores.capital,
            "price": result.scores.price,
            "compounder": result.archetypes.compounder,
            "quality_value": result.archetypes.quality_value,
            "inflection": result.archetypes.inflection,
            "research_priority": result.archetypes.research_priority,
            "surfaced_by": (
                result.archetypes.surfaced_by.value if result.archetypes.surfaced_by else ""
            ),
            "diagnostics": "|".join(result.diagnostics),
        }
        writer.writerow(row)
    return stream.getvalue()
