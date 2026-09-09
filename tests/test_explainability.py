"""Golden tests for the deterministic explainability projection."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from qhapaq_finance.dashboard import (
    FactStatus,
    build_company_artifact,
    build_research_narrative,
    build_semantic_facts,
    render_company_dashboard,
    validate_narrative,
)

ROOT = Path(__file__).parents[1]


def test_qcom_semantic_facts_are_deterministic_and_classified() -> None:
    artifact = build_company_artifact("QCOM", ROOT)
    facts = build_semantic_facts(artifact)
    by_id = {fact.id: fact for fact in facts}
    assert by_id["market_price"].status is FactStatus.FACT
    assert by_id["base_fair_value"].status is FactStatus.DERIVED_FACT
    assert by_id["roic_wacc_spread"].statement.endswith("13.4 pp.")
    assert by_id["market_price"].evidence_ids == tuple(
        item["fact_id"] for item in artifact["provenance"]
    )
    assert artifact["explainability"]["consistency"]["valid"]


def test_expectation_growth_difference_is_serialized_as_percentage_points() -> None:
    artifact = build_company_artifact("NVDA", ROOT)
    facts = {fact.id: fact for fact in build_semantic_facts(artifact)}
    statement = facts["expectations_gap"].statement
    assert " pp." in statement
    assert "%" not in statement


def test_qcom_golden_narrative_separates_business_quality_from_price() -> None:
    artifact = build_company_artifact("QCOM", ROOT)
    narrative = artifact["explainability"]["narrative"]
    assert "above" in narrative["valuation_argument"]["statement"].lower()
    assert "no valuation cushion" in narrative["valuation_argument"]["statement"].lower()
    assert "more on invested capital" in narrative["economic_quality_argument"]["statement"]
    assert "above" in narrative["expectations_argument"]["statement"].lower()
    assert narrative["fragility_argument"]["status"] == "INFERENCE"
    assert narrative["open_questions"][0]["status"] == "UNCERTAINTY"


def test_consistency_gate_rejects_typed_directional_contradictions() -> None:
    artifact = build_company_artifact("QCOM", ROOT)
    facts = build_semantic_facts(artifact)
    narrative = build_research_narrative(artifact, facts)
    invalid = replace(
        narrative,
        valuation_argument=replace(
            narrative.valuation_argument,
            statement="The current price is below Qhapaq's base fair value.",
        ),
        economic_quality_argument=replace(
            narrative.economic_quality_argument,
            statement="The business does not currently earn more on invested capital.",
        ),
        expectations_argument=replace(
            narrative.expectations_argument,
            statement="The market price implies growth at or below Qhapaq's base assumption.",
        ),
        fragility_argument=replace(
            narrative.fragility_argument,
            statement=(
                "Less than half of estimated value comes from cash flows beyond the forecast."
            ),
        ),
    )
    result = validate_narrative(invalid, facts)
    assert not result.valid
    assert len(result.failures) >= 4


def test_simple_and_research_views_embed_the_same_explainability_artifact(tmp_path: Path) -> None:
    artifact = build_company_artifact("QCOM", ROOT)
    page = render_company_dashboard(artifact, tmp_path / "qcom.html").read_text()
    assert 'data-view="simple"' in page
    assert "Simple view" in page and "Research view" in page
    assert "What Qhapaq believes" in page and "Evidence and provenance" in page
    assert "INTERPRETATION" not in page  # Simple label is humanized, classification is unchanged.
    assert "Interpretation" in page and "MARKET_PRICE" not in page
    assert "market_price" in page  # Research evidence retains technical fact access.
    assert "qhapaq-explainability-v1" in page
    assert "fetch(" not in page and "https://" not in page
