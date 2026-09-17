import re
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
    assert "FINANCIAL EVIDENCE VERIFIED" in rendered
    assert "STARTING CASH-FLOW BASE" in rendered
    assert "IMPORTANT LIMITATION" in rendered
    assert "HOW THE REQUIRED GROWTH CHANGES WHEN ASSUMPTIONS CHANGE" in rendered
    assert "Normalized Cash Power" not in rendered
    assert "Expectations gap" not in rendered
    assert "CLEARING HURDLE" not in rendered
    assert "UNDERWRITING" not in rendered
    assert "+62.5 pp" not in rendered
    assert "76.5%" not in rendered
    assert "TEST DIFFERENT ASSUMPTIONS" not in rendered
    assert "http://" not in rendered


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
    assert "FINANCIAL EVIDENCE UNAVAILABLE" in rendered
    assert "Build and validate a research evidence pack" in rendered
    assert "TEST DIFFERENT ASSUMPTIONS" not in rendered


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
    assert "WHAT TODAY'S VALUATION IMPLIES" in rendered
    assert "STARTING CASH-FLOW BASE" in rendered
    assert "Basis:</strong> current run-rate cash flow · not a full-cycle estimate" in rendered
    assert "Normalized Cash Power" not in rendered
    assert "Expectations gap" not in rendered
    assert "https://" not in rendered
    assert "http://" not in rendered


def test_one_html_contains_no_financial_solver(tmp_path: Path) -> None:
    """One receives reverse-DCF results from Python; it never derives them in JavaScript."""
    snapshot = _snapshot("NVDA", market_cap=None)
    model = build_one_model(
        snapshot=snapshot,
        repository_root=ROOT,
        now=snapshot.observed_at + timedelta(minutes=5),
    )
    rendered = render_one_html(model, tmp_path / "nvda.html").read_text(encoding="utf-8")

    forbidden_patterns = (
        r"function\s+pv\s*\(",
        r"function\s+solve\s*\(",
        r"Math\.pow\s*\(",
        r"terminal\s*=.*\/\s*\(.*-.*\)",
        r"for\s*\(.*(?:160|bisection|mid).*(?:pv|solve)",
    )
    for pattern in forbidden_patterns:
        assert re.search(pattern, rendered, flags=re.IGNORECASE) is None


def test_one_executive_view_keeps_base_hurdle_canonical(
    tmp_path: Path,
) -> None:
    """The executive view renders the Python-calculated base-case conclusion."""
    snapshot = _snapshot("NVDA", market_cap=None)
    model = build_one_model(
        snapshot=snapshot,
        repository_root=ROOT,
        now=snapshot.observed_at + timedelta(minutes=5),
    )
    output = render_one_html(model, tmp_path / "nvda.html")
    rendered = output.read_text(encoding="utf-8")

    expected_hurdle = f"{model.implied_fcf_growth * 100:.1f}%"
    assert f'id="executive-hurdle">{expected_hurdle}' in rendered
    assert "WHAT TODAY'S VALUATION IMPLIES" in rendered
    assert f"Under the base case, {model.company_name}'s current valuation" in rendered
    assert f"growing about {expected_hurdle} per year for the next {model.years} years." in rendered
    assert "This is not our forecast." in rendered
    assert "annual cash-flow growth" in rendered
    assert f"for {model.years} years" in rendered
    assert "BOTTOM LINE" in rendered
    assert "WHY THE CASE COULD WORK" in rendered
    assert "PRIMARY RISK" in rendered
    assert "WATCH NEXT" in rendered
    assert "EXECUTIVE TAKEAWAY" not in rendered
    assert "KEY CASE" not in rendered
    assert f"HOW QHAPAQ GETS TO {expected_hurdle}" in rendered
    executive = rendered.split('<section class="executive">', maxsplit=1)[1].split(
        '<div class="analysis-heading">', maxsplit=1
    )[0]
    assert "CoE" not in executive
    assert "TG" not in executive
    assert "RUN-RATE ONLY" not in executive
    assert "underwriting state" not in executive
    assert executive.count("What could change the case for") == 3
    assert executive.count("?") >= 3

    assert "scenario-hurdle" not in rendered


