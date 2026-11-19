"""End-to-end offline Diamond Funnel evaluation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType

from .archetypes import ArchetypeScores, score_archetypes
from .contracts import FundamentalRecord, Methodology
from .metrics import CompressedMetrics, FinancialFeatureSet, derive_financial_features
from .percentiles import (
    DEFAULT_PERCENTILE_POLICY,
    Direction,
    FeatureDefinition,
    PercentilePolicy,
    compute_percentiles,
    resolve_peer_context,
)
from .scoring import CategoryScores, score_categories
from .validation import validate_dataset, validate_record

SCHEMA_VERSION = "diamond-funnel-v1"

FEATURE_DEFINITIONS = (
    FeatureDefinition("roic_proxy", Direction.HIGHER_IS_BETTER),
    FeatureDefinition("normalized_fcf_margin", Direction.HIGHER_IS_BETTER),
    FeatureDefinition("cash_conversion", Direction.HIGHER_IS_BETTER),
    FeatureDefinition("margin_dispersion", Direction.LOWER_IS_BETTER),
    FeatureDefinition("fcf_margin_dispersion", Direction.LOWER_IS_BETTER),
    FeatureDefinition("revenue_cagr_5y", Direction.HIGHER_IS_BETTER),
    FeatureDefinition("revenue_cagr_3y", Direction.HIGHER_IS_BETTER),
    FeatureDefinition("fcf_margin_trend", Direction.HIGHER_IS_BETTER),
    FeatureDefinition("operating_margin_trend", Direction.HIGHER_IS_BETTER),
    FeatureDefinition("net_debt_to_operating_income", Direction.LOWER_IS_BETTER),
    FeatureDefinition("share_dilution_3y", Direction.LOWER_IS_BETTER),
    FeatureDefinition("recent_share_change", Direction.LOWER_IS_BETTER),
    FeatureDefinition("net_cash_indicator", Direction.HIGHER_IS_BETTER),
    FeatureDefinition("normalized_fcf_yield", Direction.HIGHER_IS_BETTER),
    FeatureDefinition("ebit_ev_yield", Direction.HIGHER_IS_BETTER),
)


@dataclass(frozen=True, slots=True)
class DiamondResult:
    schema_version: str
    ticker: str
    company_name: str
    sector: str | None
    data_as_of: date
    provider: str
    provider_identity: str | None
    methodology: Methodology
    peer_scope: str | None
    peer_count: int
    metrics: CompressedMetrics
    scores: CategoryScores
    archetypes: ArchetypeScores
    percentiles: Mapping[str, float | None]
    diagnostics: tuple[str, ...]
    coverage: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "percentiles", MappingProxyType(dict(self.percentiles)))
        object.__setattr__(self, "coverage", MappingProxyType(dict(self.coverage)))


def _feature_values(features: FinancialFeatureSet) -> dict[str, float | None]:
    analytical = features.features
    return {
        "roic_proxy": analytical.roic_proxy,
        "normalized_fcf_margin": analytical.normalized_fcf_margin,
        "cash_conversion": analytical.cash_conversion,
        "margin_dispersion": analytical.margin_dispersion,
        "fcf_margin_dispersion": analytical.fcf_margin_dispersion,
        "revenue_cagr_5y": analytical.revenue_cagr_5y,
        "revenue_cagr_3y": analytical.revenue_cagr_3y,
        "fcf_margin_trend": analytical.fcf_margin_trend,
        "operating_margin_trend": analytical.operating_margin_trend,
        "net_debt_to_operating_income": analytical.net_debt_to_operating_income,
        "share_dilution_3y": features.metrics.share_dilution_3y,
        "recent_share_change": analytical.recent_share_change,
        "net_cash_indicator": analytical.net_cash_indicator,
        "normalized_fcf_yield": features.metrics.normalized_fcf_yield,
        "ebit_ev_yield": analytical.ebit_ev_yield,
    }


def _empty_categories() -> CategoryScores:
    return CategoryScores(None, None, None, None)


def _empty_archetypes() -> ArchetypeScores:
    return ArchetypeScores(None, None, None, None, None)


def evaluate_universe(
    records: tuple[FundamentalRecord, ...],
    *,
    policy: PercentilePolicy = DEFAULT_PERCENTILE_POLICY,
) -> tuple[DiamondResult, ...]:
    validate_dataset(records)
    feature_sets = {record.ticker: derive_financial_features(record) for record in records}
    values_by_ticker = {
        ticker: _feature_values(features) for ticker, features in feature_sets.items()
    }
    percentile_results = compute_percentiles(
        records,
        values_by_ticker,
        FEATURE_DEFINITIONS,
        policy,
    )

    results: list[DiamondResult] = []
    for record in records:
        features = feature_sets[record.ticker]
        peer_context = resolve_peer_context(records, record, policy)
        percentile_map = {
            name: result.percentile for name, result in percentile_results[record.ticker].items()
        }
        diagnostics = set(validate_record(record))
        diagnostics.update(features.diagnostics)
        diagnostics.update(peer_context.diagnostics)
        for result in percentile_results[record.ticker].values():
            diagnostics.update(result.diagnostics)

        market_fresh = (
            record.market_age_trading_days is not None and record.market_age_trading_days <= 3
        )
        if not market_fresh:
            diagnostics.add("MARKET_DATA_STALE")

        if (
            record.methodology is not Methodology.OPERATING_COMPANY
            or "FUNDAMENTALS_STALE" in diagnostics
        ):
            categories = _empty_categories()
            archetypes = _empty_archetypes()
        else:
            categories = score_categories(features, percentile_map, market_fresh=market_fresh)
            archetypes = score_archetypes(
                categories,
                margin_trend_percentile=percentile_map.get("operating_margin_trend"),
            )

        coverage: dict[str, str] = {}
        for name in ("quality", "growth", "capital", "price"):
            score = getattr(categories, name)
            if name == "price" and not market_fresh:
                coverage[name] = "MARKET_DATA_STALE"
            else:
                coverage[name] = "READY" if score is not None else "INSUFFICIENT_DATA"

        results.append(
            DiamondResult(
                SCHEMA_VERSION,
                record.ticker,
                record.company_name,
                record.sector,
                record.data_as_of,
                record.provider,
                record.provider_identity,
                record.methodology,
                peer_context.scope,
                peer_context.count,
                features.metrics,
                categories,
                archetypes,
                percentile_map,
                tuple(sorted(diagnostics)),
                coverage,
            )
        )
    return tuple(results)
