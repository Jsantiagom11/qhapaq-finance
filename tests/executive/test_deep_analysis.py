from __future__ import annotations

import asyncio
import importlib
import threading
import time
from types import ModuleType, SimpleNamespace
from typing import cast

import pytest

from qhapaq_finance.accounting import AccountingError
from qhapaq_finance.analysis import AnalysisResult, AnalysisStageState, AnalysisStatus
from qhapaq_finance.company_resolver import ResolverError
from qhapaq_finance.diamond.engine import DiamondResult
from qhapaq_finance.financial_promotion import FinancialPromotionError
from qhapaq_finance.local_sec_corpus import LocalSecCorpusError
from qhapaq_finance.market_inputs import MarketInputError
from qhapaq_finance.research_result import ResearchResultError
from qhapaq_finance.sec_client import SecClientError
from qhapaq_finance.universe import UniverseError
from qhapaq_finance.valuation import ValuationError

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


def _module() -> ModuleType:
    try:
        return importlib.import_module("qhapaq_finance.executive.deep_analysis")
    except ModuleNotFoundError as exc:
        pytest.fail(
            f"deep analysis module missing: {exc}",
            pytrace=False,
        )


def _candidate(ticker: str) -> DiamondResult:
    return cast(DiamondResult, SimpleNamespace(ticker=ticker))


def _analysis_result(
    ticker: str,
    *,
    status: AnalysisStatus = AnalysisStatus.COMPLETED,
    canonical: object | None = object(),
) -> AnalysisResult:
    identity = SimpleNamespace(ticker=ticker)
    plan = SimpleNamespace(identity=identity)

    return cast(
        AnalysisResult,
        SimpleNamespace(
            status=status,
            plan=plan,
            canonical_result=canonical,
        ),
    )


class OrderedAnalyzer:
    def __init__(self, delays: dict[str, float]) -> None:
        self.delays = delays
        self.completion_order: list[str] = []

    def analyze(self, ticker: str) -> AnalysisResult:
        time.sleep(self.delays[ticker])
        self.completion_order.append(ticker)
        return _analysis_result(ticker)


class ConcurrencyAnalyzer:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.active = 0
        self.maximum = 0

    def analyze(self, ticker: str) -> AnalysisResult:
        with self.lock:
            self.active += 1
            self.maximum = max(self.maximum, self.active)

        time.sleep(0.04)

        with self.lock:
            self.active -= 1

        return _analysis_result(ticker)


class ThreadRecordingAnalyzer:
    def __init__(self) -> None:
        self.thread_ids: list[int] = []

    def analyze(self, ticker: str) -> AnalysisResult:
        self.thread_ids.append(threading.get_ident())
        return _analysis_result(ticker)


class RaisingAnalyzer:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def analyze(self, ticker: str) -> AnalysisResult:
        raise self.exc


class TerminalAnalyzer:
    def __init__(self, status: AnalysisStatus) -> None:
        self.status = status

    def analyze(self, ticker: str) -> AnalysisResult:
        return _analysis_result(
            ticker,
            status=self.status,
            canonical=None,
        )


class MismatchedAnalyzer:
    def analyze(self, ticker: str) -> AnalysisResult:
        return _analysis_result("WRONG")


def test_expected_domain_error_boundary_is_explicit() -> None:
    module = _module()

    assert module.EXPECTED_DOMAIN_ERRORS == EXPECTED_DOMAIN_ERRORS
    assert Exception not in module.EXPECTED_DOMAIN_ERRORS
    assert ValueError not in module.EXPECTED_DOMAIN_ERRORS
    assert TypeError not in module.EXPECTED_DOMAIN_ERRORS
    assert KeyError not in module.EXPECTED_DOMAIN_ERRORS


def test_preserves_exact_input_index_even_when_completion_order_differs() -> None:
    module = _module()
    analyzer = OrderedAnalyzer(
        {
            "MO": 0.06,
            "UBER": 0.01,
            "CRH": 0.02,
        }
    )

    inputs = tuple(_candidate(ticker) for ticker in ("MO", "UBER", "CRH"))

    output = asyncio.run(module.DeepAnalysisOrchestrator(analyzer=analyzer).analyze(inputs))

    assert analyzer.completion_order != ["MO", "UBER", "CRH"]
    assert [item.ticker for item in output] == [
        "MO",
        "UBER",
        "CRH",
    ]

    for index, item in enumerate(output):
        assert item.ticker == inputs[index].ticker


