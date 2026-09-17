"""Qhapaq One: a single-view market expectations product."""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from importlib.resources import files
from pathlib import Path
from zoneinfo import ZoneInfo

from .expectations import (
    ExpectationsError,
    ReverseDcfInputs,
    SensitivityPoint,
    reverse_dcf_sensitivity,
    solve_implied_fcf_growth,
)
from .market import Freshness, FreshnessPolicy, MarketSnapshot, classify_freshness
from .normalization import CashBasisResult, CashBridgeItem, load_cash_basis
from .research import ResearchRecord, load_research_record


@dataclass(frozen=True)
class OneModel:
    ticker: str
    company_name: str
    snapshot: MarketSnapshot
    freshness: Freshness
    evidence_as_of: date | None
    research_ready: bool
    cash_basis: CashBasisResult | None
    cash_basis_value: float | None
    effective_market_cap: float | None
    market_cap_provenance: str
    implied_fcf_growth: float | None
    sensitivity: tuple[SensitivityPoint, ...]
    discount_rate: float
    terminal_growth: float
    years: int
    status: str
    status_detail: str
    thesis: str | None
    counterthesis: str | None
    invalidation: tuple[str, ...]
    what_matters: tuple[str, ...]


def _research_paths(root: Path, ticker: str) -> tuple[Path, Path]:
    directory = root / "data" / "research" / ticker.lower()
    return directory / "research.json", directory / "manifest.json"


def _cash_basis_path(root: Path, ticker: str) -> Path:
    return root / "data" / "research" / ticker.lower() / "normalization.json"


def _research_as_of(record_path: Path) -> date:
    try:
        payload = json.loads(record_path.read_text(encoding="utf-8"))
        raw = payload["as_of"]
        parsed = datetime.strptime(raw, "%Y-%m-%d").date()
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid research as_of in {record_path}") from exc
    if parsed.isoformat() != raw:
        raise ValueError(f"research as_of must use YYYY-MM-DD in {record_path}")
    return parsed


def _load_research(root: Path, ticker: str) -> ResearchRecord | None:
    record_path, manifest_path = _research_paths(root, ticker)
    if not record_path.is_file() or not manifest_path.is_file():
        return None
    as_of = _research_as_of(record_path)
    return load_research_record(
        record_path=record_path,
        manifest_path=manifest_path,
        repository_root=root,
        as_of=as_of,
    )


def _fact_value(record: ResearchRecord, fact_id: str | None) -> float | None:
    if not fact_id:
        return None
    for fact in record.facts:
        if fact.id == fact_id:
            return fact.value
    return None


def _load_cash_basis(
    root: Path, ticker: str, record: ResearchRecord | None
) -> CashBasisResult | None:
    if record is None:
        return None
    path = _cash_basis_path(root, ticker)
    if not path.is_file():
        return None
    return load_cash_basis(record=record, path=path)


def _effective_market_cap(
    snapshot: MarketSnapshot,
    record: ResearchRecord | None,
    cash_basis: CashBasisResult | None,
) -> tuple[float | None, str]:
    if snapshot.market_cap is not None:
        return snapshot.market_cap, f"provider market cap · {snapshot.source}"
    if cash_basis and cash_basis.shares_outstanding:
        return (
            snapshot.price * cash_basis.shares_outstanding,
            "derived · observed price × filing shares",
        )
    if record is None:
        return None, "unavailable"
    shares = _fact_value(record, record.valuation.get("shares_outstanding_fact_id"))
    if shares is None or shares <= 0:
        return None, "unavailable"
    return snapshot.price * shares, "derived · observed price × filing shares"


def _interpretation(record: ResearchRecord, kind: str) -> str | None:
    for item in record.interpretations:
        if item.get("kind") == kind:
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
    return None


