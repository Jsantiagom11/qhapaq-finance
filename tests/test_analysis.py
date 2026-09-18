from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from qhapaq_finance import cli
from qhapaq_finance.analysis import (
    AnalysisOrchestrator,
    AnalysisStageState,
    AnalysisStatus,
    CompanyIdentity,
)
from qhapaq_finance.company_resolver import CompanyProvenance, ResolvedCompany
from qhapaq_finance.financial_canonicalization import classify_issuer
from qhapaq_finance.local_sec_corpus import LocalSecCorpus
from qhapaq_finance.market import MarketSnapshot, MarketState
from qhapaq_finance.market_inputs import cache_yfinance_snapshot
from qhapaq_finance.research_result import build_canonical_research_result

ROOT = Path(__file__).resolve().parents[1]


def _local_sec_corpus(root: Path, identity: CompanyIdentity) -> None:
    issuer = root / "data/cache/sec_corpus_live" / identity.ticker
    issuer.mkdir(parents=True)
    companyfacts = {"cik": identity.cik, "facts": {}}
    submissions = {
        "cik": identity.cik,
        "filings": {
            "recent": {
                "accessionNumber": ["0000000123-25-000001"],
                "form": ["10-K"],
                "filingDate": ["2025-02-01"],
                "reportDate": ["2024-12-31"],
                "primaryDocument": ["acme-20241231.htm"],
            }
        },
    }
    (issuer / "companyfacts.json").write_text(json.dumps(companyfacts), encoding="utf-8")
    (issuer / "submissions.json").write_text(json.dumps(submissions), encoding="utf-8")
    records = []
    for name, _payload in (("companyfacts.json", companyfacts), ("submissions.json", submissions)):
        raw = (issuer / name).read_bytes()
        records.append(
            {
                "artifact_kind": name.removesuffix(".json"),
                "path": name,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "ticker": identity.ticker,
                "cik": identity.cik,
            }
        )
    filing_path = issuer / "filings/0000000123-25-000001/filing-artifact/acme-20241231.htm"
    filing_path.parent.mkdir(parents=True)
    filing_path.write_text("<html></html>", encoding="utf-8")
    records.append(
        {
            "artifact_kind": "filing-artifact",
            "path": filing_path.relative_to(issuer).as_posix(),
            "sha256": hashlib.sha256(filing_path.read_bytes()).hexdigest(),
            "ticker": identity.ticker,
            "cik": identity.cik,
            "accession": "0000000123-25-000001",
            "form": "10-K",
            "filing_date": "2025-02-01",
            "report_date": "2024-12-31",
        }
    )
    (issuer / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "sec-corpus-issuer-v1",
                "ticker": identity.ticker,
                "cik": identity.cik,
                "companyfacts": records[0],
                "submissions": records[1],
                "artifacts": [records[2]],
                "selected_filings": {
                    "10-K": {
                        "accession": "0000000123-25-000001",
                        "form": "10-K",
                        "filing_date": "2025-02-01",
                        "report_date": "2024-12-31",
                        "primary_document": "acme-20241231.htm",
                    },
                    "10-Q": None,
                },
                "sufficiency": {"primitive_companyfacts_canonicalization": True},
            }
        ),
        encoding="utf-8",
    )


def test_local_validated_sec_corpus_is_promoted_to_canonicalization(tmp_path: Path) -> None:
    """A registered identity uses valid local SEC evidence without network access."""
    identity = CompanyIdentity("ACME", "acme:ACME", "acme", "Acme", None, None, "0000000123", None)
    _local_sec_corpus(tmp_path, identity)
    calls: list[dict[str, object]] = []

    class RecordingEngine:
        def canonicalize(
            self, company: object, staged_evidence: dict[str, object], **kwargs: object
        ) -> str:
            del company, kwargs
            calls.append(staged_evidence)
            return "attempted"

    result = LocalSecCorpus(tmp_path).canonicalize(
        identity, profile=classify_issuer(sic=3570), engine=RecordingEngine()
    )

    assert result == "attempted"
    assert calls[0]["selected_filing"] == {
        "accession": "0000000123-25-000001",
        "form": "10-K",
        "filing_date": "2025-02-01",
        "report_date": "2024-12-31",
        "primary_document": "acme-20241231.htm",
    }