def test_never_runs_more_than_two_sync_analyses_concurrently() -> None:
    module = _module()
    analyzer = ConcurrencyAnalyzer()

    inputs = tuple(_candidate(ticker) for ticker in ("A", "B", "C", "D", "E"))

    output = asyncio.run(module.DeepAnalysisOrchestrator(analyzer=analyzer).analyze(inputs))

    assert len(output) == len(inputs)
    assert analyzer.maximum == 2


def test_sync_analyzer_runs_off_event_loop_thread() -> None:
    module = _module()
    analyzer = ThreadRecordingAnalyzer()
    caller_thread = threading.get_ident()

    asyncio.run(module.DeepAnalysisOrchestrator(analyzer=analyzer).analyze((_candidate("MO"),)))

    assert analyzer.thread_ids
    assert all(thread_id != caller_thread for thread_id in analyzer.thread_ids)


@pytest.mark.parametrize("error_type", EXPECTED_DOMAIN_ERRORS)
def test_real_domain_error_degrades_fail_closed(
    error_type: type[Exception],
) -> None:
    module = _module()
    analyzer = RaisingAnalyzer(error_type("expected domain failure"))

    output = asyncio.run(
        module.DeepAnalysisOrchestrator(analyzer=analyzer).analyze((_candidate("MO"),))
    )

    assert len(output) == 1

    result = output[0]

    assert result.ticker == "MO"
    assert result.analysis_result is None
    assert result.analysis_status.source_status is AnalysisStatus.BLOCKED
    assert result.analysis_status.conclusion_available is False
    assert result.analysis_status.bottom_line is None
    assert result.analysis_status.reason is not None
    assert error_type.__name__ in result.analysis_status.reason


@pytest.mark.parametrize(
    "error",
    (
        KeyError("programming defect"),
        TypeError("programming defect"),
        ValueError("generic value defect"),
    ),
)
def test_unexpected_errors_propagate(error: Exception) -> None:
    module = _module()

    with pytest.raises(type(error)):
        asyncio.run(
            module.DeepAnalysisOrchestrator(analyzer=RaisingAnalyzer(error)).analyze(
                (_candidate("MO"),)
            )
        )


@pytest.mark.parametrize(
    "status",
    (
        AnalysisStatus.BLOCKED,
        AnalysisStatus.EVIDENCE_REQUIRED,
        AnalysisStatus.UNSUPPORTED_TICKER,
    ),
)
def test_existing_terminal_analysis_state_is_preserved(
    status: AnalysisStatus,
) -> None:
    module = _module()

    output = asyncio.run(
        module.DeepAnalysisOrchestrator(analyzer=TerminalAnalyzer(status)).analyze(
            (_candidate("MO"),)
        )
    )

    result = output[0]

    assert result.analysis_result is not None
    assert result.analysis_status.source_status is status
    assert result.analysis_status.conclusion_available is False
    assert result.analysis_status.bottom_line is None


def test_completed_analysis_marks_conclusion_available() -> None:
    module = _module()

    output = asyncio.run(
        module.DeepAnalysisOrchestrator(
            analyzer=TerminalAnalyzer(AnalysisStatus.COMPLETED)
        ).analyze((_candidate("MO"),))
    )

    # TerminalAnalyzer deliberately supplies no canonical result.
    # A COMPLETED result without canonical evidence must fail closed.
    assert output[0].analysis_status.conclusion_available is False


def test_completed_analysis_with_canonical_result_is_available() -> None:
    module = _module()

    class CompletedAnalyzer:
        def analyze(self, ticker: str) -> AnalysisResult:
            return _analysis_result(
                ticker,
                status=AnalysisStatus.COMPLETED,
                canonical=object(),
            )

    output = asyncio.run(
        module.DeepAnalysisOrchestrator(analyzer=CompletedAnalyzer()).analyze((_candidate("MO"),))
    )

    assert output[0].analysis_status.source_status is AnalysisStatus.COMPLETED
    assert output[0].analysis_status.conclusion_available is True


