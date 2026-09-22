"""Multiple research archetypes avoid the perfect-company conjunction."""

from __future__ import annotations

from dataclasses import dataclass

from qhapaq_finance.string_enum import StringEnum

from .scoring import CategoryScores


class Archetype(StringEnum):
    COMPOUNDER = "COMPOUNDER"
    QUALITY_VALUE = "QUALITY_VALUE"
    INFLECTION = "INFLECTION"


@dataclass(frozen=True, slots=True)
class ArchetypeScores:
    compounder: float | None
    quality_value: float | None
    inflection: float | None
    research_priority: float | None
    surfaced_by: Archetype | None


def _complete_weighted(values: tuple[tuple[float | None, float], ...]) -> float | None:
    if any(value is None for value, _ in values):
        return None
    return sum(float(value) * weight for value, weight in values if value is not None)


def score_archetypes(
    categories: CategoryScores,
    *,
    margin_trend_percentile: float | None,
) -> ArchetypeScores:
    compounder = _complete_weighted(
        ((categories.quality, 0.45), (categories.growth, 0.35), (categories.capital, 0.20))
    )
    quality_value = _complete_weighted(
        ((categories.quality, 0.40), (categories.price, 0.35), (categories.capital, 0.25))
    )
    inflection = _complete_weighted(
        (
            (categories.growth, 0.35),
            (categories.quality, 0.25),
            (margin_trend_percentile, 0.20),
            (categories.price, 0.20),
        )
    )
    ordered = (
        (Archetype.COMPOUNDER, compounder),
        (Archetype.QUALITY_VALUE, quality_value),
        (Archetype.INFLECTION, inflection),
    )
    available = [(kind, score) for kind, score in ordered if score is not None]
    if not available:
        return ArchetypeScores(compounder, quality_value, inflection, None, None)
    best_score = max(float(score) for _, score in available if score is not None)
    surfaced_by = next(kind for kind, score in available if float(score) == best_score)
    return ArchetypeScores(compounder, quality_value, inflection, best_score, surfaced_by)
