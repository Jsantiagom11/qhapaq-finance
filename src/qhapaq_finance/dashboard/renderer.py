"""Standalone, offline HTML rendering for dashboard artifacts."""
# ruff: noqa: E501

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from .serializer import canonical_json


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _money(value: Any) -> str:
    return "Unavailable" if value is None else f"${float(value):,.2f}"


def _millions(value: Any) -> str:
    return "Unavailable" if value is None else f"${float(value):,.0f}m"


def _pct(value: Any) -> str:
    return "Unavailable" if value is None else f"{float(value) * 100:.1f}%"


def _pp(value: Any) -> str:
    return "Unavailable" if value is None else f"{float(value) * 100:+.1f} pp"


def _items(values: list[str]) -> str:
    return "".join(f"<li>{_e(value)}</li>" for value in values) or "<li>Unavailable</li>"


def _css() -> str:
    return """
/* TOKENS */
:root{color-scheme:light;--surface-page:#f7f5f0;--surface-panel:#fffdf8;--surface-panel-alt:#f0ede5;--text-primary:#1c2730;--text-secondary:#58646d;--text-muted:#747d83;--border-subtle:#d6d1c7;--accent-primary:#536f7d;--semantic-positive:#32634d;--semantic-warning:#82621d;--semantic-negative:#8b4942;--epistemic-fact:#32634d;--epistemic-derived:#315c72;--epistemic-inference:#82621d;--epistemic-unknown:#8b4942;--touch-target-min:44px}
:root[data-theme=night]{color-scheme:dark;--surface-page:#20292f;--surface-panel:#29343b;--surface-panel-alt:#344047;--text-primary:#e5e0d5;--text-secondary:#c5ccca;--text-muted:#aab4b3;--border-subtle:#4a5960;--accent-primary:#708d99;--semantic-positive:#a9cfb2;--semantic-warning:#e0c783;--semantic-negative:#e6afa8;--epistemic-fact:#a9cfb2;--epistemic-derived:#b4d1d0;--epistemic-inference:#e0c783;--epistemic-unknown:#e6afa8}
/* RESET / BASE */
*{box-sizing:border-box}body{margin:0;background:var(--surface-page);color:var(--text-primary);font:14px/1.5 Arial,sans-serif}main{max-width:1320px;margin:auto;padding:28px}h1{margin:4px 0;font:700 42px Georgia,serif}h2{margin:34px 0 12px;font:700 21px Georgia,serif}h3{margin:0 0 8px;font-size:12px;letter-spacing:.08em;text-transform:uppercase}p{margin:8px 0}ul{padding-left:18px;margin:7px 0}table{width:100%;border-collapse:collapse;font-size:12px;background:var(--surface-panel)}th,td{padding:9px;border-bottom:1px solid var(--border-subtle);text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left}th{color:var(--text-secondary);font-size:10px;text-transform:uppercase;cursor:pointer}td:not(:first-child),.numeric{font-variant-numeric:tabular-nums lining-nums}
/* ATOMS */
.text-label,.label,.metadata-text,.control-label{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--text-secondary)}.metric-value,.value{font-size:23px;font-weight:700;margin-top:5px;font-variant-numeric:tabular-nums lining-nums}.metric-unit{font-size:14px;color:var(--text-secondary)}.status-badge,.epistemic-badge{display:inline-block;padding:3px 6px;border:1px solid var(--border-subtle);background:var(--surface-panel-alt);font-size:10px;font-weight:bold;letter-spacing:.08em;text-transform:uppercase}.status-badge.evidence{color:var(--semantic-positive)}.status-badge.fixture{color:var(--semantic-warning)}.epistemic-badge.FACT{color:var(--epistemic-fact)}.epistemic-badge.DERIVED_FACT{color:var(--epistemic-derived)}.epistemic-badge.INFERENCE{color:var(--epistemic-inference)}.epistemic-badge.UNCERTAINTY{color:var(--epistemic-unknown)}button,input{font:inherit}button{min-block-size:var(--touch-target-min);padding:8px 10px;background:var(--surface-panel-alt);border:1px solid var(--border-subtle);color:var(--text-primary);cursor:pointer}button:hover{border-color:var(--accent-primary)}button:focus-visible,input:focus-visible,summary:focus-visible{outline:2px solid var(--accent-primary);outline-offset:2px}input{min-block-size:var(--touch-target-min);padding:8px;background:var(--surface-panel);border:1px solid var(--border-subtle);color:var(--text-primary);width:280px}
/* MOLECULES */
.metric-card,.argument-card,.research-panel{background:var(--surface-panel);border:1px solid var(--border-subtle);padding:15px}.metric-card .help-text{margin-top:5px;color:var(--text-secondary);font-size:12px}.argument-card p{font-size:15px}.evidence-summary{color:var(--text-secondary);font-size:12px}.evidence-summary details{margin-top:7px}.view-toggle button[aria-pressed=true],.theme-toggle button[aria-pressed=true]{background:var(--accent-primary);border-color:var(--accent-primary);color:#fff}.control-group,.toolbar{display:flex;align-items:center;flex-wrap:wrap;gap:6px}.toolbar{margin:12px 0}.provenance{max-height:380px;overflow:auto}details{background:var(--surface-panel);border:1px solid var(--border-subtle);padding:12px}summary{cursor:pointer;font-weight:bold;min-block-size:var(--touch-target-min);display:flex;align-items:center}
/* ORGANISMS / LAYOUT */
.dashboard-header{display:flex;justify-content:space-between;gap:20px;border-bottom:2px solid var(--text-primary);padding-bottom:14px}.header-meta{text-align:right}.metric-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.decision-metrics{grid-template-columns:repeat(3,1fr)}.analytical-metrics{grid-template-columns:repeat(6,1fr)}.analytical-metrics .metric-card:nth-child(-n+3){grid-column:span 2}.analytical-metrics .metric-card:nth-child(n+4){grid-column:span 3}.argument-grid,.two-column{display:grid;grid-template-columns:1fr 1fr;gap:12px}.decision-conditions-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.three-column{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.simple-hero{padding:18px 0 5px;border-bottom:1px solid var(--border-subtle)}.simple-hero h2{margin:4px 0;font-size:26px}.price-above{color:var(--semantic-negative)}.price-below{color:var(--semantic-positive)}.scenario.base{border-top:3px solid var(--accent-primary)}.buy-zone-scale{display:flex;align-items:center;gap:3px;margin:12px 0 4px;color:var(--text-secondary);font-size:11px;font-variant-numeric:tabular-nums lining-nums}.buy-zone-scale span{flex:1;text-align:center}.buy-zone-scale .current{color:var(--text-primary);font-weight:bold}.buy-zone-line{height:2px;background:var(--border-subtle);position:relative}.buy-zone-line::after{content:'●';position:absolute;right:0;top:-10px;color:var(--semantic-negative);font-size:18px}
[data-view=research] .simple-only{display:none}[data-view=simple] .research-only{display:none}
/* RESPONSIVE */
@media(max-width:850px){main{padding:18px}.dashboard-header{display:block}.header-meta{text-align:left;margin-top:12px}.metric-grid{grid-template-columns:repeat(2,1fr)}.decision-metrics{grid-template-columns:repeat(3,1fr)}.analytical-metrics{grid-template-columns:1fr}.analytical-metrics .metric-card{grid-column:span 1}.argument-grid,.two-column,.three-column{grid-template-columns:1fr}table{display:block;overflow-x:auto}.control-group{align-items:flex-start}.buy-zone-scale{font-size:9px}}@media(max-width:800px){.decision-conditions-grid{grid-template-columns:1fr}}@media(max-width:420px){.metric-grid,.decision-metrics{grid-template-columns:1fr}h1{font-size:36px}input{width:100%}}
"""


