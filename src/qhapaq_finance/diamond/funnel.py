"""Provider-neutral orchestration for Diamond Funnel discovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from time import perf_counter

from .dataset_identity import dataset_identity
from .engine import DiamondResult, evaluate_universe
from .providers.protocol import FundamentalDataProvider


@dataclass(frozen=True, slots=True)
class FunnelRunMetadata:
    universe_count: int
    canonical_records: int
    ranked_records: int
    unranked_records: int
    provider_requests: int
    cache_hits: int
    cache_misses: int
    acquisition_seconds: float
    evaluation_seconds: float
    dataset_identity: str


@dataclass(frozen=True, slots=True)
class FunnelRun:
    results: tuple[DiamondResult, ...]
    metadata: FunnelRunMetadata


def _ranked(
    results: tuple[DiamondResult, ...],
) -> list[DiamondResult]:
    return sorted(
        results,
        key=lambda item: (
            item.archetypes.research_priority is None,
            -(item.archetypes.research_priority or 0.0),
            item.ticker,
        ),
    )


def _counter(provider: object, name: str) -> int:
    value = getattr(provider, name, 0)
    return value if isinstance(value, int) else 0


def run_funnel(
    provider: FundamentalDataProvider,
    *,
    universe_id: str,
    as_of: date,
    depth: int,
) -> FunnelRun:
    if depth < 1:
        raise ValueError("depth must be positive")

    requests_before = _counter(
        provider,
        "provider_requests",
    )
    hits_before = _counter(provider, "cache_hits")
    misses_before = _counter(provider, "cache_misses")

    acquisition_started = perf_counter()
    securities = provider.universe(
        universe_id,
        as_of,
    )
    records = provider.fundamentals(
        securities,
        as_of,
    )
    acquisition_seconds = perf_counter() - acquisition_started

    evaluation_started = perf_counter()
    evaluated = evaluate_universe(records)
    ranked = _ranked(evaluated)
    evaluation_seconds = perf_counter() - evaluation_started

    rankable = sum(item.archetypes.research_priority is not None for item in evaluated)

    return FunnelRun(
        results=tuple(ranked[:depth]),
        metadata=FunnelRunMetadata(
            universe_count=len(securities),
            canonical_records=len(records),
            ranked_records=rankable,
            unranked_records=len(evaluated) - rankable,
            provider_requests=(
                _counter(
                    provider,
                    "provider_requests",
                )
                - requests_before
            ),
            cache_hits=(_counter(provider, "cache_hits") - hits_before),
            cache_misses=(_counter(provider, "cache_misses") - misses_before),
            acquisition_seconds=acquisition_seconds,
            evaluation_seconds=evaluation_seconds,
            dataset_identity=dataset_identity(records),
        ),
    )
