"""Qhapaq One: a single-view market expectations product."""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from importlib.resources import files
from pathlib import Path

from .expectations import ExpectationsError, ReverseDcfInputs, solve_implied_fcf_growth
from .market import Freshness, FreshnessPolicy, MarketSnapshot, classify_freshness
from .research import ResearchRecord, load_research_record


@dataclass(frozen=True)
class OneModel:
    ticker: str
    company_name: str
    snapshot: MarketSnapshot
    freshness: Freshness
    evidence_as_of: date | None
    research_ready: bool
    starting_fcf: float | None
    implied_fcf_growth: float | None
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


def _starting_fcf(record: ResearchRecord) -> float | None:
    candidates = [
        metric
        for metric in record.metrics
        if metric.id.lower().startswith("m-fcf") and metric.unit == "USD million"
    ]
    if not candidates:
        return None
    value = candidates[-1].value * 1_000_000.0
    return value if value > 0 else None


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
    """Build one concise decision model without inventing missing research."""
    root = Path(repository_root).resolve()
    reference = now or datetime.now(timezone.utc)
    freshness = classify_freshness(
        snapshot,
        policy=FreshnessPolicy(max_age=max_age),
        now=reference,
    )
    record = _load_research(root, snapshot.ticker)
    company_name = record.issuer.get("name", snapshot.ticker) if record else snapshot.ticker
    starting_fcf = _starting_fcf(record) if record else None
    implied_growth: float | None = None

    if record and starting_fcf is not None and snapshot.market_cap is not None:
        try:
            implied_growth = solve_implied_fcf_growth(
                ReverseDcfInputs(
                    equity_value=snapshot.market_cap,
                    starting_fcf=starting_fcf,
                    discount_rate=discount_rate,
                    terminal_growth=terminal_growth,
                    years=years,
                )
            ).implied_fcf_growth
        except ExpectationsError:
            implied_growth = None

    if record is None:
        status = "INSUFFICIENT DATA"
        status_detail = (
            "Market state is available, but no validated primary-evidence research pack exists."
        )
    elif starting_fcf is None:
        status = "INSUFFICIENT DATA"
        status_detail = "Research is validated, but no compatible equity-FCF proxy is available."
    elif snapshot.market_cap is None:
        status = "INSUFFICIENT DATA"
        status_detail = (
            "Research is validated, but the market snapshot has no usable market capitalization."
        )
    elif implied_growth is None:
        status = "INSUFFICIENT DATA"
        status_detail = (
            "Inputs exist, but the reverse-DCF hurdle could not be solved under this scenario."
        )
    else:
        status = "UNDERWRITING"
        status_detail = (
            "The market's FCF growth hurdle is explicit. "
            "Qhapaq does not convert it into a buy/sell call."
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
        starting_fcf=starting_fcf,
        implied_fcf_growth=implied_growth,
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


def _percent(value: float | None, digits: int = 1) -> str:
    return "—" if value is None else f"{value * 100:.{digits}f}%"


def _safe(value: str | None) -> str:
    return html.escape(value or "—")


def _template() -> str:
    resource = files("qhapaq_finance").joinpath("qhapaq_one_template.html")
    return resource.read_text(encoding="utf-8")


def render_one_html(model: OneModel, output_path: str | Path) -> Path:
    """Render a deterministic, self-contained, high-end HTML decision surface."""
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
        invalidation = (
            "<li>Build and validate a primary-evidence research pack before underwriting.</li>"
        )

    scenario = {
        "marketCap": snapshot.market_cap,
        "startingFcf": model.starting_fcf,
        "discountRate": model.discount_rate,
        "terminalGrowth": model.terminal_growth,
        "years": model.years,
    }
    scenario_json = json.dumps(scenario, sort_keys=True, separators=(",", ":"))
    scenario_enabled = model.starting_fcf is not None and snapshot.market_cap is not None
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
        "__MARKET_CAP__": _money(snapshot.market_cap, snapshot.currency),
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
