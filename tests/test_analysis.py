from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType

import pytest

from qhapaq_finance import cli
from qhapaq_finance.analysis import (
    AnalysisOrchestrator,
    AnalysisProgressKind,
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
from qhapaq_finance.sec_acquisition import StagedSecResource
from qhapaq_finance.sec_canonical_gate import (
    SecCanonicalGateResult,
    SecCanonicalGateState,
    SecCanonicalReason,
    evaluate_sec_canonical_gate,
)
from qhapaq_finance.sec_client import SecResponse
from qhapaq_finance.sec_evidence_provider import (
    SecFastPathBundle,
    SecFilingDescriptor,
    SecSubmissionsBundle,
)
from qhapaq_finance.sec_filing_xbrl import FilingNativeEvidence

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


class _Task6AaplResolver:
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


class _Task6SecClient:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def get(self, url: str) -> SecResponse:
        self.urls.append(url)
        name = "submissions.json" if "/submissions/" in url else "companyfacts.json"
        content = (ROOT / "tests/fixtures/sec_corpus/AAPL" / name).read_bytes()
        return SecResponse(200, {"Content-Type": "application/json"}, content)


def _task6_analysis_root(tmp_path: Path) -> Path:
    shutil.copytree(ROOT / "data/domain", tmp_path / "data/domain")
    return tmp_path


def _task6_fast_path_bundle(tmp_path: Path) -> SecFastPathBundle:
    fixture = ROOT / "tests/fixtures/sec_corpus/AAPL"
    companyfacts = json.loads((fixture / "companyfacts.json").read_text(encoding="utf-8"))
    submissions = json.loads((fixture / "submissions.json").read_text(encoding="utf-8"))
    recent = submissions["filings"]["recent"]
    filings = tuple(
        SecFilingDescriptor(
            accession,
            form,
            filing_date,
            report_date or None,
            primary_document,
            form.endswith("/A"),
        )
        for accession, form, filing_date, report_date, primary_document in zip(
            recent["accessionNumber"],
            recent["form"],
            recent["filingDate"],
            recent["reportDate"],
            recent["primaryDocument"],
            strict=True,
        )
        if form in {"10-K", "10-K/A", "10-Q", "10-Q/A"}
    )
    staged = StagedSecResource(tmp_path / "raw.bin", tmp_path / "meta.json", "a" * 64, 1)
    return SecFastPathBundle(
        SecSubmissionsBundle(MappingProxyType(submissions), staged, filings),
        companyfacts,
        staged,
    )


def test_task6_local_sec_ready_uses_zero_acquisition() -> None:
    def unexpected_factory() -> object:
        raise AssertionError("local canonical SEC evidence must remain offline")

    result = AnalysisOrchestrator(ROOT, sec_client_factory=unexpected_factory).analyze("QCOM")

    assert result.status is AnalysisStatus.COMPLETED
    assert result.plan.acquisition.state is AnalysisStageState.NOT_REQUESTED


def test_task6_fast_ready_fetches_aggregates_once_and_stops_before_filings(
    tmp_path: Path,
) -> None:
    client = _Task6SecClient()
    events = []
    result = AnalysisOrchestrator(
        _task6_analysis_root(tmp_path),
        resolver=_Task6AaplResolver(),
        sec_client_factory=lambda: client,  # type: ignore[arg-type]
        progress_observer=events.append,
    ).analyze("AAPL")

    assert result.status is AnalysisStatus.EVIDENCE_REQUIRED
    assert result.plan.acquisition.state is AnalysisStageState.COMPLETED
    assert result.plan.evidence.state is AnalysisStageState.COMPLETED
    assert client.urls == [
        "https://data.sec.gov/submissions/CIK0000320193.json",
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
    ]
    assert [event.kind for event in events] == [
        AnalysisProgressKind.RESOLUTION_STARTED,
        AnalysisProgressKind.FAST_PATH_ACQUISITION_STARTED,
        AnalysisProgressKind.FAST_PATH_ACQUISITION_COMPLETED,
        AnalysisProgressKind.CANONICAL_GATE_READY,
        AnalysisProgressKind.CANONICALIZATION_COMPLETED,
    ]


def test_task6_gap_executes_one_verified_fallback_then_continues_downstream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _task6_analysis_root(tmp_path)
    bundle = _task6_fast_path_bundle(tmp_path)
    fixture_facts = json.loads(
        (ROOT / "tests/fixtures/sec_corpus/AAPL/companyfacts.json").read_text(encoding="utf-8")
    )
    from qhapaq_finance.financial_canonicalization import extract_company_facts

    ready = evaluate_sec_canonical_gate(
        extract_company_facts(fixture_facts, source_identity="fixture")
    )
    assert ready.snapshot is not None
    gates = iter(
        (
            SecCanonicalGateResult(
                SecCanonicalGateState.GAP,
                SecCanonicalReason.MISSING_STANDARD_CONCEPT,
                None,
            ),
            ready,
        )
    )
    gate_calls = 0

    def gate(*args: object, **kwargs: object) -> SecCanonicalGateResult:
        nonlocal gate_calls
        del args, kwargs
        gate_calls += 1
        return next(gates)

    provider_instances = []

    class Provider:
        def __init__(self, client: object, staging_root: Path) -> None:
            self.client = client
            self.staging_root = staging_root
            self.calls = 0
            provider_instances.append(self)

        def acquire_fast_path(self, identity: CompanyIdentity) -> SecFastPathBundle:
            assert identity.ticker == "AAPL"
            self.calls += 1
            return bundle

    exports: list[str] = []

    def export(
        client: object,
        *,
        staging_root: Path,
        issuer_root: Path,
        ticker: str,
        cik: str,
        filing: SecFilingDescriptor,
    ) -> list[dict[str, object]]:
        del client, staging_root
        assert ticker == "AAPL"
        assert cik == "0000320193"
        exports.append(filing.accession)
        relative = Path("filings") / filing.accession / "filing-artifact" / "instance.xml"
        artifact = issuer_root / relative
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text("<xbrl/>", encoding="utf-8")
        return [
            {
                "artifact_kind": "filing-artifact",
                "path": relative.as_posix(),
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                "accession": filing.accession,
                "form": filing.form,
                "filing_date": filing.filing_date,
                "report_date": filing.report_date,
            }
        ]

    parsed = []

    def parse(filings: tuple[object, ...]) -> FilingNativeEvidence:
        parsed.extend(filings)
        return FilingNativeEvidence((), MappingProxyType({}), ())

    monkeypatch.setattr("qhapaq_finance.analysis.StructuredSecProvider", Provider)
    monkeypatch.setattr("qhapaq_finance.analysis.evaluate_sec_canonical_gate", gate)
    monkeypatch.setattr("qhapaq_finance.analysis.export_sec_filing", export)
    monkeypatch.setattr("qhapaq_finance.analysis.parse_filing_native_evidence", parse)
    events = []

    result = AnalysisOrchestrator(
        root,
        resolver=_Task6AaplResolver(),
        sec_client_factory=object,  # type: ignore[arg-type]
        progress_observer=events.append,
    ).analyze("AAPL")

    assert result.status is AnalysisStatus.EVIDENCE_REQUIRED
    assert len(provider_instances) == 1
    assert provider_instances[0].calls == 1
    assert gate_calls == 2
    assert len(exports) == 1
    assert len(parsed) == 1
    assert [event.kind for event in events] == [
        AnalysisProgressKind.RESOLUTION_STARTED,
        AnalysisProgressKind.FAST_PATH_ACQUISITION_STARTED,
        AnalysisProgressKind.FAST_PATH_ACQUISITION_COMPLETED,
        AnalysisProgressKind.CANONICAL_GATE_GAP,
        AnalysisProgressKind.FILING_FALLBACK_STARTED,
        AnalysisProgressKind.FILING_FALLBACK_COMPLETED,
        AnalysisProgressKind.CANONICAL_GATE_READY,
        AnalysisProgressKind.CANONICALIZATION_COMPLETED,
    ]


@pytest.mark.parametrize(
    ("final_gate", "expected_status"),
    [
        (
            SecCanonicalGateResult(
                SecCanonicalGateState.GAP,
                SecCanonicalReason.REQUIRED_COMPONENT_MISSING,
                None,
            ),
            AnalysisStatus.EVIDENCE_REQUIRED,
        ),
        (
            SecCanonicalGateResult(
                SecCanonicalGateState.BLOCKED,
                SecCanonicalReason.CANONICAL_INVARIANT,
                None,
            ),
            AnalysisStatus.BLOCKED,
        ),
    ],
)
def test_task6_post_fallback_gate_maps_gap_and_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    final_gate: SecCanonicalGateResult,
    expected_status: AnalysisStatus,
) -> None:
    bundle = _task6_fast_path_bundle(tmp_path)

    class Provider:
        def __init__(self, client: object, staging_root: Path) -> None:
            del client, staging_root

        def acquire_fast_path(self, identity: CompanyIdentity) -> SecFastPathBundle:
            del identity
            return bundle

    gates = iter(
        (
            SecCanonicalGateResult(
                SecCanonicalGateState.GAP,
                SecCanonicalReason.MISSING_STANDARD_CONCEPT,
                None,
            ),
            final_gate,
        )
    )

    def export(
        client: object,
        *,
        staging_root: Path,
        issuer_root: Path,
        ticker: str,
        cik: str,
        filing: SecFilingDescriptor,
    ) -> list[dict[str, object]]:
        del client, staging_root, ticker, cik
        relative = Path("filings") / filing.accession / "filing-artifact" / "instance.xml"
        artifact = issuer_root / relative
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text("<xbrl/>", encoding="utf-8")
        return [
            {
                "artifact_kind": "filing-artifact",
                "path": relative.as_posix(),
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                "accession": filing.accession,
                "form": filing.form,
                "filing_date": filing.filing_date,
                "report_date": filing.report_date,
            }
        ]

    monkeypatch.setattr("qhapaq_finance.analysis.StructuredSecProvider", Provider)
    monkeypatch.setattr(
        "qhapaq_finance.analysis.evaluate_sec_canonical_gate", lambda *args, **kwargs: next(gates)
    )
    monkeypatch.setattr("qhapaq_finance.analysis.export_sec_filing", export)
    monkeypatch.setattr(
        "qhapaq_finance.analysis.parse_filing_native_evidence",
        lambda filings: FilingNativeEvidence((), MappingProxyType({}), ()),
    )

    result = AnalysisOrchestrator(
        _task6_analysis_root(tmp_path),
        resolver=_Task6AaplResolver(),
        sec_client_factory=object,  # type: ignore[arg-type]
    ).analyze("AAPL")

    assert result.status is expected_status


