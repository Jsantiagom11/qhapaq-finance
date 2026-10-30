from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from qhapaq_finance import cli
from qhapaq_finance.diamond.contracts import FundamentalRecord, SecurityRef
from qhapaq_finance.diamond.providers.sec_evidence import SecEvidenceManifest
from qhapaq_finance.opportunities_cli import run_opportunities, run_opportunity

try:
    from tests.diamond_helpers import AS_OF, rich_record
except ModuleNotFoundError:
    from diamond_helpers import AS_OF, rich_record


def _records() -> tuple[FundamentalRecord, ...]:
    output: list[FundamentalRecord] = []
    for index in range(20):
        ticker = f"T{index:02d}"
        cik = f"{index + 1:010d}"
        output.append(
            replace(
                rich_record(
                    ticker,
                    scale=1.0 + index * 0.03,
                    growth=0.04 + index * 0.003,
                    op_margin=0.15 + index * 0.004,
                    fcf_margin=0.10 + index * 0.003,
                    dilution=-0.005 + index * 0.0004,
                    recent_share_change=-0.01 + index * 0.001,
                ),
                issuer_id=f"sec-cik:{cik}",
                security_id=f"sec-cik:{cik}:{ticker}",
            )
        )
    return tuple(output)


def _manifests() -> tuple[SecEvidenceManifest, ...]:
    return tuple(
        SecEvidenceManifest(
            schema_version="diamond-sec-evidence-v1",
            cik=f"{index + 1:010d}",
            request_identity=(
                f"https://data.sec.gov/api/xbrl/companyfacts/CIK{index + 1:010d}.json"
            ),
            retrieved_at=datetime(2026, 9, 22, tzinfo=timezone.utc),
            data_as_of=AS_OF,
            payload_sha256=f"{index + 1:064x}",
            evidence_revision_sha256=f"{index + 101:064x}",
            latest_in_scope_filing_date=date(2026, 8, 1),
            latest_in_scope_accession=f"0000000001-26-{index + 1:06d}",
            etag=None,
            last_modified=None,
            blob_name=f"{index + 1:064x}.json",
        )
        for index in range(20)
    )


class _OfflineProvider:
    provider_requests = 0
    cache_hits = 41
    cache_misses = 0

    def __init__(self, cache_root: Path) -> None:
        self._records = _records()
        self._securities = tuple(
            SecurityRef(record.ticker, record.security_id, record.issuer_id)
            for record in self._records
        )
        self.read_paths = (cache_root / "evidence.json",)
        self.resolved_manifests = _manifests()

    def universe(self, universe_id: str, as_of: date) -> tuple[SecurityRef, ...]:
        assert universe_id == "sp500"
        assert as_of == AS_OF
        assert self.read_paths[0].is_file()
        return self._securities

    def fundamentals(
        self,
        securities: tuple[SecurityRef, ...],
        as_of: date,
        history_years: int = 5,
    ) -> tuple[FundamentalRecord, ...]:
        assert securities == self._securities
        assert as_of == AS_OF
        assert history_years == 5
        return self._records


def _install_factory(monkeypatch: pytest.MonkeyPatch, source_root: Path):
    roots: list[Path] = []

    def factory(cache_root: Path, *, refresh: bool, offline: bool = False):
        assert refresh is False
        assert offline is True
        root = cache_root.resolve()
        roots.append(root)
        return _OfflineProvider(root)

    source_root.mkdir(parents=True)
    (source_root / "evidence.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        "qhapaq_finance.opportunities_cli._production_funnel_provider",
        factory,
    )
    return roots