def _theme_initializer() -> str:
    """Return an offline, failure-tolerant preference initializer for the document head."""
    return """<script>try{const saved=localStorage.getItem('qhapaq-theme');const theme=saved==='night'||saved==='paper'?saved:(matchMedia('(prefers-color-scheme: dark)').matches?'night':'paper');document.documentElement.dataset.theme=theme}catch(_){document.documentElement.dataset.theme=matchMedia('(prefers-color-scheme: dark)').matches?'night':'paper'}</script>"""


def _theme_toggle() -> str:
    return '<div class="control-group theme-toggle" aria-label="Color theme"><span class="control-label">Theme</span><button id="paper-theme" aria-pressed="true">Paper</button><button id="night-theme" aria-pressed="false">Night</button></div>'


def _theme_controls() -> str:
    return """function setTheme(theme){document.documentElement.dataset.theme=theme;paperTheme?.setAttribute('aria-pressed',String(theme==='paper'));nightTheme?.setAttribute('aria-pressed',String(theme==='night'));try{localStorage.setItem('qhapaq-theme',theme)}catch(_){}}function initTheme(){const theme=document.documentElement.dataset.theme==='night'?'night':'paper';setTheme(theme);paperTheme?.addEventListener('click',()=>setTheme('paper'));nightTheme?.addEventListener('click',()=>setTheme('night'));}const paperTheme=document.getElementById('paper-theme');const nightTheme=document.getElementById('night-theme');initTheme();"""


def _render_metric_card(label: str, value: str, helper: str = "", status: str = "") -> str:
    """Render the MetricCard molecule; values are already deterministic facts."""
    helper_html = f'<div class="help-text">{_e(helper)}</div>' if helper else ""
    status_html = f'<div class="status-badge">{_e(status)}</div>' if status else ""
    return f'<div class="metric-card"><div class="text-label">{_e(label)}</div><div class="metric-value">{value}</div>{helper_html}{status_html}</div>'


_SIMPLE_EPISTEMIC = {
    "FACT": "Verified fact",
    "DERIVED_FACT": "Calculated",
    "INFERENCE": "Interpretation",
    "UNCERTAINTY": "Unknown",
}
_FRIENDLY_EVIDENCE = {
    "market_price": "Current market price",
    "base_fair_value": "Base valuation estimate",
    "margin_of_safety": "Price compared with base value",
    "roic": "Return on invested capital",
    "wacc": "Estimated cost of capital",
    "roic_wacc_spread": "Return compared with cost of capital",
    "market_implied_growth": "Market-implied growth",
    "base_growth": "Base growth assumption",
    "expectations_gap": "Market versus base growth",
    "terminal_value_share": "Long-term value dependence",
}


