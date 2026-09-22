import pytest

from qhapaq_finance.diamond.archetypes import Archetype, score_archetypes
from qhapaq_finance.diamond.scoring import CategoryScores


def test_exact_archetype_formulas() -> None:
    categories = CategoryScores(quality=80.0, growth=70.0, capital=60.0, price=50.0)
    result = score_archetypes(categories, margin_trend_percentile=90.0)
    assert result.compounder == pytest.approx(0.45 * 80 + 0.35 * 70 + 0.20 * 60)
    assert result.quality_value == pytest.approx(0.40 * 80 + 0.35 * 50 + 0.25 * 60)
    assert result.inflection == pytest.approx(0.35 * 70 + 0.25 * 80 + 0.20 * 90 + 0.20 * 50)
    assert result.research_priority == max(
        result.compounder, result.quality_value, result.inflection
    )


def test_tie_break_is_deterministically_compounder_first() -> None:
    categories = CategoryScores(quality=50.0, growth=50.0, capital=50.0, price=50.0)
    result = score_archetypes(categories, margin_trend_percentile=50.0)
    assert result.compounder == pytest.approx(50.0)
    assert result.quality_value == pytest.approx(50.0)
    assert result.inflection == pytest.approx(50.0)
    assert result.surfaced_by is Archetype.COMPOUNDER
