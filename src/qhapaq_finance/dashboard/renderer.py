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
:root{--bg:#fafafa;--paper:#fff;--ink:#17212b;--muted:#65717d;--line:#dce1e5;--blue:#1b4965;--good:#245c45;--warn:#805d18;--bad:#8a3d38}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 Arial,sans-serif}main{max-width:1320px;margin:auto;padding:28px}.top{display:flex;justify-content:space-between;border-bottom:2px solid var(--ink);padding-bottom:14px}.brand,.eyebrow{font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}h1{margin:4px 0;font:700 42px Georgia,serif}h2{margin:34px 0 12px;font:700 21px Georgia,serif}h3{margin:0 0 8px;font-size:12px;letter-spacing:.08em}.tag{border:1px solid var(--line);padding:4px 7px;font-size:11px;font-weight:bold}.tag.evidence{color:var(--good)}.tag.fixture{color:var(--warn)}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.card,.panel{background:var(--paper);border:1px solid var(--line);padding:15px}.label{font-size:11px;text-transform:uppercase;color:var(--muted)}.value{font-size:23px;font-weight:700;margin-top:5px}.twocol{display:grid;grid-template-columns:1fr 1fr;gap:12px}.three{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.scenario.base{border-top:3px solid var(--blue)}.negative{color:var(--bad)}.positive{color:var(--good)}table{width:100%;border-collapse:collapse;font-size:12px;background:var(--paper)}th,td{padding:9px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left}th{color:var(--muted);font-size:10px;text-transform:uppercase;cursor:pointer}ul{padding-left:18px;margin:7px 0}details{background:var(--paper);border:1px solid var(--line);padding:12px}summary{cursor:pointer;font-weight:bold}.provenance{max-height:380px;overflow:auto}.toolbar{display:flex;gap:8px;margin:10px 0}input{padding:8px;border:1px solid var(--line);width:280px}button{padding:8px 10px;background:white;border:1px solid var(--line);cursor:pointer}@media(max-width:850px){main{padding:18px}.grid{grid-template-columns:repeat(2,1fr)}.three,.twocol{grid-template-columns:1fr}.top{display:block}table{display:block;overflow-x:auto}.card{min-height:0}}
"""


def _metric(label: str, value: str, extra: str = "") -> str:
    return f'<div class="card"><div class="label">{_e(label)}</div><div class="value">{value}</div><div class="label">{_e(extra)}</div></div>'


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


def render_company_dashboard(artifact: dict[str, Any], output: str | Path) -> Path:
    """Render an embedded-data HTML file; JavaScript only filters provenance."""
    identity, market, economics, valuation = (
        artifact[key] for key in ("identity", "market", "economics", "valuation")
    )
    base = valuation["scenarios"]["base"]
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
    page = f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Qhapaq · {_e(identity["ticker"])}</title><style>{_css()}</style><main>
<header class="top"><div><div class="brand">Qhapaq Finance · Research Dashboard</div><h1>{_e(identity["ticker"])}</h1><div>{_e(identity["company_name"])}</div></div><div><span class="tag {"fixture" if identity["classification"] == "fixture" else "evidence"}">{_e(identity["classification"])}</span><p class="label">Research as-of {_e(identity["research_as_of"])}<br>Latest filing {_e(identity["latest_filing_accession"] or "Unavailable")}<br>Market snapshot {_e(identity["market_snapshot_date"] or "Unavailable")}</p></div></header>
<section><h2>Price vs value</h2><div class="grid">{metrics}</div><div class="panel"><h3>{_e(zones["classification"])} · valuation distance</h3><p>30% MOS {_money(zones["mos_30"])} — 25% {_money(zones["mos_25"])} — 20% {_money(zones["mos_20"])} — 10% {_money(zones["mos_10"])} — fair value {_money(zones["fair_value"])} — current price {_money(zones["current_price"])}.</p></div></section>
<section class="twocol"><div class="panel"><h2>Decision · {_e(artifact["decision"]["status"])}</h2><p>{_e(artifact["decision"]["interpretation"])}</p><h3>Primary thesis</h3><ul>{_items(artifact["decision"]["thesis"])}</ul><h3>Invalidation</h3><ul>{_items(artifact["decision"]["invalidation_conditions"])}</ul></div><div class="panel"><h2>Buy-zone reference</h2><table><tr><td>Fair value</td><td>{_money(zones["fair_value"])}</td></tr><tr><td>10% MOS</td><td>{_money(zones["mos_10"])}</td></tr><tr><td>20% MOS</td><td>{_money(zones["mos_20"])}</td></tr><tr><td>25% MOS</td><td>{_money(zones["mos_25"])}</td></tr><tr><td>30% MOS</td><td>{_money(zones["mos_30"])}</td></tr></table></div></section>
<section class="twocol"><div class="panel"><h2>Market expectations</h2><table><tr><td>Market-implied FCFF growth</td><td>{_pct(valuation["reverse_dcf_implied_growth"])}</td></tr><tr><td>Qhapaq base growth</td><td>{_pct(base["explicit_growth"])}</td></tr><tr><td>Difference</td><td>{_pp(valuation["expectations"]["growth_difference_pp"])}</td></tr><tr><td>FCFF implied discount rate / WACC</td><td>{_pct(valuation["fcff_implied_discount_rate"])} / {_pct(economics["wacc"])}</td></tr><tr><td>Difference</td><td>{_pp(valuation["expectations"]["discount_rate_difference_pp"])}</td></tr></table></div><div class="panel"><h2>Economic quality</h2><table><tr><td>ROIC / WACC / spread</td><td>{_pct(economics["roic"])} / {_pct(economics["wacc"])} / {_pct(economics["roic_minus_wacc"])}</td></tr><tr><td>Revenue / EBIT</td><td>{_millions(economics["revenue_ttm"])} / {_millions(economics["ebit_ttm"])}</td></tr><tr><td>NOPAT / FCFF</td><td>{_millions(economics["nopat"])} / {_millions(economics["normalized_fcff"])}</td></tr><tr><td>FCFF yield</td><td>{_pct(economics["fcff_yield"])}</td></tr></table></div></section>
<section><h2>Sensitivity</h2><div class="twocol">{sensitivity}</div></section>
<section><h2>Valuation scenarios</h2><div class="three">{scenarios}</div><div class="panel"><h3>Terminal dependence · base case</h3><p>PV explicit period {_millions(base["pv_explicit_period"])} · PV terminal value {_millions(base["pv_terminal_value"])} · terminal-value share {_pct(base["terminal_value_share"])}. {_e(" | ".join(base["warnings"]) or "No terminal-value warning.")}</p></div></section>
<section><h2>Valuation bridge</h2><table><tr><td>Enterprise value</td><td>{_millions(bridge["enterprise_value"])}</td></tr><tr><td>+ Cash and securities</td><td>{_millions(bridge["liquid_assets"])}</td></tr><tr><td>− Debt / senior claims</td><td>{_millions(bridge["debt"] + bridge["senior_claims"])}</td></tr><tr><td>= Equity value</td><td>{_millions(bridge["equity_value"])}</td></tr><tr><td>/ Shares</td><td>{_millions(bridge["shares"])}</td></tr><tr><td>= Base intrinsic value/share</td><td>{_money(base["intrinsic_value"])}</td></tr></table></section>
<section><h2>TTM bridge</h2>{ttm}</section>
<section><h2>FCFF bridge</h2><table><tr><td>EBIT</td><td>{_millions(b["fcff"]["ebit"])}</td></tr><tr><td>Cash taxes / NOPAT adjustment</td><td>{_pct(b["fcff"]["tax_rate"])}</td></tr><tr><td>= NOPAT</td><td>{_millions(b["fcff"]["nopat"])}</td></tr><tr><td>+ D&A − Capex − change NWC</td><td>{_millions(b["fcff"]["da"])} − {_millions(b["fcff"]["capex"])} − {_millions(b["fcff"]["change_nwc"])}</td></tr><tr><td>= Reconstructed FCFF</td><td>{_millions(b["fcff"]["reconstructed_fcff"])}</td></tr><tr><td>± Normalization</td><td>{_millions(b["fcff"]["normalization_adjustments"])}</td></tr><tr><td>= Normalized FCFF</td><td>{_millions(b["fcff"]["normalized_fcff"])}</td></tr></table></section>
<section class="three"><div class="panel"><h2>Key risks</h2><ul>{_items(artifact["decision"]["risks"])}</ul></div><div class="panel"><h2>Research gaps</h2><ul>{_items(artifact["decision"]["research_gaps"])}</ul></div><div class="panel"><h2>Data quality</h2><ul>{_items(artifact["decision"]["data_quality_warnings"])}</ul></div></section>
<section><h2>Provenance</h2><details><summary>Show source records</summary><div class="toolbar"><input id="search" placeholder="Filter metric, filing, tag, or fact ID"></div><div class="provenance"><table id="provenance"><tr><th>Metric</th><th>Value</th><th>Type</th><th>Period</th><th>Filing</th><th>Concept/tag</th><th>Fact ID</th><th>Selection</th></tr>{provenance_rows}</table></div></details></section>
</main><script type="application/json" id="qhapaq-data">{payload}</script><script>document.getElementById('search')?.addEventListener('input',e=>document.querySelectorAll('#provenance tr').forEach((r,i)=>{{if(i)r.hidden=!r.textContent.toLowerCase().includes(e.target.value.toLowerCase())}}));</script></html>"""
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
    controls = """const table=document.getElementById('universe');const body=[...table.rows].slice(1);
document.getElementById('search').addEventListener('input',e=>body.forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(e.target.value.toLowerCase())));
[...table.rows[0].cells].forEach((head,index)=>head.addEventListener('click',()=>body.sort((a,b)=>a.cells[index].textContent.localeCompare(b.cells[index].textContent,undefined,{numeric:true})).forEach(row=>table.appendChild(row))));"""
    page = f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Qhapaq · Universe</title><style>{_css()}</style><main><header class="top"><div><div class="brand">Qhapaq Finance · Research Dashboard</div><h1>Universe</h1></div><div class="label">Research as-of {_e(artifact["research_as_of"])}<br>{len(artifact["companies"])} companies · {evidence_count} evidence-backed · {fixture_count} fixtures</div></header><section><div class="toolbar"><input id="search" placeholder="Filter ticker, status, or data quality"></div><table id="universe"><tr><th>Ticker</th><th>Price</th><th>Base value</th><th>Base MOS</th><th>ROIC</th><th>WACC</th><th>ROIC − WACC</th><th>FCFF yield</th><th>Reverse DCF</th><th>FCFF rate</th><th>TV share</th><th>Status</th><th>Data quality</th></tr>{rows}</table></section></main><script type="application/json" id="qhapaq-data">{payload}</script><script>{controls}</script></html>"""
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(page, encoding="utf-8")
    return destination