def _render_argument_card(argument: dict[str, Any], title: str = "", simple: bool = False) -> str:
    status = argument["status"]
    statement = argument["statement"]
    badge = (
        _SIMPLE_EPISTEMIC.get(status, status.replace("_", " "))
        if simple
        else status.replace("_", " ")
    )
    if simple:
        if argument["category"] == "VALUATION":
            statement = (
                "The current price is above Qhapaq's base value, so there is no valuation "
                "cushion under the base case."
                if "above" in statement.lower()
                else "The current price is below Qhapaq's base value, so there is a valuation "
                "cushion under the base case."
            )
        elif argument["category"] == "MUST_BE_TRUE":
            statement = (
                f"For the base case to hold, {statement[:1].lower()}{statement[1:]}".replace(
                    "can generate cash conversion", "need to continue supporting cash conversion"
                )
            )
        labels = [
            _FRIENDLY_EVIDENCE.get(item, "Verified financial data")
            for item in argument["evidence_ids"]
        ]
        summary = (
            "Gap identified in the current evidence set"
            if status == "UNCERTAINTY"
            else "✓ Supported by verified financial data"
        )
        evidence = (
            f"{summary}<details><summary>View evidence</summary><ul>{_items(labels)}</ul></details>"
        )
    else:
        evidence = f"Evidence IDs: {_e(', '.join(argument['evidence_ids']))}"
    return f'<article class="argument-card">{f"<h3>{_e(title)}</h3>" if title else ""}<span class="epistemic-badge {_e(status)}">{_e(badge)}</span><p>{_e(statement)}</p><div class="evidence-summary">{evidence}</div></article>'


# Compatibility aliases for the legacy universe-compatible rendering path below.
_metric = _render_metric_card
_argument = _render_argument_card


def _sensitivity_table(title: str, matrix: dict[str, Any], column_label: str) -> str:
    headers = "".join(f"<th>{_pct(value)}</th>" for value in matrix["column_axis"])
    rows = "".join(
        f"<tr><th>{_pct(wacc)}</th>"
        + "".join(
            "<td>Invalid</td>" if value is None else f"<td>{_money(value)}</td>" for value in values
        )
        + "</tr>"
        for wacc, values in zip(matrix["row_axis"], matrix["cells"], strict=True)
    )
    return (
        f'<div class="panel"><h3>{_e(title)}</h3><div class="provenance">'
        f"<table><tr><th>WACC / {column_label}</th>{headers}</tr>{rows}</table></div></div>"
    )


def _render_header(identity: dict[str, Any]) -> str:
    classification = identity["classification"]
    return f"""<header class="dashboard-header"><div><div class="text-label">Qhapaq Finance · Research Dashboard</div><h1>{_e(identity["ticker"])}</h1><div>{_e(identity["company_name"])}</div></div><div class="header-meta"><span class="status-badge {"fixture" if classification == "fixture" else "evidence"}">{_e(classification)}</span><p class="metadata-text">Research as-of {_e(identity["research_as_of"])}<br>Latest filing {_e(identity["latest_filing_accession"] or "Unavailable")}<br>Market snapshot {_e(identity["market_snapshot_date"] or "Unavailable")}</p></div></header><div class="toolbar"><div class="control-group view-toggle" aria-label="Dashboard view"><span class="control-label">View</span><button id="simple" aria-pressed="true">Simple view</button><button id="research" aria-pressed="false">Research view</button></div>{_theme_toggle()}</div>"""


def _render_simple_view(artifact: dict[str, Any]) -> str:
    market, economics, valuation = artifact["market"], artifact["economics"], artifact["valuation"]
    base, narrative = valuation["scenarios"]["base"], artifact["explainability"]["narrative"]
    above = market["price"] > base["intrinsic_value"]
    hero = (
        "STRONG BUSINESS · DEMANDING PRICE"
        if economics["roic"] > economics["wacc"] and above
        else _e(narrative["headline"]["statement"]).upper()
    )
    distance = -base["margin_of_safety"] if above else base["margin_of_safety"]
    direction, helper, tone = (
        ("ABOVE", "No valuation cushion under our base case.", "price-above")
        if above
        else ("BELOW", "A valuation cushion exists under our base case.", "price-below")
    )
    arguments = (
        ("PRICE", "valuation_argument"),
        ("BUSINESS QUALITY", "economic_quality_argument"),
        ("MARKET EXPECTATIONS", "expectations_argument"),
        ("LONG-TERM DEPENDENCE", "fragility_argument"),
    )
    concepts = "".join(
        f"<tr><td>{_e(name.replace('_', ' '))}</td><td>{_e(value)}</td></tr>"
        for name, value in artifact["explainability"]["concepts"].items()
    )
    summary = (
        narrative["plain_language_summary"]["statement"]
        if not above
        else "This business appears economically strong, but today’s price requires better results than our base case assumes."
    )
    metrics = "".join(
        (
            _render_metric_card("Current price", _money(market["price"])),
            _render_metric_card("Base value", _money(base["intrinsic_value"])),
            _render_metric_card(
                "Price vs base value",
                f'<span class="{tone}">{_pct(distance)} {direction}</span>',
                helper,
            ),
        )
    )
    why = "".join(
        _render_argument_card(narrative[key], title, simple=True) for title, key in arguments
    )
    must = "".join(
        _render_argument_card(item, simple=True) for item in narrative["what_must_be_true"]
    )
    breaks = "".join(
        _render_argument_card(item, simple=True) for item in narrative["what_could_break"]
    )
    unknowns = "".join(
        _render_argument_card(item, simple=True) for item in narrative["open_questions"]
    )
    return f"""<section class="simple-only simple-template"><div class="simple-hero"><div class="text-label">What Qhapaq believes</div><h2>{hero}</h2><p>{_e(summary)}</p></div><h2>Price vs base value</h2><div class="metric-grid decision-metrics">{metrics}</div><h2>Why?</h2><div class="argument-grid">{why}</div><section class="decision-conditions"><h2>Decision conditions</h2><div class="decision-conditions-grid"><div><h3>What must go right</h3>{must}</div><div><h3>What could break</h3>{breaks}</div><div><h3>What we don't know</h3>{unknowns}</div></div></section><h2>Financial concepts</h2><details><summary>Show plain-language definitions</summary><table>{concepts}</table></details></section>"""


