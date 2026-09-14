from __future__ import annotations

import json
from pathlib import Path

from qhapaq_finance import cli
from qhapaq_finance.analysis import AnalysisOrchestrator, AnalysisStageState, AnalysisStatus
from qhapaq_finance.research_result import build_canonical_research_result

ROOT = Path(__file__).resolve().parents[1]


def test_qcom_and_nvda_run_through_generic_completed_orchestration() -> None:
    orchestrator = AnalysisOrchestrator(ROOT)
    for ticker in ("QCOM", "NVDA"):
        result = orchestrator.analyze(ticker)
        assert result.status is AnalysisStatus.COMPLETED
        assert result.canonical_result is not None
        assert result.canonical_result == build_canonical_research_result(ticker, ROOT)
        assert result.plan.identity.ticker == ticker
        assert result.plan.research.state is AnalysisStageState.COMPLETED
        assert result.plan.valuation.state is AnalysisStageState.COMPLETED
        assert result.plan.acquisition.state is AnalysisStageState.NOT_REQUESTED
        assert result.plan.publishing.state is AnalysisStageState.NOT_REQUESTED
        assert result.plan.evidence_plan is not None
        assert result.plan.evidence_plan.items[0].state.value == "AVAILABLE"


def test_registered_ticker_without_canonical_evidence_is_structured_not_valued() -> None:
    result = AnalysisOrchestrator(ROOT).analyze("AAPL")

    assert result.status is AnalysisStatus.EVIDENCE_REQUIRED
    assert result.canonical_result is None
    assert result.plan.identity.issuer_id == "apple-inc"
    assert result.plan.evidence.state is AnalysisStageState.BLOCKED
    assert result.plan.acquisition.state is AnalysisStageState.NOT_REQUESTED
    assert result.plan.valuation.state is AnalysisStageState.BLOCKED
    assert result.plan.evidence_plan is not None
    assert result.plan.evidence_plan.items[0].state.value == "MISSING"


def test_unregistered_ticker_is_an_explicit_structured_outcome() -> None:
    result = AnalysisOrchestrator(ROOT).analyze("nope")

    assert result.status is AnalysisStatus.UNSUPPORTED_TICKER
    assert result.canonical_result is None
    assert result.plan.identity.to_dict() == {
        "ticker": "NOPE",
        "security_id": None,
        "issuer_id": None,
        "display_name": None,
        "exchange": None,
        "share_class": None,
        "cik": None,
        "source": None,
    }


def test_analyze_cli_is_a_thin_structured_orchestration_entrypoint(
    capsys: object,
) -> None:
    cli.main(["analyze", "QCOM", "--repository-root", str(ROOT)])
    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]

    assert payload["status"] == "COMPLETED"
    assert payload["plan"]["identity"]["ticker"] == "QCOM"
    assert payload["canonical_result"]["security"]["ticker"] == "QCOM"