def build_one_model(
    *,
    snapshot: MarketSnapshot,
    repository_root: str | Path = ".",
    max_age: timedelta = timedelta(minutes=30),
    now: datetime | None = None,
    discount_rate: float = 0.09,
    terminal_growth: float = 0.03,
    years: int = 10,
) -> OneModel:
    """Build a concise decision model while failing closed on unsupported cash bases."""
    root = Path(repository_root).resolve()
    reference = now or datetime.now(timezone.utc)
    freshness = classify_freshness(
        snapshot,
        policy=FreshnessPolicy(max_age=max_age),
        now=reference,
    )
    record = _load_research(root, snapshot.ticker)
    cash_basis = _load_cash_basis(root, snapshot.ticker, record)
    company_name = record.issuer.get("name", snapshot.ticker) if record else snapshot.ticker
    cash_basis_value = (
        cash_basis.run_rate_annualized_cash * 1_000_000.0 if cash_basis is not None else None
    )
    effective_market_cap, market_cap_provenance = _effective_market_cap(
        snapshot, record, cash_basis
    )

    implied_growth: float | None = None
    sensitivity: tuple[SensitivityPoint, ...] = ()
    if cash_basis_value is not None and effective_market_cap is not None:
        try:
            implied_growth = solve_implied_fcf_growth(
                ReverseDcfInputs(
                    equity_value=effective_market_cap,
                    starting_fcf=cash_basis_value,
                    discount_rate=discount_rate,
                    terminal_growth=terminal_growth,
                    years=years,
                )
            ).implied_fcf_growth
            sensitivity = reverse_dcf_sensitivity(
                equity_value=effective_market_cap,
                starting_fcf=cash_basis_value,
                years=years,
            )
        except ExpectationsError:
            implied_growth = None
            sensitivity = ()

    if record is None:
        status = "INSUFFICIENT DATA"
        status_detail = "Market state is available, but no validated research evidence pack exists."
    elif cash_basis is None:
        status = "INSUFFICIENT DATA"
        status_detail = (
            "Research is validated, but no evidence-backed analytical cash basis exists."
        )
    elif effective_market_cap is None:
        status = "INSUFFICIENT DATA"
        status_detail = "Research is validated, but no usable equity-value input is available."
    elif implied_growth is None:
        status = "INSUFFICIENT DATA"
        status_detail = (
            "Cash basis and equity value exist, but the reverse-DCF hurdle could not be solved "
            "under this scenario."
        )
    else:
        status = "RUN-RATE ONLY"
        status_detail = (
            f"At {discount_rate * 100:.1f}% cost of equity and {terminal_growth * 100:.1f}% "
            f"terminal growth, the observed equity value requires {implied_growth * 100:.1f}% "
            f"annual growth from the current run-rate cash basis over {years} years. "
            "Cycle durability is not validated; this is not a full-cycle underwriting state."
        )

    thesis = _interpretation(record, "thesis") if record else None
    counterthesis = _interpretation(record, "counterthesis") if record else None
    invalidation = tuple(record.invalidation[:3]) if record else ()
    what_matters = (
        tuple(
            _watch_question(str(risk.get("title", "")), str(risk.get("mechanism", "")))
            for risk in record.risks[:3]
        )
        if record
        else ()
    )

    return OneModel(
        ticker=snapshot.ticker,
        company_name=company_name,
        snapshot=snapshot,
        freshness=freshness,
        evidence_as_of=record.as_of if record else None,
        research_ready=record is not None,
        cash_basis=cash_basis,
        cash_basis_value=cash_basis_value,
        effective_market_cap=effective_market_cap,
        market_cap_provenance=market_cap_provenance,
        implied_fcf_growth=implied_growth,
        sensitivity=sensitivity,
        discount_rate=discount_rate,
        terminal_growth=terminal_growth,
        years=years,
        status=status,
        status_detail=status_detail,
        thesis=thesis,
        counterthesis=counterthesis,
        invalidation=invalidation,
        what_matters=what_matters,
    )


def _money(value: float | None, currency: str = "USD") -> str:
    if value is None:
        return "—"
    sign = "−" if value < 0 else ""
    absolute = abs(value)
    prefix = "$" if currency.upper() == "USD" else f"{currency.upper()} "
    if absolute >= 1_000_000_000_000:
        return f"{sign}{prefix}{absolute / 1_000_000_000_000:.2f}T"
    if absolute >= 1_000_000_000:
        return f"{sign}{prefix}{absolute / 1_000_000_000:.1f}B"
    if absolute >= 1_000_000:
        return f"{sign}{prefix}{absolute / 1_000_000:.1f}M"
    return f"{sign}{prefix}{absolute:,.2f}"


def _money_millions(value: float | None) -> str:
    return _money(None if value is None else value * 1_000_000.0, "USD")


def _percent(value: float | None, digits: int = 1) -> str:
    return "—" if value is None else f"{value * 100:.{digits}f}%"


def _safe(value: str | None) -> str:
    return html.escape(value or "—")


def _template() -> str:
    resource = files("qhapaq_finance").joinpath("qhapaq_one_template.html")
    return resource.read_text(encoding="utf-8")


def _bridge_html(items: tuple[CashBridgeItem, ...]) -> str:
    if not items:
        return '<div class="empty">Cash-basis bridge unavailable.</div>'
    rows = []
    for item in items:
        sign = "+" if item.amount > 0 else ""
        label = item.label.replace("SBC economic-cost policy", "Stock-based compensation cost")
        rows.append(
            '<div class="bridge-row">'
            f"<span>{html.escape(label)}</span>"
            f"<strong>{sign}{_money_millions(item.amount)}</strong>"
            "</div>"
        )
    return "".join(rows)