def _render_buy_zones(zones: dict[str, Any]) -> str:
    rows = "".join(
        f"<tr><td>{label}</td><td>{_money(value)}</td></tr>"
        for label, value in (
            ("Fair value", zones["fair_value"]),
            ("10% MOS", zones["mos_10"]),
            ("20% MOS", zones["mos_20"]),
            ("25% MOS", zones["mos_25"]),
            ("30% MOS", zones["mos_30"]),
        )
    )
    return f'<div class="research-panel buy-zone"><h2>Buy-zone reference</h2><div class="text-label">{_e(zones["classification"])} · valuation distance</div><div class="buy-zone-scale"><span>30% MOS<br>{_money(zones["mos_30"])}</span><span>20% MOS<br>{_money(zones["mos_20"])}</span><span>FAIR<br>{_money(zones["fair_value"])}</span><span class="current">CURRENT<br>{_money(zones["current_price"])}</span></div><div class="buy-zone-line" aria-label="Current price is compared with fair value and margin-of-safety zones"></div><table>{rows}</table></div>'


def _render_evidence(artifact: dict[str, Any]) -> str:
    facts = "".join(
        f'<tr><td>{_e(item["id"])}</td><td>{_e(item["topic"])}</td><td>{_e(item["statement"])}</td><td><span class="epistemic-badge {_e(item["status"])}">{_e(item["status"].replace("_", " "))}</span></td><td>{_e(", ".join(item["evidence_ids"]))}</td></tr>'
        for item in artifact["explainability"]["facts"]
    )
    provenance = (
        "".join(
            f"<tr><td>{_e(item['metric'])}</td><td>{_e(item['value'])}</td><td>{_e(item['classification'])}</td><td>{_e(item['period'])}</td><td>{_e(item['filing_accession'])}</td><td>{_e(item['concept_tag'])}</td><td>{_e(item['fact_id'])}</td><td>{_e(item['selection_method'])}</td></tr>"
            for item in artifact["provenance"]
        )
        or "<tr><td colspan=8>Unavailable for illustrative fixture.</td></tr>"
    )
    return f'<section><h2>Evidence and provenance</h2><details><summary>Show semantic fact catalog</summary><div class="provenance"><table><tr><th>Fact ID</th><th>Topic</th><th>Statement</th><th>Type</th><th>Evidence IDs</th></tr>{facts}</table></div></details><details><summary>Show source records</summary><div class="toolbar"><input id="search" placeholder="Filter metric, filing, tag, or fact ID"></div><div class="provenance"><table id="provenance"><tr><th>Metric</th><th>Value</th><th>Type</th><th>Period</th><th>Filing</th><th>Concept/tag</th><th>Fact ID</th><th>Selection</th></tr>{provenance}</table></div></details></section>'


