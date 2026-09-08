from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from qhapaq_finance.market import MarketSnapshot, MarketState
from qhapaq_finance.one import build_one_model, render_one_html

ROOT = Path(__file__).parents[1]


def _snapshot(ticker: str, *, market_cap: float | None) -> MarketSnapshot:
    observed = datetime(2026, 9, 7, 20, 0, tzinfo=timezone.utc)
    return MarketSnapshot(
        ticker=ticker,
        price=230.36 if ticker == "NVDA" else 170.0,
        currency="USD",
        observed_at=observed,
        retrieved_at=observed + timedelta(minutes=1),
        source="fixture",
        market_state=MarketState.CLOSED,
        previous_close=228.10 if ticker == "NVDA" else 168.0,
        market_cap=market_cap,
    )


def test_qcom_one_exposes_run_rate_limit_instead_of_full_underwriting() -> None:
    snapshot = _snapshot("QCOM", market_cap=200_000_000_000.0)
    model = build_one_model(
        snapshot=snapshot,
        repository_root=ROOT,
        now=snapshot.observed_at + timedelta(minutes=5),
    )

    assert model.research_ready is True
    assert model.company_name == "QUALCOMM Incorporated"
    assert model.status == "RUN-RATE ONLY"
    assert model.cash_basis is not None
    assert model.cash_basis_value == pytest.approx(12_216_000_000.0)
    assert model.effective_market_cap == 200_000_000_000.0
    assert model.implied_fcf_growth == pytest.approx(0.02378, abs=0.0001)
    assert len(model.sensitivity) == 9
    assert model.thesis
    assert model.counterthesis
    assert len(model.invalidation) == 3
    assert len(model.what_matters) == 3


def test_nvda_one_uses_run_rate_cash_when_provider_omits_market_cap(tmp_path: Path) -> None:
    snapshot = _snapshot("NVDA", market_cap=None)
    model = build_one_model(
        snapshot=snapshot,
        repository_root=ROOT,
        now=snapshot.observed_at + timedelta(minutes=5),
    )
    output = render_one_html(model, tmp_path / "nvda.html")
    rendered = output.read_text(encoding="utf-8")

    assert model.research_ready is True
    assert model.company_name == "NVIDIA Corporation"
    assert model.status == "RUN-RATE ONLY"
    assert model.cash_basis is not None
    assert model.cash_basis_value == pytest.approx(181_658_000_000.0)
    assert model.effective_market_cap == pytest.approx(5_551_676_000_000.0)
    assert model.market_cap_provenance == "derived · observed price × filing shares"
    assert model.implied_fcf_growth == pytest.approx(0.10539, abs=0.0001)
    assert len(model.sensitivity) == 9
    assert "VERIFIED" in rendered
    assert "Analytical cash basis" in rendered
    assert "RUN-RATE BASIS ONLY" in rendered
    assert "cycle not validated" in rendered
    assert "Sensitivity" in rendered
    assert "Cost of equity" in rendered
    assert "Normalized Cash Power" not in rendered
    assert "Expectations gap" not in rendered
    assert "CLEARING HURDLE" not in rendered
    assert "UNDERWRITING" not in rendered
    assert "+62.5 pp" not in rendered
    assert "76.5%" not in rendered
    assert 'scenario-toggle" disabled' not in rendered


def test_missing_research_stays_explicit_for_unknown_ticker(tmp_path: Path) -> None:
    snapshot = _snapshot("ZZZZ", market_cap=5_500_000_000_000.0)
    model = build_one_model(
        snapshot=snapshot,
        repository_root=ROOT,
        now=snapshot.observed_at + timedelta(minutes=5),
    )
    output = render_one_html(model, tmp_path / "unknown.html")
    rendered = output.read_text(encoding="utf-8")

    assert model.research_ready is False
    assert model.status == "INSUFFICIENT DATA"
    assert model.implied_fcf_growth is None
    assert model.cash_basis is None
    assert "INSUFFICIENT DATA" in rendered
    assert "Build and validate a research evidence pack" in rendered
    assert 'scenario-toggle" disabled' in rendered


def test_one_render_is_byte_deterministic_for_same_model(tmp_path: Path) -> None:
    snapshot = _snapshot("NVDA", market_cap=None)
    model = build_one_model(
        snapshot=snapshot,
        repository_root=ROOT,
        now=snapshot.observed_at + timedelta(minutes=5),
    )
    first = render_one_html(model, tmp_path / "a.html")
    second = render_one_html(model, tmp_path / "b.html")

    assert first.read_bytes() == second.read_bytes()
    rendered = first.read_text(encoding="utf-8")
    assert "QHAPAQ ONE" in rendered
    assert "Market requires" in rendered
    assert "Analytical cash basis" in rendered
    assert "RUN-RATE ONLY" in rendered
    assert "Normalized Cash Power" not in rendered
    assert "Expectations gap" not in rendered
    assert "https://" not in rendered