def test_local_sec_corpus_accepts_the_default_relative_repository_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = CompanyIdentity("ACME", "acme:ACME", "acme", "Acme", None, None, "0000000123", None)
    _local_sec_corpus(tmp_path, identity)
    monkeypatch.chdir(tmp_path)

    assert LocalSecCorpus().evidence(identity).selected_filing["form"] == "10-K"


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


def test_registered_aapl_runs_end_to_end_from_canonical_evidence(
    aapl_analysis_root: Path,
) -> None:
    result = AnalysisOrchestrator(aapl_analysis_root).analyze("AAPL")

    assert result.status is AnalysisStatus.COMPLETED
    assert result.canonical_result is not None

    assert result.plan.identity.issuer_id == "apple-inc"
    assert result.plan.identity.security_id == "apple-inc:AAPL"

    assert result.plan.evidence.state is AnalysisStageState.COMPLETED
    assert result.plan.research.state is AnalysisStageState.COMPLETED
    assert result.plan.valuation.state is AnalysisStageState.COMPLETED

    canonical = result.canonical_result

    assert canonical.security["ticker"] == "AAPL"
    assert canonical.financial_evidence["capital_cost"]["source_mode"] == "canonical"

    # The primary identity includes Apple commercial paper at the closing date,
    # unlike the prior long-term-debt-only canonical debt policy.
    assert canonical.valuation["wacc"] == pytest.approx(
        0.086890,
        abs=1e-5,
    )


def test_generic_accounting_snapshot_consumes_temporary_canonical_market_evidence(
    tmp_path: Path,
) -> None:
    """A valid canonical quote clears market readiness but not capital-cost readiness."""
    shutil.copytree(ROOT / "data/domain", tmp_path / "data/domain")
    shutil.copytree(
        ROOT / "tests/fixtures/sec_corpus/AAPL",
        tmp_path / "data/cache/sec_corpus_live/AAPL",
    )
    profile = cache_yfinance_snapshot(
        root=tmp_path,
        ticker="AAPL",
        max_age=timedelta(days=1),
        fetcher=lambda _ticker, *, now: MarketSnapshot(
            ticker="AAPL",
            price=100.0,
            currency="USD",
            observed_at=datetime(2026, 6, 27, tzinfo=timezone.utc),
            retrieved_at=datetime(2026, 6, 27, tzinfo=timezone.utc),
            source="yfinance",
            market_state=MarketState.REGULAR,
        ),
        now=datetime(2026, 6, 27, tzinfo=timezone.utc),
    )
    issuers_path = tmp_path / "data/domain/issuers.json"
    issuers = json.loads(issuers_path.read_text(encoding="utf-8"))
    next(item for item in issuers["issuers"] if item["id"] == "apple-inc")["research"] = {
        "as_of": "2026-06-28",
        "market_quality_profile": profile.relative_to(tmp_path).as_posix(),
    }
    issuers_path.write_text(json.dumps(issuers), encoding="utf-8")

    class AaplResolver:
        def resolve(self, ticker: str) -> ResolvedCompany | None:
            if ticker != "AAPL":
                return None
            return ResolvedCompany(
                "AAPL",
                "Apple Inc.",
                "0000320193",
                "NASDAQ",
                CompanyProvenance("fixture", None, None, None),
            )

    result = AnalysisOrchestrator(tmp_path, resolver=AaplResolver()).analyze("AAPL")

    assert result.status is AnalysisStatus.EVIDENCE_REQUIRED
    assert result.plan.evidence.state is AnalysisStageState.COMPLETED
    assert result.plan.research.state is AnalysisStageState.COMPLETED
    assert result.plan.valuation.reason == (
        "BETA_REQUIRED,RISK_FREE_REQUIRED,ERP_REQUIRED,COST_OF_DEBT_REQUIRED"
    )
    assert result.plan.market_input is not None
    assert result.plan.market_input.price == 100.0
    assert result.plan.market_input.market_equity == 1_459_418_000_000.0
    assert result.plan.market_input.provenance(date(2026, 6, 27)).source_mode == "canonical"