def test_task6_acquisition_failure_is_blocked_not_unsupported(tmp_path: Path) -> None:
    calls = 0

    def failing_factory() -> object:
        nonlocal calls
        calls += 1
        raise OSError("SEC unavailable")

    result = AnalysisOrchestrator(
        _task6_analysis_root(tmp_path),
        resolver=_Task6AaplResolver(),
        sec_client_factory=failing_factory,  # type: ignore[arg-type]
    ).analyze("AAPL")

    assert calls == 1
    assert result.status is AnalysisStatus.BLOCKED


def test_task6_plan_remains_network_free(tmp_path: Path) -> None:
    def unexpected_factory() -> object:
        raise AssertionError("plan must not instantiate an SEC client")

    plan = AnalysisOrchestrator(
        _task6_analysis_root(tmp_path),
        resolver=_Task6AaplResolver(),
        sec_client_factory=unexpected_factory,  # type: ignore[arg-type]
    ).plan("AAPL")

    assert plan.status is AnalysisStatus.EVIDENCE_REQUIRED


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

    headings = (
        "ANALYST DETAIL",
        "FINANCIAL DETAIL",
        "DCF SCENARIOS",
        "EVIDENCE QUALITY",
        "READINESS",
        "PROVENANCE",
        "AUDIT",
    )

    assert all(heading in output for heading in headings)
    lines = output.splitlines()
    assert [lines.index(heading) for heading in headings] == sorted(
        lines.index(heading) for heading in headings
    )
    assert "quality.gates[" not in output
    assert "financial_evidence_quality." not in output
    assert "model_requirements." not in output
    assert "model_stage_readiness." not in output


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


