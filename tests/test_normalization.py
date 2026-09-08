from datetime import date
from pathlib import Path

import pytest

from qhapaq_finance.normalization import (
    CashBasisKind,
    NormalizationError,
    calculate_run_rate_cash_basis,
    load_cash_basis,
)
from qhapaq_finance.research import load_research_record

ROOT = Path(__file__).parents[1]


def _record(ticker: str, as_of: date):
    directory = ROOT / "data" / "research" / ticker.lower()
    return load_research_record(
        record_path=directory / "research.json",
        manifest_path=directory / "manifest.json",
        repository_root=ROOT,
        as_of=as_of,
    )


def test_nvda_run_rate_cash_bridge() -> None:
    record = _record("NVDA", date(2026, 8, 26))
    result = load_cash_basis(
        record=record,
        path=ROOT / "data" / "research" / "nvda" / "normalization.json",
    )

    assert result.basis_kind is CashBasisKind.RUN_RATE
    assert result.reported_period_fcf == pytest.approx(69_987.0)
    assert result.working_capital_current == pytest.approx(-27_164.0)
    assert result.working_capital_prior == pytest.approx(-2_368.0)
    assert result.working_capital_adjustment == pytest.approx(24_796.0)
    assert result.timing_adjustment == pytest.approx(0.0)
    assert result.sbc_adjustment == pytest.approx(-3_954.0)
    assert result.run_rate_period_cash == pytest.approx(90_829.0)
    assert result.run_rate_annualized_cash == pytest.approx(181_658.0)
    assert result.shares_outstanding == pytest.approx(24_100_000_000.0)


def test_qcom_run_rate_cash_bridge() -> None:
    record = _record("QCOM", date(2026, 9, 1))
    result = load_cash_basis(
        record=record,
        path=ROOT / "data" / "research" / "qcom" / "normalization.json",
    )

    assert result.basis_kind is CashBasisKind.RUN_RATE
    assert result.reported_period_fcf == pytest.approx(6_827.0)
    assert result.working_capital_current == pytest.approx(-1_130.0)
    assert result.working_capital_prior == pytest.approx(-231.0)
    assert result.working_capital_adjustment == pytest.approx(899.0)
    assert result.timing_adjustment == pytest.approx(4_015.0)
    assert result.sbc_adjustment == pytest.approx(-2_579.0)
    assert result.run_rate_period_cash == pytest.approx(9_162.0)
    assert result.run_rate_annualized_cash == pytest.approx(12_216.0)
    assert result.shares_outstanding == pytest.approx(1_050_000_000.0)


def test_micron_peak_trough_proves_run_rate_is_not_cycle_normalization() -> None:
    """Reproduce the FY2022/FY2023 Micron stress case from its 2023 Form 10-K.

    The same timing-normalization formula yields positive cash at the FY2022 cycle peak
    and deeply negative cash one year later. This regression test exists to prevent the
    product from ever relabeling the run-rate bridge as a through-cycle cash estimate.
    """
    fy2022 = calculate_run_rate_cash_basis(
        operating_cash_flow=15_181.0,
        capex=12_067.0,
        working_capital_current=-1_263.0,
        working_capital_prior=-440.0,
        timing_adjustment=0.0,
        sbc_expense=514.0,
        annualization_factor=1.0,
    )
    fy2023 = calculate_run_rate_cash_basis(
        operating_cash_flow=1_559.0,
        capex=7_676.0,
        working_capital_current=-2_903.0,
        working_capital_prior=-1_263.0,
        timing_adjustment=0.0,
        sbc_expense=596.0,
        annualization_factor=1.0,
    )

    assert fy2022.run_rate_annualized_cash == pytest.approx(3_423.0)
    assert fy2023.run_rate_annualized_cash == pytest.approx(-5_073.0)
    assert fy2022.run_rate_annualized_cash > 0 > fy2023.run_rate_annualized_cash


def test_cash_basis_fails_closed_on_unknown_source(tmp_path: Path) -> None:
    record = _record("NVDA", date(2026, 8, 26))
    source = ROOT / "data" / "research" / "nvda" / "normalization.json"
    payload = source.read_text(encoding="utf-8").replace(
        '"source_id": "nvda-2026-q2-10q-capsule"',
        '"source_id": "unknown-source"',
        1,
    )
    path = tmp_path / "normalization.json"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(NormalizationError, match="unknown source_id"):
        load_cash_basis(record=record, path=path)


def test_through_cycle_label_is_not_accepted_without_methodology(tmp_path: Path) -> None:
    record = _record("NVDA", date(2026, 8, 26))
    source = ROOT / "data" / "research" / "nvda" / "normalization.json"
    payload = source.read_text(encoding="utf-8").replace(
        '"basis_kind": "run_rate"', '"basis_kind": "through_cycle"', 1
    )
    path = tmp_path / "normalization.json"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(NormalizationError, match="unsupported basis_kind"):
        load_cash_basis(record=record, path=path)
