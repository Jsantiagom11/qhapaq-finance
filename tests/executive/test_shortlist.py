from __future__ import annotations

import asyncio
import importlib
import json
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import cast

import pytest

from qhapaq_finance import cli as root_cli
from qhapaq_finance.analysis import AnalysisStatus
from qhapaq_finance.diamond.archetypes import Archetype
from qhapaq_finance.diamond.engine import DiamondResult
from qhapaq_finance.diamond.funnel import (
    FunnelRun,
    FunnelRunMetadata,
)
from qhapaq_finance.executive.contracts import (
    ExecutiveAnalysisStatus,
)
from qhapaq_finance.executive.deep_analysis import (
    DeepAnalysisResult,
)
from qhapaq_finance.research_result import (
    build_canonical_research_result,
)
from qhapaq_finance.valuation import (
    load_fixture_case,
    present_value_fcff,
)

ROOT = Path(__file__).resolve().parents[2]


def _shortlist() -> ModuleType:
    try:
        return importlib.import_module("qhapaq_finance.executive.shortlist")
    except ModuleNotFoundError as exc:
        pytest.fail(
            f"shortlist module missing: {exc}",
            pytrace=False,
        )


def _executive_cli() -> ModuleType:
    try:
        return importlib.import_module("qhapaq_finance.executive.cli")
    except ModuleNotFoundError as exc:
        pytest.fail(
            f"executive CLI module missing: {exc}",
            pytrace=False,
        )


def test_canonical_result_exposes_goal_seek_years() -> None:
    result = build_canonical_research_result("QCOM", ROOT)
    case = load_fixture_case("QCOM", ROOT)

    scenarios = cast(
        dict[str, dict[str, object]],
        result.valuation["scenarios"],
    )
    expected = next(item.years for item in case.scenarios if item.name == "base")

    assert scenarios["base"]["years"] == expected


def _candidate(
    ticker: str,
    surfaced_by: Archetype,
    priority: float,
    diagnostics: tuple[str, ...] = (),
) -> DiamondResult:
    return cast(
        DiamondResult,
        SimpleNamespace(
            ticker=ticker,
            archetypes=SimpleNamespace(
                surfaced_by=surfaced_by,
                research_priority=priority,
            ),
            diagnostics=diagnostics,
        ),
    )


def _canonical(
    ticker: str,
    *,
    diagnostic: str | None = None,
) -> object:
    growth = 0.08
    fcff = 100.0
    wacc = 0.10
    terminal_growth = 0.03
    years = 5

    enterprise_value = present_value_fcff(
        starting_fcff=fcff,
        explicit_growth=growth,
        terminal_growth=terminal_growth,
        wacc=wacc,
        years=years,
    )

    diagnostics = [] if diagnostic is None else [diagnostic]

    return SimpleNamespace(
        research_as_of=SimpleNamespace(isoformat=lambda: "2026-09-24"),
        content_identity=f"canonical:{ticker}",
        valuation={
            "normalized_fcff": fcff,
            "roic": 0.14,
            "wacc": wacc,
            "diagnostics": diagnostics,
            "scenarios": {
                "base": {
                    "explicit_growth": 0.05,
                    "terminal_growth": terminal_growth,
                    "years": years,
                }
            },
        },
        market_comparison={
            "enterprise_value": enterprise_value,
        },
    )


def _deep_result(
    ticker: str,
    *,
    canonical: object | None,
    status: AnalysisStatus = AnalysisStatus.COMPLETED,
) -> DeepAnalysisResult:
    conclusion_available = status is AnalysisStatus.COMPLETED and canonical is not None

    return DeepAnalysisResult(
        ticker=ticker,
        analysis_result=cast(
            object,
            SimpleNamespace(canonical_result=canonical),
        ),
        analysis_status=ExecutiveAnalysisStatus(
            source_status=status,
            conclusion_available=conclusion_available,
            reason=None,
            bottom_line=None,
        ),
    )


class FakeDeepAnalysis:
    def __init__(
        self,
        outcomes: tuple[DeepAnalysisResult, ...],
    ) -> None:
        self.outcomes = outcomes
        self.seen: list[str] = []

    async def analyze(
        self,
        candidates: object,
    ) -> tuple[DeepAnalysisResult, ...]:
        self.seen = [item.ticker for item in cast(tuple[DiamondResult, ...], candidates)]
        return self.outcomes


