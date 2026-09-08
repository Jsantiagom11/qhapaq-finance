from datetime import datetime, timedelta, timezone
from pathlib import Path

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


def test_qcom_one_uses_validated_research_and_market_expectations() -> None:
    snapshot = _snapshot("QCOM", market_cap=200_000_000_000.0)
    model = build_one_model(
        snapshot=snapshot,
        repository_root=ROOT,
        now=snapshot.observed_at + timedelta(minutes=5),
    )

    assert model.research_ready is True
    assert model.company_name == "QUALCOMM Incorporated"
    assert model.status == "UNDERWRITING"
    assert model.starting_fcf == 12_820_000_000.0
    assert model.implied_fcf_growth is not None
    assert model.thesis
    assert model.counterthesis
    assert len(model.invalidation) == 3
    assert len(model.what_matters) == 3


def test_missing_research_stays_explicit_for_nvda(tmp_path: Path) -> None:
    snapshot = _snapshot("NVDA", market_cap=5_500_000_000_000.0)
    model = build_one_model(
        snapshot=snapshot,
        repository_root=ROOT,
        now=snapshot.observed_at + timedelta(minutes=5),
    )
    output = render_one_html(model, tmp_path / "nvda.html")
    rendered = output.read_text(encoding="utf-8")

    assert model.research_ready is False
    assert model.status == "INSUFFICIENT DATA"
    assert model.implied_fcf_growth is None
    assert "INSUFFICIENT DATA" in rendered
    assert "Build and validate a primary-evidence research pack" in rendered
    assert 'scenario-toggle" disabled' in rendered


def test_one_render_is_byte_deterministic_for_same_model(tmp_path: Path) -> None:
    snapshot = _snapshot("QCOM", market_cap=200_000_000_000.0)
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
    assert "Market expects" in rendered
    assert "UNDERWRITING" in rendered
    assert "https://" not in rendered
