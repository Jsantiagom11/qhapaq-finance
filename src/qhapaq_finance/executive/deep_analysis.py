"""Concurrent execution boundary for Diamond-selected deep analysis."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from qhapaq_finance.accounting import AccountingError
from qhapaq_finance.analysis import (
    AnalysisOrchestrator,
    AnalysisResult,
    AnalysisStageState,
    AnalysisStatus,
)
from qhapaq_finance.company_resolver import ResolverError
from qhapaq_finance.diamond.engine import DiamondResult
from qhapaq_finance.financial_promotion import (
    FinancialPromotionError,
)
from qhapaq_finance.local_sec_corpus import LocalSecCorpusError
from qhapaq_finance.market_inputs import MarketInputError
from qhapaq_finance.research_result import ResearchResultError
from qhapaq_finance.sec_client import SecClientError
from qhapaq_finance.universe import UniverseError
from qhapaq_finance.valuation import ValuationError

from .contracts import ExecutiveAnalysisStatus

EXPECTED_DOMAIN_ERRORS = (
    AccountingError,
    ResolverError,
    FinancialPromotionError,
    LocalSecCorpusError,
    MarketInputError,
    ResearchResultError,
    SecClientError,
    UniverseError,
    ValuationError,
)


class SyncAnalyzer(Protocol):
    """Existing synchronous single-company analysis boundary."""

    def analyze(self, ticker: str) -> AnalysisResult: ...


@dataclass(frozen=True)
class DeepAnalysisResult:
    """One input-index-preserving deep-analysis outcome."""

    ticker: str
    analysis_result: AnalysisResult | None
    analysis_status: ExecutiveAnalysisStatus


class DeepAnalysisOrchestrator:
    """Run existing synchronous analysis with bounded concurrency."""

    def __init__(
        self,
        repository_root: str | Path = ".",
        *,
        analyzer: SyncAnalyzer | None = None,
    ) -> None:
        self._analyzer: SyncAnalyzer = (
            analyzer if analyzer is not None else AnalysisOrchestrator(repository_root)
        )

    async def analyze(
        self,
        diamond_top_n: Sequence[DiamondResult],
    ) -> tuple[DeepAnalysisResult, ...]:
        """Analyze in parallel while preserving exact Diamond input order."""
        semaphore = asyncio.Semaphore(2)

        return tuple(
            await asyncio.gather(
                *(self._analyze_one(candidate, semaphore) for candidate in diamond_top_n)
            )
        )

    async def _analyze_one(
        self,
        candidate: DiamondResult,
        semaphore: asyncio.Semaphore,
    ) -> DeepAnalysisResult:
        async with semaphore:
            try:
                result = await asyncio.to_thread(
                    self._analyzer.analyze,
                    candidate.ticker,
                )
            except EXPECTED_DOMAIN_ERRORS as exc:
                return DeepAnalysisResult(
                    ticker=candidate.ticker,
                    analysis_result=None,
                    analysis_status=ExecutiveAnalysisStatus(
                        source_status=AnalysisStatus.BLOCKED,
                        conclusion_available=False,
                        reason=_domain_error_reason(exc),
                        bottom_line=None,
                    ),
                )

        if result.plan.identity.ticker != candidate.ticker:
            raise ValueError(
                "deep analysis ticker mismatch: "
                f"expected {candidate.ticker}, "
                f"received {result.plan.identity.ticker}"
            )

        conclusion_available = (
            result.status is AnalysisStatus.COMPLETED and result.canonical_result is not None
        )

        return DeepAnalysisResult(
            ticker=candidate.ticker,
            analysis_result=result,
            analysis_status=ExecutiveAnalysisStatus(
                source_status=result.status,
                conclusion_available=conclusion_available,
                reason=(
                    None
                    if result.status is AnalysisStatus.COMPLETED
                    else _first_blocked_reason(result)
                ),
                bottom_line=None,
            ),
        )


def _first_blocked_reason(result: AnalysisResult) -> str | None:
    for stage_name in (
        "acquisition",
        "evidence",
        "research",
        "valuation",
        "publishing",
    ):
        stage = getattr(result.plan, stage_name, None)
        reason = getattr(stage, "reason", None)
        if (
            getattr(stage, "state", None) is AnalysisStageState.BLOCKED
            and isinstance(reason, str)
            and reason
        ):
            return reason
    return None


def _domain_error_reason(exc: Exception) -> str:
    detail = str(exc).strip()
    name = type(exc).__name__

    return f"{name}: {detail}" if detail else name