def test_one_calculation_bridge_uses_rendered_base_case_inputs_in_executive_order(
    tmp_path: Path,
) -> None:
    """The executive bridge explains the canonical result without duplicating scenario state."""
    snapshot = _snapshot("NVDA", market_cap=None)
    model = build_one_model(
        snapshot=snapshot,
        repository_root=ROOT,
        now=snapshot.observed_at + timedelta(minutes=5),
    )
    rendered = render_one_html(model, tmp_path / "nvda.html").read_text(encoding="utf-8")
    bridge = rendered.split('<section class="calculation-bridge"', maxsplit=1)[1].split(
        "</section>", maxsplit=1
    )[0]

    expected_hurdle = f"{model.implied_fcf_growth * 100:.1f}%"
    expected_cash_basis = f"${model.cash_basis_value / 1_000_000_000:.1f}B"
    assert f"HOW QHAPAQ GETS TO {expected_hurdle}" in bridge
    assert f"${snapshot.price:,.2f}" in bridge
    assert expected_cash_basis in bridge
    assert f"{model.discount_rate * 100:.1f}%" in bridge
    assert f"{model.terminal_growth * 100:.1f}%" in bridge
    assert f"IMPLIED {model.years}-YEAR CASH-FLOW GROWTH" in bridge
    assert "solves backwards" in bridge
    assert expected_hurdle in bridge
    assert "forecast" not in bridge.lower()
    assert "expected growth" not in bridge.lower()
    assert "target" not in bridge.lower()
    assert "recommendation" not in bridge.lower()


def test_one_labels_nondefault_reverse_dcf_inputs_as_base_case_assumptions(
    tmp_path: Path,
) -> None:
    """The bridge must distinguish observed, evidence-based, assumed, and solved values."""
    snapshot = _snapshot("NVDA", market_cap=None)
    model = build_one_model(
        snapshot=snapshot,
        repository_root=ROOT,
        now=snapshot.observed_at + timedelta(minutes=5),
        discount_rate=0.11,
        terminal_growth=0.025,
    )
    rendered = render_one_html(model, tmp_path / "nvda.html").read_text(encoding="utf-8")
    bridge = rendered.split('<section class="calculation-bridge"', maxsplit=1)[1].split(
        "</section>", maxsplit=1
    )[0]

    assert "11.0%" in rendered
    assert "2.5%" in rendered
    assert "Base-case assumption used to discount future shareholder cash flows." in rendered
    assert (
        "Base-case assumption used after the explicit 10-year period to calculate terminal value."
        in rendered
    )
    assert "Market observation" in bridge
    assert "Evidence-backed current run-rate basis" in bridge
    assert bridge.count("Base-case assumption") == 2
    assert "Model result" in bridge
    assert "forecast" not in bridge.lower()


def test_one_executive_trust_and_market_labels_only_claim_supported_states(tmp_path: Path) -> None:
    """Unsupported market or evidence state must stay explicit instead of becoming a pass badge."""
    snapshot = _snapshot("ZZZZ", market_cap=5_500_000_000_000.0)
    model = build_one_model(
        snapshot=snapshot,
        repository_root=ROOT,
        now=snapshot.observed_at + timedelta(days=1),
    )
    rendered = render_one_html(model, tmp_path / "unknown.html").read_text(encoding="utf-8")

    assert "MARKET DATA STALE" in rendered
    assert "MARKET OBSERVATION FRESH" not in rendered
    assert "FINANCIAL EVIDENCE UNAVAILABLE" in rendered
    assert "FINANCIAL EVIDENCE VERIFIED" not in rendered
    assert "VALUATION MODEL NOT SOLVED" in rendered
    assert "UNKNOWN" not in rendered.split("<section", maxsplit=1)[0]


def test_one_uses_readable_analytical_labels_without_changing_values(tmp_path: Path) -> None:
    """Presentation changes must retain the canonical sensitivity and cash bridge numbers."""
    snapshot = _snapshot("NVDA", market_cap=None)
    model = build_one_model(
        snapshot=snapshot,
        repository_root=ROOT,
        now=snapshot.observed_at + timedelta(minutes=5),
    )
    rendered = render_one_html(model, tmp_path / "nvda.html").read_text(encoding="utf-8")

    assert "Rows: required return" in rendered
    assert "Columns: long-run growth after year 10" in rendered
    assert "8% return" in rendered
    assert "3% long-run" in rendered
    assert "HOW THE STARTING CASH-FLOW BASE IS BUILT" in rendered
    assert "Reported 6-month free-cash-flow proxy" in rendered
    assert "Adjusted 6-month cash base" in rendered
    assert "ADJUSTMENTS TO THE PERIOD CASH BASE" in rendered
    assert "Stock-based compensation cost" in rendered
    assert "$-3,954,000,000.00" not in rendered
    assert re.search(r"−\$[0-9.]+B", rendered)
    for expected in ("9.6%", "8.0%", "6.0%", "11.9%", "10.5%", "8.9%", "14.0%", "12.9%", "11.5%"):
        assert f">{expected}</td>" in rendered
    assert "Reported FCF proxy" in rendered
    assert "+$24.8B" in rendered
    assert "Stock-based compensation cost" in rendered
    assert "−$4.0B" in rendered