def _sensitivity_html(points: tuple[SensitivityPoint, ...]) -> str:
    if not points:
        return '<div class="empty">Sensitivity unavailable.</div>'
    discounts = sorted({point.discount_rate for point in points})
    terminals = sorted({point.terminal_growth for point in points})
    lookup = {
        (point.discount_rate, point.terminal_growth): point.implied_fcf_growth for point in points
    }
    header = "".join(f"<th>{terminal * 100:.0f}% long-run</th>" for terminal in terminals)
    rows = []
    for discount in discounts:
        cells = "".join(
            f"<td>{_percent(lookup[(discount, terminal)])}</td>" for terminal in terminals
        )
        rows.append(f"<tr><th>{discount * 100:.0f}% return</th>{cells}</tr>")
    return (
        '<table class="sensitivity"><thead><tr><th></th>'
        + header
        + "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _observed_label(value: datetime) -> str:
    eastern = value.astimezone(ZoneInfo("America/New_York"))
    hour = eastern.strftime("%I").lstrip("0") or "0"
    return f"{eastern:%b} {eastern.day}, {eastern.year} · {hour}{eastern:%M %p} ET"


def _market_freshness_label(model: OneModel) -> str:
    observed = _observed_label(model.snapshot.observed_at)
    if model.freshness is Freshness.FRESH:
        return f"MARKET DATA FRESH · AS OF {observed}"
    return f"MARKET DATA {model.freshness.value.upper()} · OBSERVED {observed}"


def _watch_question(title: str, mechanism: str) -> str:
    """Turn source-backed risk content into an explicit executive question."""
    return f"What could change the case for {title.lower()}? {mechanism}"


def _why_case_could_work(thesis: str | None) -> str:
    if not thesis:
        return "No validated research interpretation is available."
    _, separator, supporting_evidence = thesis.partition(":")
    return supporting_evidence.strip() if separator else thesis


def _invalidation_copy(item: str) -> str:
    """Translate stored invalidation language without changing its conditions."""
    translated = item
    translated = translated.replace("Reconsider the positive underwriting case if ", "")
    translated = translated.replace("Reconsider if ", "")
    translated = translated.replace("recent FCF-proxy growth", "cash-flow growth")
    translated = translated.replace("the market-implied hurdle", "the rate required by valuation")
    translated = translated.replace("compress structurally", "weaken for lasting reasons")
    translated = translated.replace(
        "the expected duration of current AI-infrastructure economics",
        "whether current economics can last",
    )
    return translated[:1].upper() + translated[1:]


def _period_descriptor(period: str) -> str:
    """Produce a compact, readable period label from frozen cash-basis metadata."""
    normalized = period.lower()
    if normalized.startswith("six months"):
        return "6-month"
    if normalized.startswith("nine months"):
        return "9-month"
    if normalized.startswith("three months"):
        return "3-month"
    if normalized.startswith("year") or normalized.startswith("twelve months"):
        return "annual"
    return "reported-period"


def render_one_html(model: OneModel, output_path: str | Path) -> Path:
    """Render a deterministic, self-contained decision surface."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    snapshot = model.snapshot
    change = snapshot.change_from_previous_close
    price = f"{snapshot.price:,.2f}"
    change_label = "—" if change is None else f"{change * 100:+.2f}%".replace("-", "−", 1)
    hurdle = _percent(model.implied_fcf_growth)
    evidence = (
        model.evidence_as_of.strftime("%b %d, %Y").replace(" 0", " ")
        if model.evidence_as_of
        else "Not available"
    )
    source = html.escape(snapshot.source)
    matters = "".join(f"<li>{html.escape(item)}</li>" for item in model.what_matters)
    invalidation = "".join(
        f"<li>{html.escape(_invalidation_copy(item))}</li>" for item in model.invalidation
    )
    if not matters:
        matters = "<li>No validated research risks available.</li>"
    if not invalidation:
        invalidation = "<li>Build and validate a research evidence pack before underwriting.</li>"

    cash_basis = model.cash_basis
    reported_period = cash_basis.reported_period_fcf if cash_basis else None
    run_rate_period = cash_basis.run_rate_period_cash if cash_basis else None
    basis_period = cash_basis.period if cash_basis else "Not available"
    annualization = cash_basis.annualization_factor if cash_basis else None
    basis_kind = cash_basis.basis_kind.value.upper().replace("_", "-") if cash_basis else "MISSING"
    policy_note = cash_basis.policy_notes[0] if cash_basis else "Cash basis unavailable."
    bottom_line = (
        f"{model.company_name} enters this valuation test with evidence of current operating "
        f"strength, but today’s valuation still requires that strength to persist for years."
        if model.thesis
        else (
            "This valuation test needs validated research evidence before it can support a "
            "conclusion."
        )
    )
    primary_risk = (
        "Duration is the key risk. If demand, margins, or cash conversion weaken too soon, today’s "
        "valuation becomes harder to justify."
        if model.counterthesis
        else "No validated counter-case is available."
    )
    trust_evidence = (
        f"FINANCIAL EVIDENCE VERIFIED<br><span>Research evidence through {evidence}</span>"
        if model.research_ready
        else (
            "FINANCIAL EVIDENCE UNAVAILABLE<br><span>No checksum-validated evidence pack is "
            "available.</span>"
        )
    )
    trust_market = (
        f"MARKET OBSERVATION FRESH<br><span>{_observed_label(snapshot.observed_at)}</span>"
        if model.freshness is Freshness.FRESH
        else (
            f"MARKET OBSERVATION {model.freshness.value.upper()}<br>"
            f"<span>{_observed_label(snapshot.observed_at)}</span>"
        )
    )
    trust_cash = (
        f"CASH-FLOW BASE TRACEABLE<br><span>"
        f"{_money(model.cash_basis_value, snapshot.currency)} current run-rate basis</span>"
        if model.cash_basis_value is not None
        else (
            "CASH-FLOW BASE UNAVAILABLE<br><span>No evidence-backed cash-flow base is "
            "available.</span>"
        )
    )
    trust_model = (
        "VALUATION MODEL SOLVED<br><span>Base-case result reproducible from disclosed "
        "assumptions</span>"
        if model.implied_fcf_growth is not None
        else (
            "VALUATION MODEL NOT SOLVED<br><span>The disclosed inputs do not support a "
            "base-case result.</span>"
        )
    )
    currency = "$" if snapshot.currency.upper() == "USD" else html.escape(snapshot.currency) + " "

    replacements = {
        "__TICKER__": html.escape(model.ticker),
        "__COMPANY__": html.escape(model.company_name),
        "__MARKET_FRESHNESS__": _market_freshness_label(model),
        "__CURRENCY__": currency,
        "__PRICE__": price,
        "__CHANGE__": change_label,
        "__OBSERVED_SHORT__": html.escape(_observed_label(snapshot.observed_at)),
        "__EVIDENCE_STATE__": "VERIFIED" if model.research_ready else "MISSING",
        "__EVIDENCE_AS_OF__": evidence,
        "__MARKET_CAP__": _money(model.effective_market_cap, snapshot.currency),
        "__MARKET_CAP_SOURCE__": html.escape(model.market_cap_provenance),
        "__CASH_BASIS__": _money(model.cash_basis_value, snapshot.currency),
        "__REPORTED_PERIOD_FCF__": _money_millions(reported_period),
        "__RUN_RATE_PERIOD_CASH__": _money_millions(run_rate_period),
        "__BASIS_PERIOD__": html.escape(basis_period),
        "__PERIOD_DESCRIPTOR__": _period_descriptor(basis_period),
        "__ANNUALIZATION__": "—" if annualization is None else f"{annualization:.2f}×",
        "__BASIS_KIND__": html.escape(basis_kind),
        "__CASH_BASIS_BRIDGE__": _bridge_html(cash_basis.bridge if cash_basis else ()),
        "__CASH_BASIS_NOTE__": html.escape(policy_note),
        "__SENSITIVITY_TABLE__": _sensitivity_html(model.sensitivity),
        "__SOURCE__": source,
        "__HURDLE__": hurdle,
        "__DR_PCT__": _percent(model.discount_rate),
        "__TG_PCT__": _percent(model.terminal_growth),
        "__YEARS__": str(model.years),
        "__STATUS__": html.escape(model.status),
        "__STATUS_DETAIL__": html.escape(model.status_detail),
        "__BOTTOM_LINE__": _safe(bottom_line),
        "__WHY_CASE__": _safe(_why_case_could_work(model.thesis)),
        "__PRIMARY_RISK__": _safe(primary_risk),
        "__COUNTER__": _safe(model.counterthesis),
        "__TRUST_EVIDENCE__": trust_evidence,
        "__TRUST_MARKET__": trust_market,
        "__TRUST_CASH__": trust_cash,
        "__TRUST_MODEL__": trust_model,
        "__MATTERS__": matters,
        "__INVALIDATION__": invalidation,
        "__OBSERVED__": html.escape(snapshot.observed_at.isoformat()),
        "__RETRIEVED__": html.escape(snapshot.retrieved_at.isoformat()),
    }
    rendered = _template()
    for token, value in replacements.items():
        rendered = rendered.replace(token, value)
    output.write_text(rendered, encoding="utf-8")
    return output