def test_local_cache_miss_is_blocked_during_offline_planning() -> None:
    plan = AnalysisOrchestrator(ROOT).plan("nope")

    assert plan.status is AnalysisStatus.BLOCKED
    assert plan.identity.to_dict() == {
        "ticker": "NOPE",
        "security_id": None,
        "issuer_id": None,
        "display_name": None,
        "exchange": None,
        "share_class": None,
        "cik": None,
        "source": None,
    }


def test_analyze_cli_defaults_to_human_view(capsys: pytest.CaptureFixture[str]) -> None:
    cli.main(["analyze", "QCOM", "--repository-root", str(ROOT)])
    output = capsys.readouterr().out

    assert "QHAPAQ" in output
    assert "COMPLETED" in output
    assert "MARKET EXPECTATIONS" in output
    assert "BUSINESS ECONOMICS" in output
    assert '"schema_version"' not in output


def test_analyze_cli_detail_adds_analyst_sections(
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli.main(["analyze", "QCOM", "--repository-root", str(ROOT), "--detail", "--plain"])
    output = capsys.readouterr().out

    assert "ANALYSIS STAGES" in output
    assert "DCF SCENARIOS" in output
    assert "MARKET PROVENANCE" in output
    assert "AUDIT" in output


def test_analyze_cli_plain_is_ascii_without_ansi(capsys: pytest.CaptureFixture[str]) -> None:
    cli.main(["analyze", "QCOM", "--repository-root", str(ROOT), "--plain"])
    output = capsys.readouterr().out

    assert output.isascii()
    assert "\x1b[" not in output


def test_analyze_cli_json_preserves_canonical_machine_artifact(
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli.main(["analyze", "QCOM", "--repository-root", str(ROOT), "--json"])
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert payload["schema_version"] == "analysis-result-v1"
    assert payload["status"] == "COMPLETED"
    assert payload["plan"]["identity"]["ticker"] == "QCOM"
    assert payload["canonical_result"]["security"]["ticker"] == "QCOM"
    expected = AnalysisOrchestrator(ROOT).analyze("QCOM")
    assert output == cli.canonical_json(expected.to_dict())


@pytest.mark.parametrize(
    ("human_flag", "message"),
    [
        ("--detail", "not allowed with argument --json"),
        ("--plain", "--json cannot be combined with --plain"),
    ],
)
def test_analyze_cli_rejects_json_with_human_flags(
    human_flag: str, message: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        cli.main(["analyze", "QCOM", "--json", human_flag])
    assert message in capsys.readouterr().err


def test_analyze_cli_non_tty_disables_color(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(
        shutil, "get_terminal_size", lambda fallback=None: os.terminal_size((72, 24))
    )

    cli.main(["analyze", "QCOM", "--repository-root", str(ROOT)])

    output = capsys.readouterr().out
    assert "QHAPAQ" in output
    assert "\x1b[" not in output


def test_analyze_cli_no_color_environment_disables_color(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr(
        shutil, "get_terminal_size", lambda fallback=None: os.terminal_size((72, 24))
    )

    cli.main(["analyze", "QCOM", "--repository-root", str(ROOT)])

    output = capsys.readouterr().out
    assert "QHAPAQ" in output
    assert "\x1b[" not in output


def test_analyze_cli_tty_enables_semantic_color(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.delenv("NO_COLOR", raising=False)

    cli.main(["analyze", "QCOM", "--repository-root", str(ROOT)])

    output = capsys.readouterr().out
    assert "QHAPAQ" in output
    assert "\x1b[" in output
