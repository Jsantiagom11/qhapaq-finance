from datetime import date
from pathlib import Path

import pytest

from qhapaq_finance.dashboard.serializer import build_company_artifact
from qhapaq_finance.market_inputs import MarketInputError, canonical_market_input
from qhapaq_finance.nvda_case import load_nvda_case
from qhapaq_finance.qcom_case import load_qcom_case

ROOT = Path(__file__).parents[1]


def test_nvda_uses_canonical_market_input_and_qcom_has_no_profile() -> None:
    nvda = canonical_market_input(
        root=ROOT, ticker="NVDA", evaluation_as_of=date(2026, 9, 8), valuation_shares=24_100
    )
    assert nvda is not None and nvda.source_kind == "canonical"
    assert nvda.provenance(date(2026, 9, 8)).source_manifest_identity
    case = load_nvda_case(ROOT)
    assert case.market_snapshot.price == nvda.price
    assert (
        canonical_market_input(
            root=ROOT, ticker="QCOM", evaluation_as_of=date(2026, 9, 8), valuation_shares=1_050
        )
        is None
    )
    assert load_qcom_case(ROOT).market_snapshot.price == pytest.approx(168.6358)


def test_declared_broken_profile_never_falls_back(tmp_path: Path) -> None:
    registry = ROOT / "data/domain/issuers.json"
    payload = registry.read_text(encoding="utf-8").replace(
        "data/research/nvda/market-quality-profile.json", "missing.json"
    )
    copied = tmp_path / "data/domain"
    copied.mkdir(parents=True)
    (copied / "issuers.json").write_text(payload, encoding="utf-8")
    # Declared canonical evidence fails closed when its artifact is unavailable.
    with pytest.raises(MarketInputError, match="MARKET_QUALITY_FAILED"):
        canonical_market_input(
            root=tmp_path, ticker="NVDA", evaluation_as_of=date(2026, 9, 8), valuation_shares=24_100
        )


def test_case_and_artifact_preserve_generic_source_modes() -> None:
    nvda = load_nvda_case(ROOT).market_provenance
    qcom = load_qcom_case(ROOT).market_provenance
    assert nvda is not None and nvda.source_mode == "canonical" and nvda.market_quality_identity
    assert nvda.content_identity == nvda.content_identity
    assert (
        qcom is not None and qcom.source_mode == "legacy" and qcom.market_quality_identity is None
    )
    assert (
        build_company_artifact("NVDA", ROOT)["market"]["provenance"]["source_mode"] == "canonical"
    )
    assert build_company_artifact("QCOM", ROOT)["market"]["provenance"]["source_mode"] == "legacy"
    assert build_company_artifact("VRTX", ROOT)["market"]["provenance"]["source_mode"] == "fixture"
