from dataclasses import replace
from pathlib import Path

import pytest

from qhapaq_finance.dashboard import build_company_artifact, render_company_dashboard
from qhapaq_finance.sensitivity import _cell, sensitivity_matrices
from qhapaq_finance.valuation import analyze_case, load_fixture_case

ROOT = Path(__file__).parents[1]


def test_sensitivity_is_deterministic_and_base_cell_matches_base_case() -> None:
    case = load_fixture_case("QCOM", ROOT)
    matrices = sensitivity_matrices(case)
    terminal = matrices["wacc_terminal_growth"]
    growth = matrices["wacc_explicit_growth"]
    assert matrices == sensitivity_matrices(case)
    assert terminal["cells"][2][2] == pytest.approx(
        next(
            item for item in analyze_case(case).scenarios if item.name == "base"
        ).intrinsic_value_per_share
    )
    assert growth["cells"][2][2] == pytest.approx(terminal["cells"][2][2])


def test_sensitivity_monotonicity_and_invalid_terminal_cells() -> None:
    matrices = sensitivity_matrices(load_fixture_case("QCOM", ROOT))
    terminal = matrices["wacc_terminal_growth"]
    growth = matrices["wacc_explicit_growth"]
    for row in terminal["cells"]:
        valid = [value for value in row if value is not None]
        assert valid == sorted(valid)
    for column in range(5):
        values = [row[column] for row in growth["cells"]]
        assert all(left >= right for left, right in zip(values[:-1], values[1:], strict=True))
    for row in growth["cells"]:
        assert all(left <= right for left, right in zip(row[:-1], row[1:], strict=True))
    base = next(item for item in load_fixture_case("QCOM", ROOT).scenarios if item.name == "base")
    case = load_fixture_case("QCOM", ROOT)
    assert (
        _cell(case, replace(base, terminal_growth=case.capital_cost.wacc), case.capital_cost.wacc)
        is None
    )


def test_dashboard_serializes_and_renders_sensitivity_and_zones(tmp_path: Path) -> None:
    artifact = build_company_artifact("QCOM", ROOT)
    assert artifact["decision_zones"]["classification"] == "ABOVE FAIR VALUE"
    assert artifact["sensitivity"]["wacc_terminal_growth"]["cells"]
    output = render_company_dashboard(artifact, tmp_path / "qcom.html")
    html = output.read_text(encoding="utf-8")
    assert "WACC × terminal growth" in html
    assert "valuation distance" in html
    assert "fetch(" not in html and "https://" not in html
