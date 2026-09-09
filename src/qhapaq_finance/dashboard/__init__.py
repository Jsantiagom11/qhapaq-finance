"""Offline dashboard serialization and rendering."""

from ..explainability import (
    ArgumentCategory,
    Fact,
    FactStatus,
    ResearchArgument,
    ResearchNarrative,
    build_research_narrative,
    build_semantic_facts,
    validate_narrative,
)
from .renderer import render_company_dashboard, render_universe_dashboard
from .serializer import (
    build_company_artifact,
    build_universe_artifact,
    canonical_json,
    write_artifacts,
)

__all__ = [
    "build_company_artifact",
    "build_universe_artifact",
    "canonical_json",
    "render_company_dashboard",
    "render_universe_dashboard",
    "write_artifacts",
    "ArgumentCategory",
    "Fact",
    "FactStatus",
    "ResearchArgument",
    "ResearchNarrative",
    "build_research_narrative",
    "build_semantic_facts",
    "validate_narrative",
]