def _render_research_view(artifact: dict[str, Any]) -> str:
    market, economics, valuation, b, zones = (
        artifact[key] for key in ("market", "economics", "valuation", "bridges", "decision_zones")
    )
    base, bridge = valuation["scenarios"]["base"], b["enterprise_to_equity"]
    decision = "".join(
        (
            _render_metric_card("Price", _money(market["price"])),
            _render_metric_card("Base value", _money(base["intrinsic_value"])),
            _render_metric_card("Base MOS", _pct(base["margin_of_safety"])),
        )
    )
    analytical = "".join(
        (
            _render_metric_card("ROIC", _pct(economics["roic"])),
            _render_metric_card("WACC", _pct(economics["wacc"])),
            _render_metric_card("ROIC − WACC", _pp(economics["roic_minus_wacc"])),
            _render_metric_card(
                "Reverse DCF growth", _pct(valuation["reverse_dcf_implied_growth"])
            ),
            _render_metric_card("Terminal value share", _pct(base["terminal_value_share"])),
        )
    )
    sensitivity = _sensitivity_table(
        "WACC × terminal growth", artifact["sensitivity"]["wacc_terminal_growth"], "terminal growth"
    ) + _sensitivity_table(
        "WACC × explicit FCFF growth", artifact["sensitivity"]["wacc_explicit_growth"], "growth"
    )
    scenarios = "".join(
        f'<div class="research-panel scenario {name}"><h3>{_e(item["name"])}</h3><div class="metric-value">{_money(item["intrinsic_value"])}</div><p>MOS {_pct(item["margin_of_safety"])} · growth {_pct(item["explicit_growth"])} · WACC {_pct(item["wacc"])} · terminal growth {_pct(item["terminal_growth"])} · TV {_pct(item["terminal_value_share"])}</p></div>'
        for name, item in valuation["scenarios"].items()
    )
    ttm = "<p>Unavailable for illustrative fixtures.</p>"
    if b["ttm"]:
        ttm_rows = "".join(
            f"<tr><td>{label}</td>{''.join(f'<td>{_millions(value)}</td>' for value in values)}</tr>"
            for label, values in (("Revenue", b["ttm"]["revenue"]), ("EBIT", b["ttm"]["ebit"]))
        )
        labels = "".join(f"<th>{_e(label)}</th>" for label in b["ttm"]["labels"])
        ttm = f"<p>{_e(b['ttm']['formula'])}</p><table><tr><th>Metric</th>{labels}</tr>{ttm_rows}</table>"
    return f"""<div class="research-only research-template"><section><h2>Decision metrics</h2><div class="metric-grid decision-metrics">{decision}</div><h2>Analytical metrics</h2><div class="metric-grid analytical-metrics">{analytical}</div></section><section class="two-column"><div class="research-panel"><h2>Research thesis</h2><p>{_e(artifact["decision"]["interpretation"])}</p><h3>Primary thesis</h3><ul>{_items(artifact["decision"]["thesis"])}</ul><h3>Invalidation</h3><ul>{_items(artifact["decision"]["invalidation_conditions"])}</ul></div>{_render_buy_zones(zones)}</section><section class="two-column"><div class="research-panel"><h2>Market expectations</h2><table><tr><td>Market-implied FCFF growth</td><td>{_pct(valuation["reverse_dcf_implied_growth"])}</td></tr><tr><td>Qhapaq base growth</td><td>{_pct(base["explicit_growth"])}</td></tr><tr><td>Difference</td><td>{_pp(valuation["expectations"]["growth_difference_pp"])}</td></tr><tr><td>FCFF implied discount rate / WACC</td><td>{_pct(valuation["fcff_implied_discount_rate"])} / {_pct(economics["wacc"])}</td></tr></table></div><div class="research-panel"><h2>Economic quality</h2><table><tr><td>ROIC / WACC / spread</td><td>{_pct(economics["roic"])} / {_pct(economics["wacc"])} / {_pp(economics["roic_minus_wacc"])}</td></tr><tr><td>Revenue / EBIT</td><td>{_millions(economics["revenue_ttm"])} / {_millions(economics["ebit_ttm"])}</td></tr><tr><td>NOPAT / FCFF</td><td>{_millions(economics["nopat"])} / {_millions(economics["normalized_fcff"])}</td></tr></table></div></section><section><h2>Sensitivity</h2><div class="two-column">{sensitivity}</div></section><section><h2>Valuation scenarios</h2><div class="three-column">{scenarios}</div><div class="research-panel"><h3>Terminal dependence · base case</h3><p class="numeric">PV explicit period {_millions(base["pv_explicit_period"])} · PV terminal value {_millions(base["pv_terminal_value"])} · terminal-value share {_pct(base["terminal_value_share"])}. {_e(" | ".join(base["warnings"]) or "No terminal-value warning.")}</p></div></section><section><h2>Financial bridges</h2><div class="two-column"><div class="research-panel"><h3>Enterprise to equity</h3><table><tr><td>Enterprise value</td><td>{_millions(bridge["enterprise_value"])}</td></tr><tr><td>+ Cash and securities</td><td>{_millions(bridge["liquid_assets"])}</td></tr><tr><td>− Debt / senior claims</td><td>{_millions(bridge["debt"] + bridge["senior_claims"])}</td></tr><tr><td>= Equity value</td><td>{_millions(bridge["equity_value"])}</td></tr><tr><td>/ Shares</td><td>{_millions(bridge["shares"])}</td></tr><tr><td>= Base intrinsic value/share</td><td>{_money(base["intrinsic_value"])}</td></tr></table></div><div class="research-panel"><h3>FCFF bridge</h3><table><tr><td>EBIT</td><td>{_millions(b["fcff"]["ebit"])}</td></tr><tr><td>Cash taxes / NOPAT adjustment</td><td>{_pct(b["fcff"]["tax_rate"])}</td></tr><tr><td>= NOPAT</td><td>{_millions(b["fcff"]["nopat"])}</td></tr><tr><td>+ D&A − Capex − change NWC</td><td>{_millions(b["fcff"]["da"])} − {_millions(b["fcff"]["capex"])} − {_millions(b["fcff"]["change_nwc"])}</td></tr><tr><td>= Normalized FCFF</td><td>{_millions(b["fcff"]["normalized_fcff"])}</td></tr></table></div></div><div class="research-panel"><h3>TTM bridge</h3>{ttm}</div></section><section class="three-column"><div class="research-panel"><h2>Key risks</h2><ul>{_items(artifact["decision"]["risks"])}</ul></div><div class="research-panel"><h2>Research gaps</h2><ul>{_items(artifact["decision"]["research_gaps"])}</ul></div><div class="research-panel"><h2>Data quality</h2><ul>{_items(artifact["decision"]["data_quality_warnings"])}</ul></div></section>{_render_evidence(artifact)}</div>"""


