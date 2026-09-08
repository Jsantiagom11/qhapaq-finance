from datetime import date
from pathlib import Path

import pytest

from qhapaq_finance.normalization import NormalizationError, load_normalized_cash
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


def test_nvda_normalized_cash_power_bridge() -> None:
    record = _record("NVDA", date(2026, 8, 26))
    result = load_normalized_cash(
        record=record,
        path=ROOT / "data" / "research" / "nvda" / "normalization.json",
    )

    assert result.reported_period_fcf == pytest.approx(69_987.0)
    assert result.working_capital_current == pytest.approx(-27_164.0)
    assert result.working_capital_prior == pytest.approx(-2_368.0)
    assert result.working_capital_adjustment == pytest.approx(24_796.0)
    assert result.timing_adjustment == pytest.approx(0.0)
    assert result.sbc_adjustment == pytest.approx(-3_954.0)
    assert result.normalized_period_fcf == pytest.approx(90_829.0)
    assert result.normalized_annualized_fcf == pytest.approx(181_658.0)
    assert result.shares_outstanding == pytest.approx(24_100_000_000.0)


def test_qcom_normalized_cash_power_bridge() -> None:
    record = _record("QCOM", date(2026, 9, 1))
    result = load_normalized_cash(
        record=record,
        path=ROOT / "data" / "research" / "qcom" / "normalization.json",
    )

    assert result.reported_period_fcf == pytest.approx(6_827.0)
    assert result.working_capital_current == pytest.approx(-1_130.0)
    assert result.working_capital_prior == pytest.approx(-231.0)
    assert result.working_capital_adjustment == pytest.approx(899.0)
    assert result.timing_adjustment == pytest.approx(4_015.0)
    assert result.sbc_adjustment == pytest.approx(-2_579.0)
    assert result.normalized_period_fcf == pytest.approx(9_162.0)
    assert result.normalized_annualized_fcf == pytest.approx(12_216.0)
    assert result.shares_outstanding == pytest.approx(1_050_000_000.0)


def test_normalization_fails_closed_on_unknown_source(tmp_path: Path) -> None:
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
        load_normalized_cash(record=record, path=path)