def _funnel() -> FunnelRun:
    candidates = (
        _candidate(
            "MO",
            Archetype.INFLECTION,
            91.0,
            ("DIAMOND_FLAG",),
        ),
        _candidate(
            "UBER",
            Archetype.QUALITY_VALUE,
            87.5,
        ),
    )

    metadata = FunnelRunMetadata(
        universe_count=503,
        canonical_records=503,
        ranked_records=117,
        unranked_records=386,
        provider_requests=0,
        cache_hits=1526,
        cache_misses=0,
        acquisition_seconds=0.5,
        evaluation_seconds=0.2,
        dataset_identity="dataset:stable",
    )

    return FunnelRun(
        results=candidates,
        metadata=metadata,
    )


def test_enrichment_preserves_exact_diamond_order_and_uses_real_goal_seek() -> None:
    module = _shortlist()
    funnel = _funnel()

    deep = FakeDeepAnalysis(
        (
            _deep_result(
                "MO",
                canonical=_canonical(
                    "MO",
                    diagnostic="ANALYSIS_FLAG",
                ),
            ),
            _deep_result(
                "UBER",
                canonical=_canonical("UBER"),
            ),
        )
    )

    run = asyncio.run(
        module.build_shortlist_from_funnel(
            funnel,
            universe_id="sp500",
            as_of=module.date(2026, 9, 24),
            deep_analysis=deep,
        )
    )

    assert deep.seen == ["MO", "UBER"]
    assert [item.ticker for item in run.entries] == [
        "MO",
        "UBER",
    ]

    first = run.entries[0]

    assert first.surfaced_by is Archetype.INFLECTION
    assert first.research_priority == 91.0
    assert "INFLECTION" in first.why_it_surfaced.upper()

    assert first.expectations is not None
    assert first.expectations.implied_fcff_growth == pytest.approx(
        0.08,
        abs=0.002,
    )
    assert first.expectations.years == 5
    assert first.expectations.hurdle_rate == pytest.approx(0.10)
    assert first.expectations.terminal_growth_rate == pytest.approx(0.03)

    assert {item.metric_id for item in first.evidence} >= {
        "normalized_fcff",
        "wacc",
        "enterprise_value",
    }

    assert {item.flag_id for item in first.contradictions} == {
        "DIAMOND:DIAMOND_FLAG",
        "ANALYSIS:ANALYSIS_FLAG",
    }


def test_incomplete_analysis_fails_closed_without_fabricating_financials() -> None:
    module = _shortlist()
    funnel = _funnel()

    deep = FakeDeepAnalysis(
        (
            _deep_result(
                "MO",
                canonical=None,
                status=AnalysisStatus.EVIDENCE_REQUIRED,
            ),
            _deep_result(
                "UBER",
                canonical=None,
                status=AnalysisStatus.BLOCKED,
            ),
        )
    )

    run = asyncio.run(
        module.build_shortlist_from_funnel(
            funnel,
            universe_id="sp500",
            as_of=module.date(2026, 9, 24),
            deep_analysis=deep,
        )
    )

    for entry in run.entries:
        assert entry.analysis_status.conclusion_available is False
        assert entry.expectations is None
        assert entry.evidence == ()
        assert entry.bottom_line is None


def _sample_run() -> object:
    module = _shortlist()

    deep = FakeDeepAnalysis(
        (
            _deep_result(
                "MO",
                canonical=_canonical("MO"),
            ),
            _deep_result(
                "UBER",
                canonical=_canonical("UBER"),
            ),
        )
    )

    return asyncio.run(
        module.build_shortlist_from_funnel(
            _funnel(),
            universe_id="sp500",
            as_of=module.date(2026, 9, 24),
            deep_analysis=deep,
        )
    )


def test_json_and_text_are_semantically_equivalent() -> None:
    module = _shortlist()
    run = _sample_run()

    payload = json.loads(module.canonical_shortlist_json(run))
    text = module.render_shortlist_text(run)

    assert payload == module.shortlist_payload(run)

    assert payload["schema_version"] == "executive-shortlist-v1"
    assert payload["universe"] == "sp500"
    assert payload["as_of"] == "2026-09-24"
    assert payload["dataset_identity"] == "dataset:stable"

    assert [item["ticker"] for item in payload["entries"]] == ["MO", "UBER"]

    for item in payload["entries"]:
        assert f"ticker={item['ticker']}" in text
        assert f"surfaced_by={item['surfaced_by']}" in text
        assert f"research_priority={item['research_priority']}" in text
        assert f"analysis_status={item['analysis_status']['source_status']}" in text

        expectation = item["expectations"]
        assert expectation is not None
        assert f"expectation_status={expectation['status']}" in text
        assert f"years={expectation['years']}" in text

        for evidence in item["evidence"]:
            assert evidence["metric_id"] in text
            assert evidence["source_identity"] in text