def test_task6_verified_filing_accepts_real_export_index_record(tmp_path: Path) -> None:
    from qhapaq_finance.financial_canonicalization import extract_company_facts

    bundle = _task6_fast_path_bundle(tmp_path)
    filing = next(
        item for item in bundle.submissions.filings if item.form == "10-K" and not item.amendment
    )
    identity = CompanyIdentity(
        "AAPL",
        None,
        None,
        "Apple Inc.",
        "NASDAQ",
        None,
        "0000320193",
        None,
    )
    issuer_root = tmp_path / "issuer"

    index_relative = Path("filings") / filing.accession / "filing-index" / "index.json"
    artifact_relative = Path("filings") / filing.accession / "filing-artifact" / "instance.xml"

    index_path = issuer_root / index_relative
    artifact_path = issuer_root / artifact_relative
    index_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)

    index_path.write_text('{"directory":{"item":[]}}', encoding="utf-8")
    artifact_path.write_text("<xbrl/>", encoding="utf-8")

    def record(kind: str, relative: Path, path: Path) -> dict[str, object]:
        return {
            "artifact_kind": kind,
            "path": relative.as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "accession": filing.accession,
            "form": filing.form,
            "filing_date": filing.filing_date,
            "report_date": filing.report_date,
        }

    raw_facts = extract_company_facts(
        bundle.companyfacts,
        source_identity="fixture",
    )

    verified = AnalysisOrchestrator._verified_filing_artifacts(
        identity,
        filing,
        [
            record("filing-index", index_relative, index_path),
            record("filing-artifact", artifact_relative, artifact_path),
        ],
        issuer_root,
        raw_facts,
    )

    assert tuple(item.path for item in verified.artifacts) == (artifact_path.resolve(),)


