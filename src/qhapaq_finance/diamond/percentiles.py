"""Robust peer formation, winsorization, and deterministic percentile ranks."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from qhapaq_finance.string_enum import StringEnum

from .contracts import FundamentalRecord
from .validation import record_eligible_for_scoring


class Direction(StringEnum):
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"


@dataclass(frozen=True, slots=True)
class PercentilePolicy:
    primary_peer_minimum: int = 20
    feature_observation_minimum: int = 8
    winsor_lower: float = 0.05
    winsor_upper: float = 0.95
    soft_period_spread_days: int = 45
    hard_period_spread_days: int = 92

    def __post_init__(self) -> None:
        if self.primary_peer_minimum < 1 or self.feature_observation_minimum < 2:
            raise ValueError("PERCENTILE_POLICY_COUNT_INVALID")
        if not 0 <= self.winsor_lower < self.winsor_upper <= 1:
            raise ValueError("PERCENTILE_POLICY_WINSOR_INVALID")
        if not 0 <= self.soft_period_spread_days <= self.hard_period_spread_days:
            raise ValueError("PERCENTILE_POLICY_PERIOD_SPREAD_INVALID")


DEFAULT_PERCENTILE_POLICY = PercentilePolicy()


@dataclass(frozen=True, slots=True)
class FeatureDefinition:
    name: str
    direction: Direction


@dataclass(frozen=True, slots=True)
class PeerContext:
    scope: str
    count: int
    records: tuple[FundamentalRecord, ...]
    diagnostics: tuple[str, ...]
    blocked: bool


@dataclass(frozen=True, slots=True)
class PercentileResult:
    percentile: float | None
    original_value: float | None
    scored_value: float | None
    peer_scope: str
    peer_count: int
    diagnostics: tuple[str, ...]


def linear_winsor_bounds(
    values: tuple[float, ...], policy: PercentilePolicy = DEFAULT_PERCENTILE_POLICY
) -> tuple[float, float]:
    if not values or any(not math.isfinite(item) for item in values):
        raise ValueError("WINSOR_VALUES_INVALID")
    array = np.asarray(values, dtype=float)
    lower = float(np.quantile(array, policy.winsor_lower, method="linear"))
    upper = float(np.quantile(array, policy.winsor_upper, method="linear"))
    return lower, upper


def empirical_percentile(values: tuple[float, ...], target: float, direction: Direction) -> float:
    if not values or not math.isfinite(target) or any(not math.isfinite(item) for item in values):
        raise ValueError("PERCENTILE_VALUES_INVALID")
    n = len(values)
    if n == 1:
        base = 50.0
    else:
        sorted_values = sorted(values)
        matching = [index + 1 for index, item in enumerate(sorted_values) if item == target]
        if not matching:
            raise ValueError("PERCENTILE_TARGET_NOT_IN_SAMPLE")
        average_rank = sum(matching) / len(matching)
        base = (average_rank - 1.0) / (n - 1.0) * 100.0
    return base if direction is Direction.HIGHER_IS_BETTER else 100.0 - base


def resolve_peer_context(
    records: tuple[FundamentalRecord, ...],
    target: FundamentalRecord,
    policy: PercentilePolicy = DEFAULT_PERCENTILE_POLICY,
) -> PeerContext:
    eligible = tuple(record for record in records if record_eligible_for_scoring(record))
    primary = tuple(record for record in eligible if record.peer_group_id == target.peer_group_id)
    if len(primary) >= policy.primary_peer_minimum:
        selected = primary
        scope = target.peer_group_id
    else:
        selected = eligible
        scope = "ELIGIBLE_UNIVERSE"
    if not selected:
        return PeerContext(scope, 0, (), ("INSUFFICIENT_PEER_SET",), True)
    period_ends = [record.fundamental_period_end for record in selected]
    spread = (max(period_ends) - min(period_ends)).days
    diagnostics: list[str] = []
    blocked = False
    if spread > policy.hard_period_spread_days:
        diagnostics.append("PEER_PERIOD_MISALIGNED")
        blocked = True
    elif spread > policy.soft_period_spread_days:
        diagnostics.append("PEER_PERIOD_DRIFT")
    return PeerContext(scope, len(selected), selected, tuple(diagnostics), blocked)


def compute_percentiles(
    records: tuple[FundamentalRecord, ...],
    values_by_ticker: Mapping[str, Mapping[str, float | None]],
    definitions: tuple[FeatureDefinition, ...],
    policy: PercentilePolicy = DEFAULT_PERCENTILE_POLICY,
) -> dict[str, dict[str, PercentileResult]]:
    output: dict[str, dict[str, PercentileResult]] = {}
    for record in records:
        record_output: dict[str, PercentileResult] = {}
        context = resolve_peer_context(records, record, policy)
        for definition in definitions:
            original = values_by_ticker.get(record.ticker, {}).get(definition.name)
            diagnostics = list(context.diagnostics)
            if not record_eligible_for_scoring(record):
                diagnostics.append("UNSUPPORTED_OR_STALE_RECORD")
                record_output[definition.name] = PercentileResult(
                    None,
                    original,
                    None,
                    context.scope,
                    context.count,
                    tuple(sorted(set(diagnostics))),
                )
                continue
            if context.blocked:
                record_output[definition.name] = PercentileResult(
                    None,
                    original,
                    None,
                    context.scope,
                    context.count,
                    tuple(sorted(set(diagnostics))),
                )
                continue
            peer_values = [
                values_by_ticker.get(peer.ticker, {}).get(definition.name)
                for peer in context.records
            ]
            finite_values = tuple(
                float(item)
                for item in peer_values
                if item is not None and math.isfinite(float(item))
            )
            if len(finite_values) < policy.feature_observation_minimum:
                diagnostics.append("INSUFFICIENT_PEER_OBSERVATIONS")
                record_output[definition.name] = PercentileResult(
                    None,
                    original,
                    None,
                    context.scope,
                    context.count,
                    tuple(sorted(set(diagnostics))),
                )
                continue
            if original is None or not math.isfinite(float(original)):
                record_output[definition.name] = PercentileResult(
                    None,
                    original,
                    None,
                    context.scope,
                    context.count,
                    tuple(sorted(set(diagnostics))),
                )
                continue
            lower, upper = linear_winsor_bounds(finite_values, policy)
            scored_sample = tuple(min(max(item, lower), upper) for item in finite_values)
            scored_target = min(max(float(original), lower), upper)
            percentile = empirical_percentile(scored_sample, scored_target, definition.direction)
            record_output[definition.name] = PercentileResult(
                percentile,
                float(original),
                scored_target,
                context.scope,
                context.count,
                tuple(sorted(set(diagnostics))),
            )
        output[record.ticker] = record_output
    return output
