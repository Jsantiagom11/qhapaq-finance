"""Diamond Funnel: low-cost, deterministic research-priority discovery."""

from .contracts import (
    FiscalSlot,
    FundamentalObservation,
    FundamentalPeriodType,
    FundamentalRecord,
    Methodology,
    PeriodKind,
    SecurityRef,
    UnitKind,
)
from .engine import DiamondResult, evaluate_universe

__all__ = [
    "DiamondResult",
    "FiscalSlot",
    "FundamentalObservation",
    "FundamentalPeriodType",
    "FundamentalRecord",
    "Methodology",
    "PeriodKind",
    "SecurityRef",
    "UnitKind",
    "evaluate_universe",
]
