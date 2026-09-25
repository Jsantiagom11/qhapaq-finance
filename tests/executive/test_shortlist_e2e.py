from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from qhapaq_finance.analysis import AnalysisResult, AnalysisStatus
from qhapaq_finance.diamond.funnel import run_funnel
from qhapaq_finance.diamond.providers.local import LocalJsonProvider
from qhapaq_finance.executive.deep_analysis import (
    DeepAnalysisOrchestrator,
)
from qhapaq_finance.executive.shortlist import (
    ExecutiveShortlistRun,
    build_shortlist_from_funnel,
    canonical_shortlist_json,
    render_shortlist_text,
)

ROOT = Path(__file__).resolve().parents[2]
DIAMOND_FIXTURE = ROOT / "tests" / "fixtures" / "diamond" / "minimal-universe.json"
GOLDEN_JSON = ROOT / "tests" / "fixtures" / "executive" / "shortlist-e2e.json"
GOLDEN_TEXT = ROOT / "tests" / "fixtures" / "executive" / "shortlist-e2e.txt"

# Frozen external analysis evidence for the known T19 winner.
#
# The value is a fixed observed enterprise value corresponding to the
# external input boundary, not calculated by the E2E fixture itself.
FROZEN_ENTERPRISE_VALUE = 1815.8184042854218


def _canonical(ticker: str) -> object:
    return SimpleNamespace(
        content_identity=f"frozen-analysis:{ticker}",
        valuation={
            "normalized_fcff": 100.0,
            "roic": 0.14,
            "wacc": 0.10,
            "diagnostics": [
                "FROZEN_ANALYSIS_FLAG",
            ],
            "scenarios": {
                "base": {
                    "explicit_growth": 0.05,
                    "terminal_growth": 0.03,
                    "years": 5,
                }
            },
        },
        market_comparison={
            "enterprise_value": FROZEN_ENTERPRISE_VALUE,
        },
    )


class FrozenSyncAnalyzer:
    """Frozen analysis I/O boundary behind the real async orchestrator."""

    def analyze(self, ticker: str) -> AnalysisResult:
        if ticker == "T19":
            status = AnalysisStatus.COMPLETED
            canonical = _canonical(ticker)
        else:
            status = AnalysisStatus.EVIDENCE_REQUIRED
            canonical = None

        return cast(
            AnalysisResult,
            SimpleNamespace(
                plan=SimpleNamespace(
                    identity=SimpleNamespace(
                        ticker=ticker,
                    )
                ),
                status=status,
                canonical_result=canonical,
            ),
        )


async def _execute() -> tuple[
    ExecutiveShortlistRun,
    tuple[str, ...],
]:
    # Real deterministic Diamond provider over a frozen local I/O fixture.
    provider = LocalJsonProvider(DIAMOND_FIXTURE)

    # Real Diamond engine / ranking.
    funnel = run_funnel(
        provider,
        universe_id=provider.universe_id,
        as_of=provider.data_as_of,
        depth=2,
    )

    # Real Task 4 orchestrator. Only its synchronous external analysis
    # boundary is frozen.
    deep = DeepAnalysisOrchestrator(
        analyzer=FrozenSyncAnalyzer(),
    )

    # Real shortlist assembly, Goal Seek and ExecutiveSynthesis.
    run = await build_shortlist_from_funnel(
        funnel,
        universe_id=provider.universe_id,
        as_of=provider.data_as_of,
        deep_analysis=deep,
    )

    return (
        run,
        tuple(item.ticker for item in funnel.results),
    )


def _actual() -> tuple[
    ExecutiveShortlistRun,
    tuple[str, ...],
    str,
    str,
]:
    run, funnel_tickers = asyncio.run(_execute())

    return (
        run,
        funnel_tickers,
        canonical_shortlist_json(run),
        render_shortlist_text(run),
    )


def test_frozen_e2e_json_matches_exact_golden() -> None:
    _, _, actual_json, _ = _actual()

    assert actual_json == GOLDEN_JSON.read_text(encoding="utf-8")


def test_frozen_e2e_text_matches_exact_golden() -> None:
    _, _, _, actual_text = _actual()

    assert actual_text == GOLDEN_TEXT.read_text(encoding="utf-8")


def test_frozen_e2e_preserves_order_provenance_and_fail_closed() -> None:
    run, funnel_tickers, actual_json, actual_text = _actual()
    payload = json.loads(actual_json)

    shortlist_tickers = tuple(item["ticker"] for item in payload["entries"])

    # Diamond remains the sole selector/orderer.
    assert funnel_tickers == shortlist_tickers
    assert funnel_tickers[0] == "T19"

    assert payload["dataset_identity"] == run.funnel_metadata.dataset_identity
    assert payload["dataset_identity"]

    first = payload["entries"][0]

    # Canonical provenance survives translation.
    assert first["ticker"] == "T19"
    assert first["analysis_status"] == {
        "source_status": "COMPLETED",
        "conclusion_available": True,
        "reason": None,
    }

    evidence = first["evidence"]

    assert {item["metric_id"] for item in evidence} == {
        "normalized_fcff",
        "roic",
        "wacc",
        "enterprise_value",
    }

    assert {item["source_identity"] for item in evidence} == {
        "frozen-analysis:T19",
    }

    # Real Goal Seek solved the frozen valuation boundary.
    expectation = first["expectations"]
    assert expectation is not None

    assert expectation["status"] == "SOLVED"
    assert expectation["implied_fcff_growth"] == pytest.approx(
        0.08,
        abs=0.002,
    )
    assert expectation["starting_fcff"] == 100.0
    assert expectation["hurdle_rate"] == 0.10
    assert expectation["terminal_growth_rate"] == 0.03
    assert expectation["years"] == 5
    assert expectation["observed_enterprise_value"] == FROZEN_ENTERPRISE_VALUE

    assert {item["flag_id"] for item in first["contradictions"]} >= {
        "ANALYSIS:FROZEN_ANALYSIS_FLAG",
    }

    # Task 3 never manufactures a conclusion.
    assert first["bottom_line"] is None

    second = payload["entries"][1]

    # Incomplete analysis must remain strictly fail-closed.
    assert second["analysis_status"] == {
        "source_status": "EVIDENCE_REQUIRED",
        "conclusion_available": False,
        "reason": None,
    }
    assert second["evidence"] == []
    assert second["expectations"] is None
    assert second["bottom_line"] is None

    # Both renderers carry the same stable semantic identities.
    for ticker in funnel_tickers:
        assert f"ticker={ticker}" in actual_text

    assert f"dataset_identity={payload['dataset_identity']}" in actual_text
    assert "frozen-analysis:T19" in actual_text


def _write_goldens() -> None:
    _, _, actual_json, actual_text = _actual()

    GOLDEN_JSON.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    GOLDEN_JSON.write_text(
        actual_json,
        encoding="utf-8",
    )
    GOLDEN_TEXT.write_text(
        actual_text,
        encoding="utf-8",
    )


if __name__ == "__main__":
    _write_goldens()
