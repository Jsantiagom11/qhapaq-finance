from __future__ import annotations

import json
from pathlib import Path

from qhapaq_finance import cli
from qhapaq_finance.diamond.cli import (
    _production_funnel_provider,
    funnel_command,
    inspect_command,
    provider_benchmark_command,
    screen_command,
)
from qhapaq_finance.diamond.providers.local import LocalJsonProvider
from qhapaq_finance.diamond.providers.sec import SecFirstProvider
from qhapaq_finance.sec_config import SecConfig

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


def test_production_funnel_provider_does_not_require_fmp(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.setattr(
        "qhapaq_finance.diamond.cli.SecConfig.from_env",
        lambda: SecConfig("Qhapaq Finance", "research@example.com", 8.0),
    )

    provider = _production_funnel_provider(tmp_path, refresh=False)

    assert isinstance(provider, SecFirstProvider)


def test_funnel_cli_does_not_invoke_analysis_orchestrator(monkeypatch, capsys) -> None:
    local = LocalJsonProvider(FIXTURE)

    class Sp500AliasProvider:
        def universe(self, universe_id, as_of):
            assert universe_id == "sp500"
            return local.universe(local.universe_id, as_of)

        def fundamentals(self, securities, as_of, history_years=5):
            return local.fundamentals(securities, as_of, history_years)

    def forbidden(*args, **kwargs):
        raise AssertionError("funnel must not invoke AnalysisOrchestrator.analyze")

    monkeypatch.setattr("qhapaq_finance.analysis.AnalysisOrchestrator.analyze", forbidden)
    monkeypatch.setattr(
        "qhapaq_finance.diamond.cli._production_funnel_provider",
        lambda cache_root, refresh: Sp500AliasProvider(),
    )

    funnel_command(
        [
            "--universe",
            "sp500",
            "--depth",
            "1",
            "--as-of",
            local.data_as_of.isoformat(),
            "--format",
            "json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["results"][0]["ticker"] == "T19"