def render_company_dashboard(artifact: dict[str, Any], output: str | Path) -> Path:
    """Render an embedded-data HTML file; JavaScript only filters provenance."""
    payload = canonical_json(artifact).replace("</", "<\\/")
    identity = artifact["identity"]
    controls = """function setViewMode(view){main.dataset.view=view;simple.setAttribute('aria-pressed',String(view==='simple'));research.setAttribute('aria-pressed',String(view==='research'));}function initViewMode(){simple.addEventListener('click',()=>setViewMode('simple'));research.addEventListener('click',()=>setViewMode('research'));}function initDisclosures(){document.getElementById('search')?.addEventListener('input',event=>document.querySelectorAll('#provenance tr').forEach((row,index)=>{if(index)row.hidden=!row.textContent.toLowerCase().includes(event.target.value.toLowerCase())}));}const main=document.querySelector('main');const simple=document.getElementById('simple');const research=document.getElementById('research');initViewMode();initDisclosures();"""
    page = f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Qhapaq · {_e(identity["ticker"])}</title><style>{_css()}</style>{_theme_initializer()}<main data-view="simple">{_render_header(identity)}{_render_simple_view(artifact)}{_render_research_view(artifact)}</main><script type="application/json" id="qhapaq-data">{payload}</script><script>{_theme_controls()}{controls}</script></html>"""
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(page, encoding="utf-8")
    return destination

    # Kept below temporarily by the historical patch context.
    identity, market, economics, valuation = (
        artifact[key] for key in ("identity", "market", "economics", "valuation")
    )
    base = valuation["scenarios"]["base"]
    narrative = artifact["explainability"]["narrative"]
    simple_arguments = "".join(
        _argument(narrative[name])
        for name in (
            "valuation_argument",
            "economic_quality_argument",
            "expectations_argument",
            "fragility_argument",
        )
    )
    must = "".join(_argument(item) for item in narrative["what_must_be_true"])
    breaks = "".join(_argument(item) for item in narrative["what_could_break"])
    questions = "".join(_argument(item) for item in narrative["open_questions"])
    concepts = "".join(
        f"<tr><td>{_e(name.replace('_', ' '))}</td><td>{_e(value)}</td></tr>"
        for name, value in artifact["explainability"]["concepts"].items()
    )
    metrics = "".join(
        [
            _metric("Price", _money(market["price"])),
            _metric("Base value", _money(base["intrinsic_value"])),
            _metric("Base MOS", _pct(base["margin_of_safety"])),
            _metric("ROIC", _pct(economics["roic"])),
            _metric("WACC", _pct(economics["wacc"])),
            _metric("ROIC − WACC", _pct(economics["roic_minus_wacc"])),
            _metric("Reverse DCF growth", _pct(valuation["reverse_dcf_implied_growth"])),
            _metric("Terminal value share", _pct(base["terminal_value_share"])),
        ]
    )
    scenarios = "".join(
        f'<div class="panel scenario {name}"><h3>{_e(item["name"])}</h3><div class="value">{_money(item["intrinsic_value"])}</div>'
        f"<p>MOS {_pct(item['margin_of_safety'])} · growth {_pct(item['explicit_growth'])} · WACC {_pct(item['wacc'])} · terminal growth {_pct(item['terminal_growth'])} · TV {_pct(item['terminal_value_share'])}</p></div>"
        for name, item in valuation["scenarios"].items()
    )
    b = artifact["bridges"]
    ttm = "<p>Unavailable for illustrative fixtures.</p>"
    if b["ttm"]:
        rows = "".join(
            f"<tr><td>{label}</td><td>{_millions(values[0])}</td><td>{_millions(values[1])}</td><td>{_millions(values[2])}</td><td>{_millions(values[3])}</td></tr>"
            for label, values in (("Revenue", b["ttm"]["revenue"]), ("EBIT", b["ttm"]["ebit"]))
        )
        ttm = f"<p>{_e(b['ttm']['formula'])}</p><table><tr><th>Metric</th><th>FY</th><th>Prior 9M</th><th>Current 9M</th><th>TTM</th></tr>{rows}</table>"
    provenance_rows = (
        "".join(
            f"<tr><td>{_e(item['metric'])}</td><td>{_e(item['value'])}</td><td>{_e(item['classification'])}</td><td>{_e(item['period'])}</td><td>{_e(item['filing_accession'])}</td><td>{_e(item['concept_tag'])}</td><td>{_e(item['fact_id'])}</td><td>{_e(item['selection_method'])}</td></tr>"
            for item in artifact["provenance"]
        )
        or "<tr><td colspan=8>Unavailable for illustrative fixture.</td></tr>"
    )
    bridge = b["enterprise_to_equity"]
    zones = artifact["decision_zones"]
    sensitivity = _sensitivity_table(
        "WACC × terminal growth", artifact["sensitivity"]["wacc_terminal_growth"], "terminal growth"
    ) + _sensitivity_table(
        "WACC × explicit FCFF growth", artifact["sensitivity"]["wacc_explicit_growth"], "growth"
    )
    payload = canonical_json(artifact).replace("</", "<\\/")
    page = f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Qhapaq · {_e(identity["ticker"])}</title><style>{_css()}</style>{_theme_initializer()}<main data-view="simple">
<header class="top"><div><div class="brand">Qhapaq Finance · Research Dashboard</div><h1>{_e(identity["ticker"])}</h1><div>{_e(identity["company_name"])}</div></div><div><span class="tag {"fixture" if identity["classification"] == "fixture" else "evidence"}">{_e(identity["classification"])}</span><p class="label">Research as-of {_e(identity["research_as_of"])}<br>Latest filing {_e(identity["latest_filing_accession"] or "Unavailable")}<br>Market snapshot {_e(identity["market_snapshot_date"] or "Unavailable")}</p></div></header>
<div class="toolbar"><div class="control-group view-toggle" aria-label="Dashboard view"><span class="control-label">View</span><button id="simple" aria-pressed="true">Simple view</button><button id="research" aria-pressed="false">Research view</button></div>{_theme_toggle()}</div>
<section class="simple-only"><h2>What this means</h2>{_argument(narrative["plain_language_summary"])}<h2>Price vs value</h2><div class="grid">{_metric("Price", _money(market["price"]))}{_metric("Base value", _money(base["intrinsic_value"]))}{_metric("Margin of safety", _pct(base["margin_of_safety"]))}</div><h2>Why Qhapaq thinks this</h2><div class="twocol">{simple_arguments}</div><h2>What must go right</h2><div class="twocol">{must}</div><h2>What could break the thesis</h2><div class="twocol">{breaks}</div><h2>What we do not know</h2><div class="twocol">{questions}</div><h2>Financial concepts</h2><details><summary>Show plain-language definitions</summary><table>{concepts}</table></details></section>
<div class="research-only"><section><h2>Price vs value</h2><div class="grid">{metrics}</div><div class="panel"><h3>{_e(zones["classification"])} · valuation distance</h3><p>30% MOS {_money(zones["mos_30"])} — 25% {_money(zones["mos_25"])} — 20% {_money(zones["mos_20"])} — 10% {_money(zones["mos_10"])} — fair value {_money(zones["fair_value"])} — current price {_money(zones["current_price"])}.</p></div></section>
<section class="twocol"><div class="panel"><h2>Decision · {_e(artifact["decision"]["status"])}</h2><p>{_e(artifact["decision"]["interpretation"])}</p><h3>Primary thesis</h3><ul>{_items(artifact["decision"]["thesis"])}</ul><h3>Invalidation</h3><ul>{_items(artifact["decision"]["invalidation_conditions"])}</ul></div><div class="panel"><h2>Buy-zone reference</h2><table><tr><td>Fair value</td><td>{_money(zones["fair_value"])}</td></tr><tr><td>10% MOS</td><td>{_money(zones["mos_10"])}</td></tr><tr><td>20% MOS</td><td>{_money(zones["mos_20"])}</td></tr><tr><td>25% MOS</td><td>{_money(zones["mos_25"])}</td></tr><tr><td>30% MOS</td><td>{_money(zones["mos_30"])}</td></tr></table></div></section>
<section class="twocol"><div class="panel"><h2>Market expectations</h2><table><tr><td>Market-implied FCFF growth</td><td>{_pct(valuation["reverse_dcf_implied_growth"])}</td></tr><tr><td>Qhapaq base growth</td><td>{_pct(base["explicit_growth"])}</td></tr><tr><td>Difference</td><td>{_pp(valuation["expectations"]["growth_difference_pp"])}</td></tr><tr><td>FCFF implied discount rate / WACC</td><td>{_pct(valuation["fcff_implied_discount_rate"])} / {_pct(economics["wacc"])}</td></tr><tr><td>Difference</td><td>{_pp(valuation["expectations"]["discount_rate_difference_pp"])}</td></tr></table></div><div class="panel"><h2>Economic quality</h2><table><tr><td>ROIC / WACC / spread</td><td>{_pct(economics["roic"])} / {_pct(economics["wacc"])} / {_pct(economics["roic_minus_wacc"])}</td></tr><tr><td>Revenue / EBIT</td><td>{_millions(economics["revenue_ttm"])} / {_millions(economics["ebit_ttm"])}</td></tr><tr><td>NOPAT / FCFF</td><td>{_millions(economics["nopat"])} / {_millions(economics["normalized_fcff"])}</td></tr><tr><td>FCFF yield</td><td>{_pct(economics["fcff_yield"])}</td></tr></table></div></section>
<section><h2>Sensitivity</h2><div class="twocol">{sensitivity}</div></section>
<section><h2>Valuation scenarios</h2><div class="three">{scenarios}</div><div class="panel"><h3>Terminal dependence · base case</h3><p>PV explicit period {_millions(base["pv_explicit_period"])} · PV terminal value {_millions(base["pv_terminal_value"])} · terminal-value share {_pct(base["terminal_value_share"])}. {_e(" | ".join(base["warnings"]) or "No terminal-value warning.")}</p></div></section>
<section><h2>Valuation bridge</h2><table><tr><td>Enterprise value</td><td>{_millions(bridge["enterprise_value"])}</td></tr><tr><td>+ Cash and securities</td><td>{_millions(bridge["liquid_assets"])}</td></tr><tr><td>− Debt / senior claims</td><td>{_millions(bridge["debt"] + bridge["senior_claims"])}</td></tr><tr><td>= Equity value</td><td>{_millions(bridge["equity_value"])}</td></tr><tr><td>/ Shares</td><td>{_millions(bridge["shares"])}</td></tr><tr><td>= Base intrinsic value/share</td><td>{_money(base["intrinsic_value"])}</td></tr></table></section>
<section><h2>TTM bridge</h2>{ttm}</section>
<section><h2>FCFF bridge</h2><table><tr><td>EBIT</td><td>{_millions(b["fcff"]["ebit"])}</td></tr><tr><td>Cash taxes / NOPAT adjustment</td><td>{_pct(b["fcff"]["tax_rate"])}</td></tr><tr><td>= NOPAT</td><td>{_millions(b["fcff"]["nopat"])}</td></tr><tr><td>+ D&A − Capex − change NWC</td><td>{_millions(b["fcff"]["da"])} − {_millions(b["fcff"]["capex"])} − {_millions(b["fcff"]["change_nwc"])}</td></tr><tr><td>= Reconstructed FCFF</td><td>{_millions(b["fcff"]["reconstructed_fcff"])}</td></tr><tr><td>± Normalization</td><td>{_millions(b["fcff"]["normalization_adjustments"])}</td></tr><tr><td>= Normalized FCFF</td><td>{_millions(b["fcff"]["normalized_fcff"])}</td></tr></table></section>
<section class="three"><div class="panel"><h2>Key risks</h2><ul>{_items(artifact["decision"]["risks"])}</ul></div><div class="panel"><h2>Research gaps</h2><ul>{_items(artifact["decision"]["research_gaps"])}</ul></div><div class="panel"><h2>Data quality</h2><ul>{_items(artifact["decision"]["data_quality_warnings"])}</ul></div></section>
<section><h2>Evidence and provenance</h2><details><summary>Show semantic fact catalog</summary><div class="provenance"><table><tr><th>Fact ID</th><th>Topic</th><th>Statement</th><th>Type</th><th>Evidence IDs</th></tr>{"".join(f'<tr><td>{_e(item["id"])}</td><td>{_e(item["topic"])}</td><td>{_e(item["statement"])}</td><td><span class="epistemic {_e(item["status"])}">{_e(item["status"].replace("_", " "))}</span></td><td>{_e(", ".join(item["evidence_ids"]))}</td></tr>' for item in artifact["explainability"]["facts"])}</table></div></details><details><summary>Show source records</summary><div class="toolbar"><input id="search" placeholder="Filter metric, filing, tag, or fact ID"></div><div class="provenance"><table id="provenance"><tr><th>Metric</th><th>Value</th><th>Type</th><th>Period</th><th>Filing</th><th>Concept/tag</th><th>Fact ID</th><th>Selection</th></tr>{provenance_rows}</table></div></details></section>
</div></main><script type="application/json" id="qhapaq-data">{payload}</script><script>{_theme_controls()}const main=document.querySelector('main');const simple=document.getElementById('simple');const research=document.getElementById('research');simple.addEventListener('click',()=>{{main.dataset.view='simple';simple.setAttribute('aria-pressed','true');research.setAttribute('aria-pressed','false')}});research.addEventListener('click',()=>{{main.dataset.view='research';research.setAttribute('aria-pressed','true');simple.setAttribute('aria-pressed','false')}});document.getElementById('search')?.addEventListener('input',e=>document.querySelectorAll('#provenance tr').forEach((r,i)=>{{if(i)r.hidden=!r.textContent.toLowerCase().includes(e.target.value.toLowerCase())}}));</script></html>"""
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(page, encoding="utf-8")
    return destination