# --- Task 7 terminal acquisition UX contracts ---


class _Task7ProgressOrchestrator:
    def __init__(
        self,
        repository_root: Path,
        *,
        progress_observer: object | None = None,
    ) -> None:
        del repository_root
        self.progress_observer = progress_observer

    def analyze(self, ticker: str):
        from qhapaq_finance.analysis import AnalysisProgressEvent

        assert ticker == "QCOM"

        observer = self.progress_observer
        if observer is not None:
            assert callable(observer)
            for event in (
                AnalysisProgressEvent(
                    AnalysisProgressKind.RESOLUTION_STARTED,
                    "QCOM",
                ),
                AnalysisProgressEvent(
                    AnalysisProgressKind.FAST_PATH_ACQUISITION_STARTED,
                ),
                AnalysisProgressEvent(
                    AnalysisProgressKind.CANONICAL_GATE_GAP,
                    "MISSING_STANDARD_CONCEPT",
                ),
                AnalysisProgressEvent(
                    AnalysisProgressKind.FILING_FALLBACK_STARTED,
                    "MISSING_STANDARD_CONCEPT",
                ),
                AnalysisProgressEvent(
                    AnalysisProgressKind.FILING_FALLBACK_COMPLETED,
                    "MISSING_STANDARD_CONCEPT",
                ),
                AnalysisProgressEvent(
                    AnalysisProgressKind.CANONICALIZATION_COMPLETED,
                ),
            ):
                observer(event)

        return AnalysisOrchestrator(ROOT).analyze("QCOM")


def test_task7_cli_tty_progress_uses_stderr_and_report_uses_stdout(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "AnalysisOrchestrator", _Task7ProgressOrchestrator)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    cli.main(["analyze", "QCOM", "--repository-root", str(ROOT), "--plain"])

    captured = capsys.readouterr()

    assert "QHAPAQ" in captured.out
    assert "COMPLETED" in captured.out

    assert captured.err
    assert "SEC" in captured.err
    assert "filing" in captured.err.lower()

    assert "QHAPAQ" not in captured.err
    assert captured.out.isascii()
    assert captured.err.isascii()


def test_task7_cli_json_suppresses_progress_and_preserves_exact_json(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "AnalysisOrchestrator", _Task7ProgressOrchestrator)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    expected = AnalysisOrchestrator(ROOT).analyze("QCOM")

    cli.main(
        [
            "analyze",
            "QCOM",
            "--repository-root",
            str(ROOT),
            "--json",
        ]
    )

    captured = capsys.readouterr()

    assert captured.err == ""
    assert captured.out == cli.canonical_json(expected.to_dict())


def test_task7_cli_non_tty_suppresses_progress(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "AnalysisOrchestrator", _Task7ProgressOrchestrator)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)

    cli.main(["analyze", "QCOM", "--repository-root", str(ROOT)])

    captured = capsys.readouterr()

    assert "QHAPAQ" in captured.out
    assert captured.err == ""
