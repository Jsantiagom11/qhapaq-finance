from pathlib import Path

import pytest

from qhapaq_finance import cli
from qhapaq_finance.universe import DomainRegistry, UniverseError, issuer_batch_plan, load_universe

ROOT = Path(__file__).parents[1]


def test_top10_snapshot_is_versioned_ordered_and_auditable() -> None:
    snapshot = load_universe("sp500-top10", ROOT)
    assert snapshot.as_of.isoformat() == "2026-08-31"
    assert snapshot.universe_id == "sp500-top10"
    assert len(snapshot.securities) == len({item.ticker for item in snapshot.securities}) == 10
    assert [item.ticker for item in snapshot.securities][:2] == ["NVDA", "AAPL"]
    assert "operator-supplied" in snapshot.provenance


def test_alphabet_securities_share_an_issuer_and_evidence_identity() -> None:
    registry = DomainRegistry(ROOT)
    assert registry.security("GOOGL").ticker != registry.security("GOOG").ticker
    assert registry.issuer_for("GOOGL") == registry.issuer_for("GOOG")
    assert registry.issuer_for("GOOGL").evidence_identity == "alphabet-inc"


def test_issuer_batch_plan_deduplicates_alphabet_and_only_admits_ready_issuers() -> None:
    registry = DomainRegistry(ROOT)
    snapshot = load_universe("sp500-top10", ROOT)
    assert len(issuer_batch_plan(snapshot, registry)) == 9
    assert [issuer.id for issuer in issuer_batch_plan(snapshot, registry, agent_only=True)] == [
        "nvidia-corporation"
    ]


def test_capability_is_derived_from_validated_local_artifacts() -> None:
    registry = DomainRegistry(ROOT)
    snapshot = load_universe("sp500-top10", ROOT)
    nvda = registry.capability("NVDA", snapshot)
    aapl = registry.capability("AAPL", snapshot)
    qcom = registry.capability("QCOM")
    vrtx = registry.capability("VRTX")
    assert (nvda.universe_member, nvda.evidence_available, nvda.agent_research_ready) == (
        True,
        True,
        True,
    )
    assert (aapl.universe_member, aapl.evidence_available, aapl.deterministic_research_ready) == (
        True,
        False,
        False,
    )
    assert qcom.evidence_available and qcom.deterministic_research_ready
    assert vrtx.research_kind == "fixture" and not vrtx.evidence_available


def test_invalid_quality_profile_is_not_research_ready(tmp_path: Path) -> None:
    registry = DomainRegistry(ROOT)
    broken = tmp_path / "quality.json"
    broken.write_text("{}", encoding="utf-8")
    registry._research["qualcomm-incorporated"]["quality_profile"] = str(broken)
    capability = registry.capability("QCOM")
    assert not capability.evidence_available
    assert not capability.deterministic_research_ready
    assert not capability.agent_research_ready


def test_unknown_and_known_but_unready_security_fail_explicitly() -> None:
    registry = DomainRegistry(ROOT)
    with pytest.raises(UniverseError, match="unknown security"):
        registry.security("NOPE")
    with pytest.raises(UniverseError, match="deterministic research unavailable"):
        registry.load_case("AAPL")


def test_cli_security_validation_has_no_ticker_choices_and_reports_unready(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        cli.main(["research", "AAPL"])
    assert "deterministic research unavailable for AAPL" in capsys.readouterr().err
    cli.main(["universe", "sp500-top10", "--agent-plan"])
    assert capsys.readouterr().out.splitlines()[-1] == "agent_issuer=nvidia-corporation"