def test_one_footer_and_invalidation_are_plain_language_audit_content(tmp_path: Path) -> None:
    """The audit layer remains available without developer-facing abbreviations."""
    snapshot = _snapshot("NVDA", market_cap=None)
    model = build_one_model(
        snapshot=snapshot,
        repository_root=ROOT,
        now=snapshot.observed_at + timedelta(minutes=5),
    )
    rendered = render_one_html(model, tmp_path / "nvda.html").read_text(encoding="utf-8")

    assert "WHAT WOULD MAKE US RECONSIDER" in rendered
    assert "DATA &amp; METHODOLOGY" in rendered
    assert "Market data:" in rendered
    assert "Financial evidence:" in rendered
    assert (
        "Qhapaq does not currently store a company- or market-specific derivation for these values."
        in rendered
    )
    assert "Qhapaq is research software, not investment advice." in rendered
    assert "WACC" not in rendered


def test_one_responsive_executive_layout_preserves_information_and_trust_order(
    tmp_path: Path,
) -> None:
    """A desktop layout regression must not narrow, reorder, or hide executive evidence."""
    snapshot = _snapshot("NVDA", market_cap=None)
    model = build_one_model(
        snapshot=snapshot,
        repository_root=ROOT,
        now=snapshot.observed_at + timedelta(minutes=5),
    )
    rendered = render_one_html(model, tmp_path / "nvda.html").read_text(encoding="utf-8")

    executive_order = [
        "WHAT TODAY'S VALUATION IMPLIES",
        "BASE ASSUMPTIONS",
        "FINANCIAL EVIDENCE VERIFIED",
        "BOTTOM LINE",
        "WHY THE CASE COULD WORK",
        "PRIMARY RISK",
        "WATCH NEXT",
        "HOW QHAPAQ GETS TO",
        "DATA &amp; METHODOLOGY",
    ]
    positions = [rendered.index(label) for label in executive_order]
    assert positions == sorted(positions)
    assert "--max: clamp(0px, 78vw, 1500px)" in rendered
    assert "grid-template-columns: minmax(0, 1.9fr) minmax(280px, 1fr)" in rendered
    assert "@media (max-width: 1279px)" in rendered
    assert "@media (max-width: 767px)" in rendered
    assert re.search(
        r"\.trust-strip \{[^}]*grid-template-columns: repeat\(4, minmax\(0, 1fr\)\)",
        rendered,
    )
    assert re.search(
        r"\.trust-strip \{[^}]*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)",
        rendered,
    )
    assert re.search(r"\.trust-strip \{[^}]*grid-template-columns: 1fr", rendered)
    assert re.search(
        r"\.calculation-inputs \{[^}]*grid-template-columns: repeat\(4, minmax\(0, 1fr\)\)",
        rendered,
    )
    assert re.search(
        r"\.calculation-inputs \{[^}]*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)",
        rendered,
    )
    assert ".executive,\n  .case-risk" in rendered
    assert ".sensitivity-scroll { overflow-x: auto;" in rendered
    mobile_css = rendered.split("@media (max-width: 767px)", maxsplit=1)[1].split(
        "</style>", maxsplit=1
    )[0]
    assert "display: none" not in mobile_css
    assert "http://" not in rendered
    assert "https://" not in rendered


