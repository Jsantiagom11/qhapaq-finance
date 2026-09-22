from __future__ import annotations

import json
from pathlib import Path

from qhapaq_finance import cli
from qhapaq_finance.diamond.cli import inspect_command, provider_benchmark_command, screen_command

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tests/fixtures/diamond/minimal-universe.json"
REFERENCE = ROOT / "tests/fixtures/diamond/provider-reference.json"
CANDIDATE = ROOT / "tests/fixtures/diamond/provider-candidate.json"


def test_screen_json_is_machine_readable_and_does_not_need_network(capsys) -> None:
    screen_command(["--input", str(FIXTURE), "--depth", "5", "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "diamond-funnel-v1"
    assert len(payload["results"]) == 5


def test_inspect_json_exposes_scores_percentiles_coverage_and_diagnostics(capsys) -> None:
    inspect_command(["T00", "--input", str(FIXTURE), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["ticker"] == "T00"
    assert "scores" in payload
    assert "percentiles" in payload
    assert "coverage" in payload
    assert "diagnostics" in payload


def test_provider_benchmark_cli_is_offline_json(capsys) -> None:
    provider_benchmark_command(
        ["--reference", str(REFERENCE), "--candidate", str(CANDIDATE), "--format", "json"]
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["required_family_coverage"] < 1.0


def test_main_dispatch_exposes_screen_without_invoking_analysis(monkeypatch, capsys) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("screen must not invoke AnalysisOrchestrator.analyze")

    monkeypatch.setattr("qhapaq_finance.analysis.AnalysisOrchestrator.analyze", forbidden)
    cli.main(["screen", "--input", str(FIXTURE), "--depth", "1", "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "diamond-funnel-v1"