def test_first_run_seals_replays_and_writes_reports_without_analysis_or_network(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    output = tmp_path / "output"
    roots = _install_factory(monkeypatch, source)

    def forbidden(*args, **kwargs):
        raise AssertionError("opportunities must not invoke the analysis orchestrator")

    monkeypatch.setattr(
        "qhapaq_finance.analysis.AnalysisOrchestrator.analyze",
        forbidden,
    )
    run_opportunities(
        [
            "--as-of",
            AS_OF.isoformat(),
            "--cache-root",
            str(source),
            "--output",
            str(output),
            "--top",
            "10",
        ]
    )

    assert roots == [source.resolve(), (output / "snapshot" / "cache").resolve()]
    assert (output / "snapshot" / "manifest.json").is_file()
    assert (output / "opportunities.json").is_file()
    assert (output / "opportunities.json.sha256").is_file()
    assert (output / "opportunities.md").is_file()
    report = json.loads((output / "opportunities.json").read_text(encoding="utf-8"))
    assert report["summary"]["selected_count"] == 10
    assert report["summary"]["provider_requests"] == 0
    assert report["summary"]["cache_misses"] == 0
    assert report["snapshot"]["status"] == "COMPLETE"


def test_existing_complete_snapshot_replays_without_source_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    output = tmp_path / "output"
    roots = _install_factory(monkeypatch, source)
    arguments = [
        "--as-of",
        AS_OF.isoformat(),
        "--cache-root",
        str(source),
        "--output",
        str(output),
    ]
    run_opportunities(arguments)
    first_json = (output / "opportunities.json").read_bytes()
    first_markdown = (output / "opportunities.md").read_bytes()
    roots.clear()

    run_opportunities(arguments)

    assert roots == [(output / "snapshot" / "cache").resolve()]
    assert (output / "opportunities.json").read_bytes() == first_json
    assert (output / "opportunities.md").read_bytes() == first_markdown


@pytest.mark.parametrize("output_kind", ("same", "descendant", "ancestor"))
def test_output_must_not_overlap_source_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    output_kind: str,
) -> None:
    parent = tmp_path / "parent"
    source = parent / "source"
    _install_factory(monkeypatch, source)
    output = {
        "same": source,
        "descendant": source / "report",
        "ancestor": parent,
    }[output_kind]

    with pytest.raises(SystemExit):
        run_opportunities(
            [
                "--as-of",
                AS_OF.isoformat(),
                "--cache-root",
                str(source),
                "--output",
                str(output),
            ]
        )

    assert not (output / "snapshot" / "manifest.json").exists()


def test_focused_command_reads_artifact_only_and_main_dispatches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "source"
    output = tmp_path / "output"
    _install_factory(monkeypatch, source)
    cli.main(
        [
            "opportunities",
            "--as-of",
            AS_OF.isoformat(),
            "--cache-root",
            str(source),
            "--output",
            str(output),
        ]
    )
    capsys.readouterr()
    report = json.loads((output / "opportunities.json").read_text(encoding="utf-8"))
    ticker = report["opportunities"][0]["ticker"]

    cli.main(["opportunity", ticker, "--report", str(output / "opportunities.json")])
    focused = capsys.readouterr().out

    assert f"# {ticker}" in focused
    assert "Why selected" in focused
    assert "Evidence provenance" in focused
    assert "Evidence observations" in focused
    assert "Epistemic status" in focused
    assert "Verified facts" in focused
    assert "Derived metrics" in focused
    assert "Inference" in focused
    assert "Assumptions" in focused
    assert "Insufficient data" in focused
    assert "not an investment recommendation" in focused


def test_focused_command_rejects_unknown_ticker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    output = tmp_path / "output"
    _install_factory(monkeypatch, source)
    run_opportunities(
        [
            "--as-of",
            AS_OF.isoformat(),
            "--cache-root",
            str(source),
            "--output",
            str(output),
        ]
    )

    with pytest.raises(SystemExit):
        run_opportunity(["MISSING", "--report", str(output / "opportunities.json")])


def test_focused_command_rejects_tampered_report_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    output = tmp_path / "output"
    _install_factory(monkeypatch, source)
    run_opportunities(
        [
            "--as-of",
            AS_OF.isoformat(),
            "--cache-root",
            str(source),
            "--output",
            str(output),
        ]
    )
    report = output / "opportunities.json"
    report.write_bytes(report.read_bytes() + b" ")

    with pytest.raises(SystemExit):
        run_opportunity(["T18", "--report", str(report)])


def test_focused_command_rejects_rehashed_candidate_set_tampering(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    output = tmp_path / "output"
    _install_factory(monkeypatch, source)
    run_opportunities(
        [
            "--as-of",
            AS_OF.isoformat(),
            "--cache-root",
            str(source),
            "--output",
            str(output),
        ]
    )
    report = output / "opportunities.json"
    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["candidate_set"]["candidate_set_id"] = "0" * 64
    encoded = (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode()
    report.write_bytes(encoded)
    (output / "opportunities.json.sha256").write_text(
        f"{hashlib.sha256(encoded).hexdigest()}  opportunities.json\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit):
        run_opportunity(["T18", "--report", str(report)])


def test_focused_command_rejects_tampered_snapshot_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    output = tmp_path / "output"
    _install_factory(monkeypatch, source)
    run_opportunities(
        [
            "--as-of",
            AS_OF.isoformat(),
            "--cache-root",
            str(source),
            "--output",
            str(output),
        ]
    )
    selected = output / "snapshot" / "cache" / "evidence.json"
    selected.chmod(0o644)
    selected.write_text('{"tampered":true}\n', encoding="utf-8")

    with pytest.raises(SystemExit):
        run_opportunity(["T18", "--report", str(output / "opportunities.json")])