def test_serialization_normalizes_one_ulp_research_priority_noise() -> None:
    module = _shortlist()
    run = _sample_run()
    entry = run.entries[0]

    lower = replace(
        run,
        entries=(
            replace(
                entry,
                research_priority=82.43421052631578,
            ),
        ),
    )
    upper = replace(
        run,
        entries=(
            replace(
                entry,
                research_priority=82.4342105263158,
            ),
        ),
    )

    assert lower.entries[0].research_priority != upper.entries[0].research_priority

    assert module.canonical_shortlist_json(lower) == module.canonical_shortlist_json(upper)
    assert module.render_shortlist_text(lower) == module.render_shortlist_text(upper)


def test_root_cli_routes_shortlist_and_text_is_default(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    executive_cli = _executive_cli()
    run = _sample_run()
    calls: list[tuple[str, int]] = []

    def fake_run(
        *,
        universe_id: str,
        depth: int,
    ) -> object:
        calls.append((universe_id, depth))
        return run

    monkeypatch.setattr(
        executive_cli,
        "run_production_shortlist",
        fake_run,
    )

    root_cli.main(
        [
            "shortlist",
            "--universe",
            "sp500",
            "--depth",
            "2",
        ]
    )

    text = capsys.readouterr().out

    assert calls == [("sp500", 2)]
    assert text.startswith("QHAPAQ EXECUTIVE SHORTLIST\n")
    assert "ticker=MO" in text


def test_root_cli_json_routes_same_semantics(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    executive_cli = _executive_cli()
    shortlist = _shortlist()
    run = _sample_run()

    monkeypatch.setattr(
        executive_cli,
        "run_production_shortlist",
        lambda *, universe_id, depth: run,
    )

    root_cli.main(
        [
            "shortlist",
            "--universe",
            "sp500",
            "--depth",
            "2",
            "--format",
            "json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)

    assert payload == shortlist.shortlist_payload(run)


@pytest.mark.parametrize("depth", ("0", "-1"))
def test_shortlist_rejects_non_positive_depth(
    depth: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        root_cli.main(
            [
                "shortlist",
                "--depth",
                depth,
            ]
        )

    assert "--depth must be positive" in capsys.readouterr().err


def test_run_shortlist_injects_diamond_identity_into_default_analysis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qhapaq_finance.analysis import AnalysisOrchestrator
    from qhapaq_finance.diamond.contracts import SecurityRef
    from qhapaq_finance.executive.identity_resolver import (
        DiamondIdentityResolver,
    )

    module = _shortlist()

    candidate = cast(
        DiamondResult,
        SimpleNamespace(
            ticker="ACME",
            company_name="Acme Corporation",
            provider="sec-first",
            source_security=SecurityRef(
                ticker="ACME",
                security_id="security:acme",
                issuer_id="sec-cik:0000000123",
            ),
        ),
    )

    funnel = cast(
        FunnelRun,
        SimpleNamespace(
            results=(candidate,),
            metadata=SimpleNamespace(),
        ),
    )

    sentinel = object()

    monkeypatch.setattr(
        module,
        "run_funnel",
        lambda *args, **kwargs: funnel,
    )

    async def capture_build(
        received_funnel: FunnelRun,
        *,
        universe_id: str,
        as_of: object,
        deep_analysis: object,
    ) -> object:
        assert received_funnel is funnel
        assert universe_id == "sp500"

        analyzer = deep_analysis._analyzer

        assert isinstance(analyzer, AnalysisOrchestrator)
        assert isinstance(
            analyzer.resolver,
            DiamondIdentityResolver,
        )

        resolved = analyzer.resolver.resolve("ACME")

        assert resolved is not None
        assert resolved.cik == "0000000123"
        assert resolved.provenance.source_url == "diamond://sec-first/security-ref"

        return sentinel

    monkeypatch.setattr(
        module,
        "build_shortlist_from_funnel",
        capture_build,
    )

    result = asyncio.run(
        module.run_shortlist(
            object(),
            universe_id="sp500",
            as_of=module.date(2026, 9, 22),
            depth=1,
            repository_root=Path("."),
        )
    )

    assert result is sentinel
