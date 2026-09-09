import json
from pathlib import Path

import pytest

from qhapaq_finance import cli
from qhapaq_finance.dashboard import (
    build_company_artifact,
    build_universe_artifact,
    canonical_json,
    render_company_dashboard,
    render_universe_dashboard,
    write_artifacts,
)

ROOT = Path(__file__).parents[1]


def test_research_artifact_is_deterministic_and_classifies_cases() -> None:
    qcom = build_company_artifact("QCOM", ROOT)
    assert canonical_json(qcom) == canonical_json(build_company_artifact("QCOM", ROOT))
    assert qcom["identity"]["classification"] == "evidence-backed"
    assert qcom["economics"]["revenue_ttm"] == 44_069
    assert qcom["buy_zone"]["price_at_20_mos"] is not None
    assert qcom["provenance"] and qcom["provenance"][0]["classification"] == "FACT"
    assert build_company_artifact("VRTX", ROOT)["identity"]["classification"] == "fixture"
    assert build_company_artifact("CSCO", ROOT)["identity"]["classification"] == "fixture"


def test_artifact_output_and_offline_html(tmp_path: Path) -> None:
    written = write_artifacts(("QCOM", "VRTX", "CSCO"), tmp_path, ROOT)
    assert {"universe", "qcom", "qcom_provenance", "vrtx", "csco"} == set(written)
    payload = json.loads(written["qcom"].read_text())
    company = render_company_dashboard(payload, tmp_path / "qcom.html")
    universe = render_universe_dashboard(
        build_universe_artifact(("QCOM", "VRTX", "CSCO"), ROOT), tmp_path / "universe.html"
    )
    content = company.read_text(encoding="utf-8")
    assert "44,069m" in content and "TTM = FY - prior 9M + current 9M" in content
    assert "qhapaq-data" in content and "cdn" not in content.lower()
    assert "fetch(" not in content and "https://" not in content
    assert "function" not in content.lower()  # no dashboard valuation calculator
    assert "QCOM" in universe.read_text(encoding="utf-8")


def test_dashboard_and_json_cli_regression(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli.main(["research", "QCOM", "--json"])
    assert '"schema_version": "dashboard-research-v1"' in capsys.readouterr().out
    cli.main(["compare", "QCOM", "VRTX", "CSCO", "--json"])
    assert '"schema_version": "dashboard-universe-v1"' in capsys.readouterr().out
    cli.main(["dashboard", "QCOM", "--output-dir", str(tmp_path)])
    assert (tmp_path / "qcom-dashboard.html").is_file()
