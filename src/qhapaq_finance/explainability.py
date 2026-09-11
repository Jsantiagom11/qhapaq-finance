"""Deterministic semantic facts, narrative contracts, and consistency checks.

This module deliberately sits after valuation and before presentation.  It does
not calculate a value, and it does not ask a model to decide what is a fact.
"""
# ruff: noqa: E501

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class FactStatus(str, Enum):
    FACT = "FACT"
    DERIVED_FACT = "DERIVED_FACT"
    INFERENCE = "INFERENCE"
    UNCERTAINTY = "UNCERTAINTY"


class ArgumentCategory(str, Enum):
    VALUATION = "VALUATION"
    ECONOMIC_QUALITY = "ECONOMIC_QUALITY"
    EXPECTATIONS = "EXPECTATIONS"
    FRAGILITY = "FRAGILITY"
    MUST_BE_TRUE = "MUST_BE_TRUE"
    COULD_BREAK = "COULD_BREAK"
    OPEN_QUESTION = "OPEN_QUESTION"


@dataclass(frozen=True)
class Fact:
    id: str
    topic: str
    statement: str
    evidence_ids: tuple[str, ...]
    status: FactStatus
    value: float | str | None = None
    unit: str | None = None

    def __post_init__(self) -> None:
        if not self.id or not self.topic or not self.statement:
            raise ValueError("semantic facts require id, topic, and statement")
        if not self.evidence_ids:
            raise ValueError("semantic facts require canonical evidence IDs")


@dataclass(frozen=True)
class ResearchArgument:
    category: ArgumentCategory
    statement: str
    evidence_ids: tuple[str, ...]
    status: FactStatus

    def __post_init__(self) -> None:
        if not self.statement or not self.evidence_ids:
            raise ValueError("research arguments require text and evidence IDs")
        if self.status not in (
            FactStatus.DERIVED_FACT,
            FactStatus.INFERENCE,
            FactStatus.UNCERTAINTY,
        ):
            raise ValueError("research arguments must be derived, inferred, or uncertain")


