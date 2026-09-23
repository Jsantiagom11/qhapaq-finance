from __future__ import annotations

import json
from pathlib import Path

import pytest

import qhapaq_finance.diamond.cli as diamond_cli
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


@pytest.mark.parametrize("refresh", [False, True])
def test_production_funnel_wires_debt_zero_cache_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    refresh: bool,
) -> None:
    seen: dict[str, object] = {}

    sec_client = object()
    universe_provider = object()
    market_provider = object()
    evidence_store = object()
    canonical_cache = object()
    split_provider = object()
    final_provider = object()

    monkeypatch.setattr(
        diamond_cli.SecConfig,
        "from_env",
        lambda: SecConfig(
            "Qhapaq Finance",
            "research@example.com",
            8.0,
        ),
    )
    monkeypatch.setattr(
        diamond_cli,
        "SecClient",
        lambda config: sec_client,
    )
    monkeypatch.setattr(
        diamond_cli,
        "WikipediaTextClient",
        lambda: object(),
    )
    monkeypatch.setattr(
        diamond_cli,
        "YahooClient",
        lambda: object(),
    )

    def capture_universe(*, client, cache, refresh):
        seen["universe"] = cache.root
        seen["universe_refresh"] = refresh
        return universe_provider

    def capture_market(*, client, cache, refresh):
        seen["market"] = cache.root
        seen["market_refresh"] = refresh
        return market_provider

    def capture_store(*, root, client, legacy_cache, now=None):
        seen["sec"] = root
        seen["sec_legacy"] = legacy_cache.root
        seen["sec_client"] = client
        return evidence_store

    def capture_canonical(cache):
        seen["canonical"] = cache.root
        return canonical_cache

    def capture_split(*, client, cache, refresh):
        seen["splits"] = cache.root
        seen["splits_refresh"] = refresh
        return split_provider

    def capture_provider(**kwargs):
        seen["provider_kwargs"] = kwargs
        return final_provider

    monkeypatch.setattr(
        diamond_cli,
        "Sp500UniverseProvider",
        capture_universe,
    )
    monkeypatch.setattr(
        diamond_cli,
        "YahooBatchMarketProvider",
        capture_market,
    )
    monkeypatch.setattr(
        diamond_cli,
        "SecEvidenceStore",
        capture_store,
    )
    monkeypatch.setattr(
        diamond_cli,
        "CanonicalIssuerCache",
        capture_canonical,
    )
    monkeypatch.setattr(
        diamond_cli,
        "YahooSplitAdjustmentProvider",
        capture_split,
    )
    monkeypatch.setattr(
        diamond_cli,
        "SecFirstProvider",
        capture_provider,
    )

    provider = diamond_cli._production_funnel_provider(
        tmp_path,
        refresh=refresh,
    )

    assert provider is final_provider
    assert seen["universe"] == tmp_path / "universe"
    assert seen["sec"] == tmp_path / "sec"
    assert seen["sec_legacy"] == tmp_path / "sec"
    assert seen["canonical"] == tmp_path / "canonical"
    assert seen["market"] == tmp_path / "market"
    assert seen["splits"] == tmp_path / "splits"

    assert seen["sec_client"] is sec_client
    assert seen["universe_refresh"] is refresh
    assert seen["market_refresh"] is refresh
    assert seen["splits_refresh"] is refresh

    kwargs = seen["provider_kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["universe_provider"] is universe_provider
    assert kwargs["market_provider"] is market_provider
    assert kwargs["evidence_store"] is evidence_store
    assert kwargs["canonical_cache"] is canonical_cache
    assert kwargs["split_provider"] is split_provider
    assert kwargs["refresh"] is refresh

    assert "sec_client" not in kwargs
    assert "sec_cache" not in kwargs
