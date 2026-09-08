"""Qhapaq One: a single-view market expectations product."""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
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
        status_detail = "Market state is available, but no validated primary-evidence research pack exists."
    elif starting_fcf is None:
        status = "INSUFFICIENT DATA"
        status_detail = "Research is validated, but no compatible equity-FCF proxy is available."
    elif snapshot.market_cap is None:
        status = "INSUFFICIENT DATA"
        status_detail = "Research is validated, but the market snapshot has no usable market capitalization."
    elif implied_growth is None:
        status = "INSUFFICIENT DATA"
        status_detail = "Inputs exist, but the reverse-DCF hurdle could not be solved under this scenario."
    else:
        status = "UNDERWRITING"
        status_detail = (
            "The market's FCF growth hurdle is explicit. Qhapaq does not convert it into a buy/sell call."
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
    observed = snapshot.observed_at.isoformat()
    source = html.escape(snapshot.source)
    matters = "".join(f"<li>{html.escape(item)}</li>" for item in model.what_matters)
    invalidation = "".join(f"<li>{html.escape(item)}</li>" for item in model.invalidation)
    if not matters:
        matters = "<li>No validated research risks available.</li>"
    if not invalidation:
        invalidation = "<li>Build and validate a primary-evidence research pack before underwriting.</li>"

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

    template = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Qhapaq One · __TICKER__</title>
<style>
:root{--bg:#0a0a0b;--panel:#111113;--line:#252528;--text:#f2f0ea;--muted:#8b8a87;--accent:#d8c49a;--max:1180px}
*{box-sizing:border-box}html{background:var(--bg);color:var(--text);font-family:Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}body{margin:0;background:radial-gradient(circle at 70% -20%,#242019 0,transparent 34rem),var(--bg)}
main{max-width:var(--max);margin:auto;padding:42px 32px 72px}.top{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--line);padding-bottom:18px}.brand{font-size:12px;letter-spacing:.24em;font-weight:700}.live{font-size:11px;letter-spacing:.14em;color:var(--accent)}
.hero{display:grid;grid-template-columns:1fr auto;gap:32px;align-items:end;padding:62px 0 38px}.eyebrow{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.14em}.ticker{font-size:clamp(48px,8vw,96px);letter-spacing:-.065em;line-height:.9;margin:12px 0}.company{color:var(--muted);font-size:16px}.quote{text-align:right}.price{font-size:clamp(40px,6vw,72px);letter-spacing:-.055em}.change{margin-top:8px;color:var(--accent);font-size:14px}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);border-top:1px solid var(--line);border-bottom:1px solid var(--line)}.metric{padding:24px 20px 24px 0}.metric+.metric{border-left:1px solid var(--line);padding-left:24px}.metric-label{color:var(--muted);font-size:11px;letter-spacing:.14em;text-transform:uppercase}.metric-value{font-size:20px;margin-top:10px}.metric-sub{font-size:12px;color:var(--muted);margin-top:7px;line-height:1.5}
.section{padding:52px 0;border-bottom:1px solid var(--line)}.section-title{font-size:11px;letter-spacing:.16em;color:var(--muted);text-transform:uppercase;margin-bottom:22px}.expect{display:grid;grid-template-columns:1.2fr .8fr;gap:56px}.hurdle{font-size:clamp(54px,8vw,92px);letter-spacing:-.055em;line-height:1}.hurdle-caption{max-width:560px;color:var(--muted);line-height:1.65;margin-top:16px}.status{border-left:1px solid var(--line);padding-left:32px}.status strong{display:block;color:var(--accent);font-size:17px;letter-spacing:.04em}.status p{color:var(--muted);line-height:1.65}
.columns{display:grid;grid-template-columns:1fr 1fr;gap:56px}.copy{font-size:18px;line-height:1.72;letter-spacing:-.01em}.copy.muted{color:#b0afab}.clean{list-style:none;padding:0;margin:0}.clean li{padding:13px 0;border-bottom:1px solid var(--line);line-height:1.5}.clean li:first-child{padding-top:0}
.actions{display:flex;gap:10px;margin-top:28px}button{appearance:none;border:1px solid var(--line);background:transparent;color:var(--text);padding:11px 16px;border-radius:999px;font:inherit;font-size:12px;cursor:pointer}button:hover{border-color:var(--accent)}button:disabled{opacity:.35;cursor:not-allowed}.scenario{display:none;margin-top:28px;padding:24px;border:1px solid var(--line);border-radius:18px;background:var(--panel)}.scenario.open{display:block}.control{display:grid;grid-template-columns:180px 1fr 80px;gap:20px;align-items:center;padding:12px 0}.control label{font-size:13px;color:var(--muted)}input[type=range]{width:100%;accent-color:var(--accent)}.control output{text-align:right;font-variant-numeric:tabular-nums}.scenario-result{margin-top:18px;padding-top:20px;border-top:1px solid var(--line);display:flex;justify-content:space-between;align-items:end}.scenario-result strong{font-size:36px;letter-spacing:-.04em}
.foot{padding-top:28px;color:var(--muted);font-size:11px;line-height:1.7}.foot span{color:#bbb9b3}
@media(max-width:760px){main{padding:26px 20px 56px}.hero{grid-template-columns:1fr;padding:42px 0 30px}.quote{text-align:left}.grid3{grid-template-columns:1fr}.metric+.metric{border-left:0;border-top:1px solid var(--line);padding-left:0}.expect,.columns{grid-template-columns:1fr;gap:34px}.status{border-left:0;border-top:1px solid var(--line);padding:24px 0 0}.control{grid-template-columns:1fr 64px;gap:10px}.control input{grid-column:1/-1}.scenario-result{align-items:flex-start;gap:20px;flex-direction:column}}
</style>
</head>
<body>
<main>
<header class="top"><div class="brand">QHAPAQ ONE</div><div class="live">__FRESHNESS__ · __MARKET_STATE__</div></header>
<section class="hero"><div><div class="eyebrow">Market expectations · research evidence</div><div class="ticker">__TICKER__</div><div class="company">__COMPANY__</div></div><div class="quote"><div class="price">__CURRENCY____PRICE__</div><div class="change">__CHANGE__ · observed __OBSERVED_SHORT__</div></div></section>
<section class="grid3"><div class="metric"><div class="metric-label">Evidence</div><div class="metric-value">__EVIDENCE_STATE__</div><div class="metric-sub">As of __EVIDENCE_AS_OF__</div></div><div class="metric"><div class="metric-label">Market cap</div><div class="metric-value">__MARKET_CAP__</div><div class="metric-sub">Snapshot source · __SOURCE__</div></div><div class="metric"><div class="metric-label">10Y FCF hurdle</div><div class="metric-value" id="top-hurdle">__HURDLE__</div><div class="metric-sub">__DR_PCT__ discount · __TG_PCT__ terminal growth</div></div></section>
<section class="section"><div class="section-title">Market expects</div><div class="expect"><div><div class="hurdle" id="hero-hurdle">__HURDLE__</div><div class="hurdle-caption">Constant annual FCF growth implied by the observed equity value over __YEARS__ years under the current scenario. It is a hurdle, not a forecast or target price.</div><div class="actions"><button id="scenario-toggle"__SCENARIO_DISABLED__>Scenario</button></div><div id="scenario" class="scenario"><div class="control"><label for="discount">Discount rate</label><input id="discount" type="range" min="6" max="14" step="0.1" value="__DR_VALUE__"><output id="discount-out">__DR_PCT__</output></div><div class="control"><label for="terminal">Terminal growth</label><input id="terminal" type="range" min="0" max="5" step="0.1" value="__TG_VALUE__"><output id="terminal-out">__TG_PCT__</output></div><div class="scenario-result"><span>Implied FCF growth</span><strong id="scenario-hurdle">__HURDLE__</strong></div></div></div><div class="status"><div class="section-title">State</div><strong>__STATUS__</strong><p>__STATUS_DETAIL__</p></div></div></section>
<section class="section"><div class="columns"><div><div class="section-title">Thesis</div><div class="copy">__THESIS__</div></div><div><div class="section-title">Counterthesis</div><div class="copy muted">__COUNTER__</div></div></div></section>
<section class="section"><div class="columns"><div><div class="section-title">What matters now</div><ul class="clean">__MATTERS__</ul></div><div><div class="section-title">Invalidates</div><ul class="clean">__INVALIDATION__</ul></div></div></section>
<footer class="foot">Price observation: <span>__OBSERVED__</span> · retrieved <span>__RETRIEVED__</span> · source <span>__SOURCE__</span>.<br>Qhapaq One separates live market observations from frozen primary-source research. Missing evidence remains missing; this page is research software, not investment advice.</footer>
</main>
<script>
const scenario=__SCENARIO_JSON__;
const toggle=document.getElementById('scenario-toggle');
const panel=document.getElementById('scenario');
if(toggle){toggle.addEventListener('click',()=>panel.classList.toggle('open'));}
function pv(g,r,tg,years,fcf){let pv=0,cf=fcf,df=1;for(let i=0;i<years;i++){cf*=1+g;df*=1+r;pv+=cf/df;}const terminal=cf*(1+tg)/(r-tg);return pv+terminal/df;}
function solve(r,tg){if(scenario.marketCap===null||scenario.startingFcf===null||r<=tg)return null;let lo=-.95,hi=.5;while(pv(hi,r,tg,scenario.years,scenario.startingFcf)<scenario.marketCap&&hi<10){hi=hi*2+.1;}for(let i=0;i<160;i++){const mid=(lo+hi)/2;if(pv(mid,r,tg,scenario.years,scenario.startingFcf)<scenario.marketCap)lo=mid;else hi=mid;}return(lo+hi)/2;}
function update(){const d=document.getElementById('discount'),t=document.getElementById('terminal');if(!d||!t)return;const r=Number(d.value)/100,tg=Number(t.value)/100;document.getElementById('discount-out').textContent=d.value+'%';document.getElementById('terminal-out').textContent=t.value+'%';const g=solve(r,tg);const label=g===null?'—':(g*100).toFixed(1)+'%';document.getElementById('scenario-hurdle').textContent=label;document.getElementById('hero-hurdle').textContent=label;document.getElementById('top-hurdle').textContent=label;}
for(const id of ['discount','terminal']){const el=document.getElementById(id);if(el)el.addEventListener('input',update);}
</script>
</body></html>
"""

    replacements = {
        "__TICKER__": html.escape(model.ticker),
        "__COMPANY__": html.escape(model.company_name),
        "__FRESHNESS__": model.freshness.value.upper(),
        "__MARKET_STATE__": snapshot.market_state.value.upper(),
        "__CURRENCY__": "$" if snapshot.currency.upper() == "USD" else html.escape(snapshot.currency) + " ",
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
        "__OBSERVED__": html.escape(observed),
        "__RETRIEVED__": html.escape(snapshot.retrieved_at.isoformat()),
        "__SCENARIO_JSON__": scenario_json,
    }
    rendered = template
    for token, value in replacements.items():
        rendered = rendered.replace(token, value)
    output.write_text(rendered, encoding="utf-8")
    return output