@dataclass(frozen=True)
class ResearchNarrative:
    headline: ResearchArgument
    plain_language_summary: ResearchArgument
    valuation_argument: ResearchArgument
    economic_quality_argument: ResearchArgument
    expectations_argument: ResearchArgument
    fragility_argument: ResearchArgument
    what_must_be_true: tuple[ResearchArgument, ...]
    what_could_break: tuple[ResearchArgument, ...]
    open_questions: tuple[ResearchArgument, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ConsistencyResult:
    valid: bool
    failures: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _pp(value: float) -> str:
    """Format a difference between rates as percentage points."""
    return f"{value * 100:.1f} pp"


def _numeric_value(fact: Fact) -> float:
    if isinstance(fact.value, bool) or not isinstance(fact.value, int | float):
        raise ValueError(f"{fact.id} must have a numeric value")
    return float(fact.value)


def build_semantic_facts(artifact: dict[str, Any]) -> tuple[Fact, ...]:
    """Classify deterministic artifact data into provider-independent facts."""
    market, economics, valuation = artifact["market"], artifact["economics"], artifact["valuation"]
    base = valuation["scenarios"]["base"]
    source_ids = tuple(item["fact_id"] for item in artifact["provenance"])
    source_ids = source_ids or ("deterministic_fixture",)
    facts = (
        Fact(
            "market_price",
            "price",
            f"Market price is ${market['price']:,.2f} per share.",
            source_ids,
            FactStatus.FACT,
            market["price"],
            "USD_PER_SHARE",
        ),
        Fact(
            "base_fair_value",
            "valuation",
            f"Base fair value is ${base['intrinsic_value']:,.2f} per share.",
            ("base_fair_value",),
            FactStatus.DERIVED_FACT,
            base["intrinsic_value"],
            "USD_PER_SHARE",
        ),
        Fact(
            "margin_of_safety",
            "valuation",
            f"Base margin of safety is {_pct(base['margin_of_safety'])}.",
            ("margin_of_safety",),
            FactStatus.DERIVED_FACT,
            base["margin_of_safety"],
            "RATIO",
        ),
        Fact(
            "roic",
            "economic_quality",
            f"ROIC is {_pct(economics['roic'])}.",
            ("roic",),
            FactStatus.DERIVED_FACT,
            economics["roic"],
            "RATIO",
        ),
        Fact(
            "wacc",
            "economic_quality",
            f"WACC is {_pct(economics['wacc'])}.",
            ("wacc",),
            FactStatus.DERIVED_FACT,
            economics["wacc"],
            "RATIO",
        ),
        Fact(
            "roic_wacc_spread",
            "economic_quality",
            f"ROIC exceeds WACC by {_pp(economics['roic_minus_wacc'])}.",
            ("roic_wacc_spread",),
            FactStatus.DERIVED_FACT,
            economics["roic_minus_wacc"],
            "RATIO",
        ),
        Fact(
            "market_implied_growth",
            "expectations",
            f"Market-implied FCFF growth is {_pct(valuation['reverse_dcf_implied_growth'])}.",
            ("market_implied_growth",),
            FactStatus.DERIVED_FACT,
            valuation["reverse_dcf_implied_growth"],
            "RATIO",
        ),
        Fact(
            "base_growth",
            "expectations",
            f"Base explicit FCFF growth is {_pct(base['explicit_growth'])}.",
            ("base_growth",),
            FactStatus.DERIVED_FACT,
            base["explicit_growth"],
            "RATIO",
        ),
        Fact(
            "expectations_gap",
            "expectations",
            f"Market-implied growth differs from base growth by {_pp(valuation['expectations']['growth_difference_pp'])}.",
            ("expectations_gap",),
            FactStatus.DERIVED_FACT,
            valuation["expectations"]["growth_difference_pp"],
            "RATIO",
        ),
        Fact(
            "terminal_value_share",
            "fragility",
            f"Terminal value represents {_pct(base['terminal_value_share'])} of base valuation.",
            ("terminal_value_share",),
            FactStatus.DERIVED_FACT,
            base["terminal_value_share"],
            "RATIO",
        ),
    )
    return facts


def build_research_narrative(
    artifact: dict[str, Any], facts: tuple[Fact, ...]
) -> ResearchNarrative:
    """Produce bounded, deterministic plain-language narrative from one artifact."""
    by_id = {fact.id: fact for fact in facts}
    price = _numeric_value(by_id["market_price"])
    fair = _numeric_value(by_id["base_fair_value"])
    spread = _numeric_value(by_id["roic_wacc_spread"])
    gap = _numeric_value(by_id["expectations_gap"])
    terminal = _numeric_value(by_id["terminal_value_share"])
    above = price > fair
    headline = (
        "Strong economics, but price is above base fair value"
        if above
        else "Price is below base fair value"
    )
    valuation = ResearchArgument(
        ArgumentCategory.VALUATION,
        "The current price is above Qhapaq's base value, so there is no valuation cushion under the base case."
        if above
        else "The current price is below Qhapaq's base value, so there is a valuation cushion under the base case.",
        ("market_price", "base_fair_value", "margin_of_safety"),
        FactStatus.INFERENCE,
    )
    economics = ResearchArgument(
        ArgumentCategory.ECONOMIC_QUALITY,
        "The business earns more on invested capital than Qhapaq estimates it costs to fund that capital."
        if spread > 0
        else "The business does not currently earn more on invested capital than its estimated funding cost.",
        ("roic", "wacc", "roic_wacc_spread"),
        FactStatus.INFERENCE,
    )
    expectations = ResearchArgument(
        ArgumentCategory.EXPECTATIONS,
        "The market price implies growth above Qhapaq's base assumption, so investors are paying for a stronger outcome."
        if gap > 0
        else "The market price implies growth at or below Qhapaq's base assumption.",
        ("market_implied_growth", "base_growth", "expectations_gap"),
        FactStatus.INFERENCE,
    )
    fragility = ResearchArgument(
        ArgumentCategory.FRAGILITY,
        "A meaningful share of estimated value comes from cash flows beyond the explicit forecast period."
        if terminal >= 0.50
        else "Less than half of estimated value comes from cash flows beyond the explicit forecast period.",
        ("terminal_value_share",),
        FactStatus.INFERENCE,
    )
    must = tuple(
        ResearchArgument(
            ArgumentCategory.MUST_BE_TRUE,
            item,
            ("roic_wacc_spread", "base_growth"),
            FactStatus.INFERENCE,
        )
        for item in artifact["decision"]["thesis"]
    )
    breaks = tuple(
        ResearchArgument(
            ArgumentCategory.COULD_BREAK,
            item,
            ("margin_of_safety", "terminal_value_share"),
            FactStatus.INFERENCE,
        )
        for item in artifact["decision"]["invalidation_conditions"]
    )
    questions = tuple(
        ResearchArgument(
            ArgumentCategory.OPEN_QUESTION, item, ("base_fair_value",), FactStatus.UNCERTAINTY
        )
        for item in artifact["decision"]["research_gaps"]
    )
    return ResearchNarrative(
        headline=ResearchArgument(
            ArgumentCategory.VALUATION, headline, valuation.evidence_ids, FactStatus.INFERENCE
        ),
        plain_language_summary=ResearchArgument(
            ArgumentCategory.VALUATION,
            "Qhapaq separates a good business from a good price: strong returns do not by themselves make the current share price attractive.",
            valuation.evidence_ids + economics.evidence_ids,
            FactStatus.INFERENCE,
        ),
        valuation_argument=valuation,
        economic_quality_argument=economics,
        expectations_argument=expectations,
        fragility_argument=fragility,
        what_must_be_true=must,
        what_could_break=breaks,
        open_questions=questions,
    )


_TOPICS = {
    ArgumentCategory.VALUATION: {"price", "valuation"},
    ArgumentCategory.ECONOMIC_QUALITY: {"economic_quality"},
    ArgumentCategory.EXPECTATIONS: {"expectations"},
    ArgumentCategory.FRAGILITY: {"fragility"},
    ArgumentCategory.MUST_BE_TRUE: {"economic_quality", "expectations"},
    ArgumentCategory.COULD_BREAK: {"valuation", "fragility"},
    ArgumentCategory.OPEN_QUESTION: {"valuation", "economic_quality", "expectations", "fragility"},
}


def validate_narrative(narrative: ResearchNarrative, facts: tuple[Fact, ...]) -> ConsistencyResult:
    """Check selected semantic contradictions, not unrestricted prose semantics."""
    by_id = {fact.id: fact for fact in facts}
    failures: list[str] = []
    all_arguments = (
        narrative.headline,
        narrative.plain_language_summary,
        narrative.valuation_argument,
        narrative.economic_quality_argument,
        narrative.expectations_argument,
        narrative.fragility_argument,
        *narrative.what_must_be_true,
        *narrative.what_could_break,
        *narrative.open_questions,
    )
    for argument in all_arguments:
        if not all(evidence_id in by_id for evidence_id in argument.evidence_ids):
            failures.append(f"{argument.category}: unknown evidence")
            continue
        if not any(
            by_id[evidence_id].topic in _TOPICS[argument.category]
            for evidence_id in argument.evidence_ids
        ):
            failures.append(f"{argument.category}: semantically irrelevant evidence")
    statements = " ".join(argument.statement.lower() for argument in all_arguments)
    margin = _numeric_value(by_id["margin_of_safety"])
    if margin < 0 and "positive base margin of safety" in statements:
        failures.append("negative margin of safety contradicts narrative")
    if margin > 0 and "negative base margin of safety" in statements:
        failures.append("positive margin of safety contradicts narrative")
    if (
        _numeric_value(by_id["market_price"]) > _numeric_value(by_id["base_fair_value"])
        and "below qhapaq's base fair value" in narrative.valuation_argument.statement.lower()
    ):
        failures.append("above fair value contradicts valuation argument")
    if (
        _numeric_value(by_id["roic_wacc_spread"]) > 0
        and "does not currently earn more" in narrative.economic_quality_argument.statement.lower()
    ):
        failures.append("positive ROIC-WACC spread contradicts economics argument")
    if (
        _numeric_value(by_id["expectations_gap"]) > 0
        and "at or below" in narrative.expectations_argument.statement.lower()
    ):
        failures.append("market expectations above base contradicts expectations argument")
    if (
        _numeric_value(by_id["terminal_value_share"]) >= 0.50
        and "less than half" in narrative.fragility_argument.statement.lower()
    ):
        failures.append("meaningful terminal dependence contradicts fragility argument")
    return ConsistencyResult(not failures, tuple(failures))


def explainability_contract(artifact: dict[str, Any]) -> dict[str, Any]:
    facts = build_semantic_facts(artifact)
    narrative = build_research_narrative(artifact, facts)
    validation = validate_narrative(narrative, facts)
    if not validation.valid:
        raise ValueError(f"deterministic narrative consistency failed: {validation.failures}")
    return {
        "schema_version": "qhapaq-explainability-v1",
        "facts": [asdict(fact) for fact in facts],
        "narrative": narrative.to_dict(),
        "consistency": validation.to_dict(),
        "concepts": concept_definitions(),
    }


def concept_definitions() -> dict[str, str]:
    return {
        "fair_value": "Qhapaq's estimate of what one share is worth under stated assumptions.",
        "margin_of_safety": "How far the price is below or above fair value. A negative result means price is above fair value.",
        "roic": "Return on invested capital: how effectively the business turns the capital it uses into after-tax operating profit.",
        "wacc": "Weighted average cost of capital: Qhapaq's estimate of the return investors require for funding the business.",
        "roic_wacc_spread": "ROIC minus WACC. A positive spread suggests the business creates value on the capital it uses.",
        "reverse_dcf": "A reverse DCF asks what growth the current price already assumes, rather than estimating a price from growth assumptions.",
        "terminal_value": "The portion of value assigned to cash flows after the explicit forecast period; more terminal value means more dependence on long-run assumptions.",
        "sensitivity": "A table showing how fair value changes when key assumptions such as growth or WACC change.",
    }