def test_one_uses_two_surfaces_with_calculation_bridge_in_reading_order(
    tmp_path: Path,
) -> None:
    """The rendered DOM keeps the decision path ahead of analytical detail."""
    snapshot = _snapshot("NVDA", market_cap=None)
    model = build_one_model(
        snapshot=snapshot,
        repository_root=ROOT,
        now=snapshot.observed_at + timedelta(minutes=5),
    )
    rendered = render_one_html(model, tmp_path / "nvda.html").read_text(encoding="utf-8")

    editorial = rendered.split('<div class="reading-surface">', maxsplit=1)[1].split(
        "</div>\n\n<script>", maxsplit=1
    )[0]
    blocks_in_required_order = [
        '<section class="trust-strip"',
        '<section class="bottom-line">',
        '<section class="case-risk">',
        '<div class="label">WATCH NEXT</div>',
        '<section class="calculation-bridge"',
        '<section class="section metric-grid">',
        '<footer class="foot">',
    ]
    positions = [rendered.index(block) for block in blocks_in_required_order]
    assert positions == sorted(positions)
    assert "BOTTOM LINE" not in editorial
    assert "HOW QHAPAQ GETS TO" in editorial
    assert editorial.index("WATCH NEXT") < editorial.index("HOW QHAPAQ GETS TO")
    assert editorial.index("HOW QHAPAQ GETS TO") < editorial.index(
        "HOW THE REQUIRED GROWTH CHANGES WHEN ASSUMPTIONS CHANGE"
    )
    assert editorial.index(
        "HOW THE REQUIRED GROWTH CHANGES WHEN ASSUMPTIONS CHANGE"
    ) < editorial.index("DATA &amp; METHODOLOGY")
    assert "--paper: #E4E0D6" in rendered
    assert "--paper-elevated: #ECE8DE" in rendered
    assert "--rule-paper: #C5BEB3" in rendered
    assert "--paper-ink: #202124" in rendered
    assert ".reading-surface {" in rendered
    assert "transition-bridge" not in rendered


def test_one_surface_boundary_has_no_transition_effect_or_document_overflow(
    tmp_path: Path,
) -> None:
    """Paper follows charcoal directly; only analytical tables may scroll horizontally."""
    snapshot = _snapshot("NVDA", market_cap=None)
    model = build_one_model(
        snapshot=snapshot,
        repository_root=ROOT,
        now=snapshot.observed_at + timedelta(minutes=5),
    )
    rendered = render_one_html(model, tmp_path / "nvda.html").read_text(encoding="utf-8")

    assert "gradient" not in rendered
    assert "box-shadow" not in rendered
    assert "100vmax" not in rendered
    assert "100vw" not in rendered
    assert ".reading-surface::" not in rendered
    assert ".sensitivity-scroll { overflow-x: auto;" in rendered
    assert "overflow-x: auto" not in rendered.replace(
        ".sensitivity-scroll { overflow-x: auto; -webkit-overflow-scrolling: touch; }", ""
    )


def test_one_crisp_editorial_css_keeps_signal_color_and_quiet_structure(
    tmp_path: Path,
) -> None:
    """The rendered brief must retain its restrained editorial visual system."""
    snapshot = _snapshot("NVDA", market_cap=None)
    model = build_one_model(
        snapshot=snapshot,
        repository_root=ROOT,
        now=snapshot.observed_at + timedelta(minutes=5),
    )
    rendered = render_one_html(model, tmp_path / "nvda.html").read_text(encoding="utf-8")

    for token in (
        "--charcoal: #111315",
        "--paper: #E4E0D6",
        "--paper-elevated: #ECE8DE",
        "--paper-ink: #202124",
        "--terracotta: #C66A45",
        "--terracotta-soft: #B97A61",
        "--rule-dark: #343536",
        "--rule-paper: #C5BEB3",
    ):
        assert token in rendered

    assert "gradient" not in rendered
    assert "border-radius: 999px" not in rendered
    assert "border-radius: 12px" not in rendered
    assert (
        ".decision-grid > *,\n.bridge-grid > *,\n.columns > *,\n.executive > * { min-width: 0; }"
        in rendered
    )
    assert ".sensitivity-scroll { overflow-x: auto;" in rendered
    assert ".calculation-bridge { margin-top: 18px; padding-top: 18px; border-top:" in rendered
    assert ".bottom-line { margin-top: 26px; padding: 18px 0 0; }" in rendered
    assert ".bottom-line .label { color: var(--terracotta); }" in rendered
    trust_strip = re.search(r"\.trust-strip \{(?P<rules>[^}]*)\}", rendered)
    trust_item = re.search(r"\.trust-item \{(?P<rules>[^}]*)\}", rendered)
    assert trust_strip is not None
    assert trust_item is not None
    assert "border" not in trust_strip["rules"]
    assert "border" not in trust_item["rules"]