def test_analysis_ticker_mismatch_crashes_instead_of_hiding_defect() -> None:
    module = _module()

    with pytest.raises(ValueError, match="ticker mismatch"):
        asyncio.run(
            module.DeepAnalysisOrchestrator(analyzer=MismatchedAnalyzer()).analyze(
                (_candidate("MO"),)
            )
        )


def _analysis_result_with_stages(
    ticker: str,
    *,
    status: AnalysisStatus,
    acquisition: object | None = None,
    evidence: object | None = None,
    research: object | None = None,
    valuation: object | None = None,
    publishing: object | None = None,
) -> AnalysisResult:
    completed = SimpleNamespace(
        state=AnalysisStageState.COMPLETED,
        reason=None,
    )
    plan = SimpleNamespace(
        identity=SimpleNamespace(ticker=ticker),
        acquisition=acquisition or completed,
        evidence=evidence or completed,
        research=research or completed,
        valuation=valuation or completed,
        publishing=publishing or completed,
    )
    return cast(
        AnalysisResult,
        SimpleNamespace(
            status=status,
            plan=plan,
            canonical_result=None,
        ),
    )


def _analysis_stage(
    state: AnalysisStageState,
    reason: str | None = None,
) -> object:
    return SimpleNamespace(state=state, reason=reason)


def test_terminal_blocked_analysis_preserves_stage_reason() -> None:
    module = _module()
    expected = "checksum-verified canonical evidence is not available"
    result = _analysis_result_with_stages(
        "MO",
        status=AnalysisStatus.EVIDENCE_REQUIRED,
        evidence=_analysis_stage(
            AnalysisStageState.BLOCKED,
            expected,
        ),
    )

    class Analyzer:
        def analyze(self, ticker: str) -> AnalysisResult:
            assert ticker == "MO"
            return result

    output = asyncio.run(
        module.DeepAnalysisOrchestrator(
            analyzer=Analyzer(),
        ).analyze((_candidate("MO"),))
    )

    status = output[0].analysis_status

    assert status.source_status is AnalysisStatus.EVIDENCE_REQUIRED
    assert status.conclusion_available is False
    assert status.reason == expected
    assert status.bottom_line is None


def test_first_non_empty_blocked_stage_reason_wins() -> None:
    module = _module()
    result = _analysis_result_with_stages(
        "MO",
        status=AnalysisStatus.BLOCKED,
        acquisition=_analysis_stage(
            AnalysisStageState.BLOCKED,
            "",
        ),
        evidence=_analysis_stage(
            AnalysisStageState.BLOCKED,
            "evidence blocker",
        ),
        research=_analysis_stage(
            AnalysisStageState.BLOCKED,
            "research blocker",
        ),
        valuation=_analysis_stage(
            AnalysisStageState.BLOCKED,
            "valuation blocker",
        ),
    )

    class Analyzer:
        def analyze(self, ticker: str) -> AnalysisResult:
            return result

    output = asyncio.run(
        module.DeepAnalysisOrchestrator(
            analyzer=Analyzer(),
        ).analyze((_candidate("MO"),))
    )

    assert output[0].analysis_status.reason == "evidence blocker"


def test_terminal_analysis_without_blocked_reason_keeps_none() -> None:
    module = _module()
    result = _analysis_result_with_stages(
        "MO",
        status=AnalysisStatus.BLOCKED,
        evidence=_analysis_stage(
            AnalysisStageState.BLOCKED,
            None,
        ),
        research=_analysis_stage(
            AnalysisStageState.READY,
            "not a blocked-stage reason",
        ),
    )

    class Analyzer:
        def analyze(self, ticker: str) -> AnalysisResult:
            return result

    output = asyncio.run(
        module.DeepAnalysisOrchestrator(
            analyzer=Analyzer(),
        ).analyze((_candidate("MO"),))
    )

    assert output[0].analysis_status.reason is None
