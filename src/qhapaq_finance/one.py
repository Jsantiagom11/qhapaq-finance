"""Qhapaq One: a single-view market expectations product."""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from importlib.resources import files
from pathlib import Path

from .expectations import (
    ExpectationsError,
    ReverseDcfInputs,
    SensitivityPoint,
    reverse_dcf_sensitivity,
    solve_implied_fcf_growth,
)
from .market import Freshness, FreshnessPolicy, MarketSnapshot, classify_freshness
from .normalization import CashBridgeItem, NormalizedCashResult, load_normalized_cash
from .research import ResearchRecord, load_research_record


@dataclass(frozen=True)
class OneModel:
    ticker: str
    company_name: str
    snapshot: MarketSnapshot
    freshness: Freshness
    evidence_as_of: date | None
    research_ready: bool
    normalized_cash: NormalizedCashResult | None
    normalized_cash_power: float | None
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


def _normalization_path(root: Path, ticker: str) -> Path:
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


def _load_normalization(
    root: Path, ticker: str, record: ResearchRecord | None
) -> NormalizedCashResult | None:
    if record is None:
        return None
    path = _normalization_path(root, ticker)
    if not path.is_file():
        return None
    return load_normalized_cash(record=record, path=path)


def _effective_market_cap(
    snapshot: MarketSnapshot,
    record: ResearchRecord | None,
    normalized_cash: NormalizedCashResult | None,
) -> tuple[float | None, str]:
    if snapshot.market_cap is not None:
        return snapshot.market_cap, f"provider market cap · {snapshot.source}"
    if normalized_cash and normalized_cash.shares_outstanding:
        return (
            snapshot.price * normalized_cash.shares_outstanding,
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
    """Build a concise decision model while failing closed on missing normalization."""
    root = Path(repository_root).resolve()
    reference = now or datetime.now(timezone.utc)
    freshness = classify_freshness(
        snapshot,
        policy=FreshnessPolicy(max_age=max_age),
        now=reference,
    )
    record = _load_research(root, snapshot.ticker)
    normalized_cash = _load_normalization(root, snapshot.ticker, record)
    company_name = record.issuer.get("name", snapshot.ticker) if record else snapshot.ticker
    normalized_cash_power = (
        normalized_cash.normalized_annualized_fcf * 1_000_000.0
        if normalized_cash is not None
        else None
    )
    effective_market_cap, market_cap_provenance = _effective_market_cap(
        snapshot, record, normalized_cash
    )

    implied_growth: float | None = None
    sensitivity: tuple[SensitivityPoint, ...] = ()
    if normalized_cash_power is not None and effective_market_cap is not None:
        try:
            implied_growth = solve_implied_fcf_growth(
                ReverseDcfInputs(
                    equity_value=effective_market_cap,
                    starting_fcf=normalized_cash_power,
                    discount_rate=discount_rate,
                    terminal_growth=terminal_growth,
                    years=years,
                )
            ).implied_fcf_growth
            sensitivity = reverse_dcf_sensitivity(
                equity_value=effective_market_cap,
                starting_fcf=normalized_cash_power,
                years=years,
            )
        except ExpectationsError:
            implied_growth = None
            sensitivity = ()

    if record is None:
        status = "INSUFFICIENT DATA"
        status_detail = "Market state is available, but no validated research evidence pack exists."
    elif normalized_cash is None:
        status = "INSUFFICIENT DATA"
        status_detail = (
            "Research is validated, but no evidence-backed Normalized Cash Power record exists."
        )
    elif effective_market_cap is None:
        status = "INSUFFICIENT DATA"
        status_detail = "Research is validated, but no usable equity-value input is available."
    elif implied_growth is None:
        status = "INSUFFICIENT DATA"
        status_detail = (
            "Normalized cash and equity value exist, but the reverse-DCF hurdle could not "
            "be solved under this scenario."
        )
    else:
        status = "UNDERWRITING"
        status_detail = (
            f"At {discount_rate * 100:.1f}% cost of equity and {terminal_growth * 100:.1f}% "
            f"terminal growth, the observed equity value requires {implied_growth * 100:.1f}% "
            f"annual growth from normalized cash power over {years} years. "
            "No forward business-support range or valuation recommendation is asserted."
        )

    thesis = _interpretation(record, "thesis") if record else None
    counterthesis = _interpretation(record, "counterthesis") if record else None
    invalidation = tuple(record.invalidation[:3]) if record else ()
    what_matters = tuple(str(risk.get("title", "")) for risk in record.risks[:3]) if record else ()

    return OneModel(
        ticker=snapshot.ticker,
        company_name=company_name,
        snapshot=snapshot,
        freshness=freshness,
        evidence_as_of=record.as_of if record else None,
        research_ready=record is not None,
        normalized_cash=normalized_cash,
        normalized_cash_power=normalized_cash_power,
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
    prefix = "$" if currency.upper() == "USD" else f"{currency.upper()} "
    if value >= 1_000_000_000_000:
        return f"{prefix}{value / 1_000_000_000_000:.2f}T"
    if value >= 1_000_000_000:
        return f"{prefix}{value / 1_000_000_000:.1f}B"
    if value >= 1_000_000:
        return f"{prefix}{value / 1_000_000:.1f}M"
    return f"{prefix}{value:,.2f}"


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
        return '<div class="empty">Normalization unavailable.</div>'
    rows = []
    for item in items:
        sign = "+" if item.amount > 0 else ""
        rows.append(
            '<div class="bridge-row">'
            f'<span>{html.escape(item.label)}</span>'
            f'<strong>{sign}{_money_millions(item.amount)}</strong>'
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
    header = "".join(f"<th>{terminal * 100:.0f}% TG</th>" for terminal in terminals)
    rows = []
    for discount in discounts:
        cells = "".join(
            f"<td>{_percent(lookup[(discount, terminal)])}</td>" for terminal in terminals
        )
        rows.append(f"<tr><th>{discount * 100:.0f}% CoE</th>{cells}</tr>")
    return (
        '<table class="sensitivity"><thead><tr><th></th>'
        + header
        + "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def render_one_html(model: OneModel, output_path: str | Path) -> Path:
    """Render a deterministic, self-contained decision surface."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    snapshot = model.snapshot
    change = snapshot.change_from_previous_close
    price = f"{snapshot.price:,.2f}"
    change_label = "—" if change is None else f"{change * 100:+.2f}%"
    hurdle = _percent(model.implied_fcf_growth)
    evidence = model.evidence_as_of.isoformat() if model.evidence_as_of else "Not available"
    source = html.escape(snapshot.source)
    matters = "".join(f"<li>{html.escape(item)}</li>" for item in model.what_matters)
    invalidation = "".join(f"<li>{html.escape(item)}</li>" for item in model.invalidation)
    if not matters:
        matters = "<li>No validated research risks available.</li>"
    if not invalidation:
        invalidation = "<li>Build and validate a research evidence pack before underwriting.</li>"

    normalized = model.normalized_cash
    reported_period = normalized.reported_period_fcf if normalized else None
    normalized_period = normalized.normalized_period_fcf if normalized else None
    normalization_period = normalized.period if normalized else "Not available"
    annualization = normalized.annualization_factor if normalized else None
    policy_note = normalized.policy_notes[0] if normalized else "Normalization unavailable."
    scenario = {
        "marketCap": model.effective_market_cap,
        "startingFcf": model.normalized_cash_power,
        "discountRate": model.discount_rate,
        "terminalGrowth": model.terminal_growth,
        "years": model.years,
    }
    scenario_json = json.dumps(scenario, sort_keys=True, separators=(",", ":"))
    scenario_enabled = (
        model.normalized_cash_power is not None and model.effective_market_cap is not None
    )
    scenario_disabled = "" if scenario_enabled else " disabled"
    currency = "$" if snapshot.currency.upper() == "USD" else html.escape(snapshot.currency) + " "

    replacements = {
        "__TICKER__": html.escape(model.ticker),
        "__COMPANY__": html.escape(model.company_name),
        "__FRESHNESS__": model.freshness.value.upper(),
        "__MARKET_STATE__": snapshot.market_state.value.upper(),
        "__CURRENCY__": currency,
        "__PRICE__": price,
        "__CHANGE__": change_label,
        "__OBSERVED_SHORT__": html.escape(snapshot.observed_at.strftime("%Y-%m-%d %H:%M %Z")),
        "__EVIDENCE_STATE__": "VERIFIED" if model.research_ready else "MISSING",
        "__EVIDENCE_AS_OF__": evidence,
        "__MARKET_CAP__": _money(model.effective_market_cap, snapshot.currency),
        "__MARKET_CAP_SOURCE__": html.escape(model.market_cap_provenance),
        "__NORMALIZED_CASH__": _money(model.normalized_cash_power, snapshot.currency),
        "__REPORTED_PERIOD_FCF__": _money_millions(reported_period),
        "__NORMALIZED_PERIOD_FCF__": _money_millions(normalized_period),
        "__NORMALIZATION_PERIOD__": html.escape(normalization_period),
        "__ANNUALIZATION__": "—" if annualization is None else f"{annualization:.2f}×",
        "__NORMALIZATION_STATE__": "ANALYTICAL" if normalized else "MISSING",
        "__NORMALIZATION_BRIDGE__": _bridge_html(normalized.bridge if normalized else ()),
        "__NORMALIZATION_NOTE__": html.escape(policy_note),
        "__SENSITIVITY_TABLE__": _sensitivity_html(model.sensitivity),
        "__SOURCE__": source,
        "__HURDLE__": hurdle,
        "__DR_PCT__": _percent(model.discount_rate),
        "__TG_PCT__": _percent(model.terminal_growth),
        "__YEARS__": str(model.years),
        "__SCENARIO_DISABLED__": scenario_disabled,
        "__DR_VALUE__": f"{model.discount_rate * 100:.1f}",
        "__TG_VALUE__": f"{model.terminal_growth * 100:.1f}",
        "__STATUS__": html.escape(model.status),
        "__STATUS_DETAIL__": html.escape(model.status_detail),
        "__THESIS__": _safe(model.thesis),
        "__COUNTER__": _safe(model.counterthesis),
        "__MATTERS__": matters,
        "__INVALIDATION__": invalidation,
        "__OBSERVED__": html.escape(snapshot.observed_at.isoformat()),
        "__RETRIEVED__": html.escape(snapshot.retrieved_at.isoformat()),
        "__SCENARIO_JSON__": scenario_json,
    }
    rendered = _template()
    for token, value in replacements.items():
        rendered = rendered.replace(token, value)
    output.write_text(rendered, encoding="utf-8")
    return output