def render_universe_dashboard(artifact: dict[str, Any], output: str | Path) -> Path:
    rows = "".join(
        f"<tr><td>{_e(company['identity']['ticker'])}</td><td>{_money(company['market']['price'])}</td><td>{_money(company['valuation']['scenarios']['base']['intrinsic_value'])}</td><td>{_pct(company['valuation']['scenarios']['base']['margin_of_safety'])}</td><td>{_pct(company['economics']['roic'])}</td><td>{_pct(company['economics']['wacc'])}</td><td>{_pct(company['economics']['roic_minus_wacc'])}</td><td>{_pct(company['economics']['fcff_yield'])}</td><td>{_pct(company['valuation']['reverse_dcf_implied_growth'])}</td><td>{_pct(company['valuation']['fcff_implied_discount_rate'])}</td><td>{_pct(company['valuation']['scenarios']['base']['terminal_value_share'])}</td><td>{_e(company['identity']['status'])}</td><td>{_e(company['identity']['classification'])}</td></tr>"
        for company in artifact["companies"]
    )
    payload = canonical_json(artifact).replace("</", "<\\/")
    evidence_count = sum(
        item["identity"]["classification"] == "evidence-backed" for item in artifact["companies"]
    )
    fixture_count = len(artifact["companies"]) - evidence_count
    controls = (
        _theme_controls()
        + """const table=document.getElementById('universe');const body=[...table.rows].slice(1);
document.getElementById('search').addEventListener('input',e=>body.forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(e.target.value.toLowerCase())));
[...table.rows[0].cells].forEach((head,index)=>head.addEventListener('click',()=>body.sort((a,b)=>a.cells[index].textContent.localeCompare(b.cells[index].textContent,undefined,{numeric:true})).forEach(row=>table.appendChild(row))));"""
    )
    page = f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Qhapaq · Universe</title><style>{_css()}</style>{_theme_initializer()}<main><header class="top"><div><div class="brand">Qhapaq Finance · Research Dashboard</div><h1>Universe</h1></div><div class="label">Research as-of {_e(artifact["research_as_of"])}<br>{len(artifact["companies"])} companies · {evidence_count} evidence-backed · {fixture_count} fixtures</div></header><section><div class="toolbar">{_theme_toggle()}<input id="search" placeholder="Filter ticker, status, or data quality"></div><table id="universe"><tr><th>Ticker</th><th>Price</th><th>Base value</th><th>Base MOS</th><th>ROIC</th><th>WACC</th><th>ROIC − WACC</th><th>FCFF yield</th><th>Reverse DCF</th><th>FCFF rate</th><th>TV share</th><th>Status</th><th>Data quality</th></tr>{rows}</table></section></main><script type="application/json" id="qhapaq-data">{payload}</script><script>{controls}</script></html>"""
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(page, encoding="utf-8")
    return destination
