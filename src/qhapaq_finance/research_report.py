"""Deterministic, self-contained HTML rendering for company research."""
# ruff: noqa: E501

import html
import json
import platform
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

from .data import file_sha256
from .research import Fact, Metric, ResearchRecord, SourceDocument, load_research_record


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _metric(metric_value: float, unit: str | None) -> str:
    if unit == "percent":
        return f"{metric_value * 100:.1f}%"
    if unit == "USD million":
        return f"US$ {metric_value:,.0f} M"
    return f"{metric_value:,.0f} {_e(unit or '')}".strip()


def _quantitative_facts(record: ResearchRecord) -> str:
    facts = [fact for fact in record.facts if fact.text is None]
    cards = "".join(_quantitative_fact_card(fact) for fact in facts)
    return (
        '<div class="fact-grid" aria-label="Hechos cuantitativos validados">'
        + cards
        + "</div>"
        + '<p class="caption">Valores observados con su unidad y periodo declarados. '
        "N/A identifica información ausente o no validada; no equivale a cero.</p>"
    )


def _quantitative_fact_card(fact: Fact) -> str:
    if fact.value is None:
        value = "N/A"
        attribute = f'data-unavailable="{_e(fact.id)}"'
    else:
        value = _metric(fact.value, fact.unit)
        attribute = f'data-fact-id="{_e(fact.id)}" data-value="{fact.value}"'
    return (
        f'<article class="quant-fact" {attribute}><span>{_e(fact.label)}</span>'
        f"<strong>{value}</strong><small>{_e(fact.period)}</small></article>"
    )


def build_research_html(record: ResearchRecord) -> str:
    """Return identical HTML bytes for identical validated inputs."""
    nav = [
        ("resumen", "Vista ejecutiva"),
        ("negocio", "Negocio"),
        ("finanzas", "Evidencia financiera"),
        ("relativo", "Contexto relativo"),
        ("tesis", "Tesis y contraste"),
        ("valoracion", "Valoración"),
        ("evidencia", "Registro de evidencia"),
    ]
    metric_cards = "".join(_metric_card(item) for item in record.metrics)
    interpretations = "".join(_interpretation_card(item) for item in record.interpretations)
    risks = "".join(_risk_card(item) for item in record.risks)
    fact_rows = "".join(_fact_row(fact) for fact in record.facts)
    source_rows = "".join(_source_row(source) for source in record.sources)
    navigation = "".join(f'<a href="#{anchor}">{label}</a>' for anchor, label in nav)
    business = "".join(
        f'<article class="panel"><p>{_e(text)}</p></article>' for text in record.business
    )
    invalidation = "".join(f"<li>{_e(item)}</li>" for item in record.invalidation)
    issuer = record.issuer
    coverage = "; ".join(source.reporting_period for source in record.sources)
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Qhapaq Finance · {_e(issuer["ticker"])}</title><style>
{_styles()}
</style></head><body><header><div>
<p class="brand">Qhapaq Finance · investigación verificable</p>
<h1>{_e(issuer["ticker"])}</h1>
<p>{_e(issuer["name"])} · {_e(issuer["exchange"])} · CIK {_e(issuer["cik"])}</p>
</div><p class="badge">Solo investigación · corte {record.as_of}</p></header>
<nav>{navigation}</nav><main>
<section id="resumen"><p class="eyebrow">Vista ejecutiva</p>
<h2>Resumen de investigación fundamentada</h2>
<p class="lead">{_e(record.summary)}</p><div class="warning"><b>Cobertura:</b>
{_e(coverage)}. Caso retrospectivamente seleccionado. No representa una tenencia,
asignación ni recomendación. La valoración queda incompleta.</div></section>
<section id="negocio"><p class="eyebrow">Negocio y cadena de valor</p>
<h2>Modelo de negocio y creación de valor</h2>
<div class="grid">{business}</div></section>
<section id="finanzas"><p class="eyebrow">Evidencia financiera GAAP</p>
<h2>Hechos y métricas validados</h2>
<div class="metrics">{metric_cards}</div>
<div class="panel" style="margin-top:18px">{_quantitative_facts(record)}</div>
<p>Las métricas derivadas se calculan únicamente desde los hechos citados y conservan sus
unidades y periodos. No se mezclan cifras incompatibles para crear comparaciones implícitas.</p></section>
{_relative_context_section(record)}
<section id="tesis"><p class="eyebrow">Tesis, contratesis y escenarios</p>
<h2>Argumentos, riesgos y condiciones de revisión</h2>
<div class="grid">{interpretations}</div>
<h3>Riesgos y condiciones de revisión</h3>{risks}
<h3>Invalidación observable</h3><ol>{invalidation}</ol>
<p><b>Escenario cualitativo:</b> {_e(record.assumptions[0]["text"])}</p></section>
<section id="valoracion"><p class="eyebrow">Cobertura de valoración</p>
<h2>Incompleta por diseño</h2>
<div class="warning">{_e(record.valuation["gap"])}</div></section>
<section id="evidencia"><p class="eyebrow">Drill-down de evidencia</p>
<h2>Hechos y documentos congelados</h2><details open>
<summary>Hechos observados y localizadores</summary>{_facts_table(fact_rows)}</details>
<details><summary>Registro de fuentes primarias</summary>
{_sources_table(source_rows)}</details>
<p>Los PDF completos permanecen en el paquete local ignorado por Git. Este HTML contiene
resúmenes originales y enlaces externos; el hash acredita identidad de bytes, no autenticidad
absoluta ni ausencia de revisiones posteriores.</p></section></main>
<footer><b>Research only — not investment advice.</b> Sin mandato de inversión, moneda de
referencia, horizonte, liquidez, tolerancia al riesgo, benchmark ni datos de cartera.</footer>
</body></html>"""


def _relative_context_section(record: ResearchRecord) -> str:
    context = record.relative_context
    if not context:
        return ""

    def fmt(item: object, key: str = "return") -> str:
        return (
            "N/A"
            if not isinstance(item, dict) or item.get("status") != "ok"
            else f"{float(item[key]):+.1%}"
        )

    def judgment_class(item: object) -> str:
        if not isinstance(item, dict) or item.get("status") != "ok":
            return "is-unavailable"
        return "is-positive" if float(item["value"]) >= 0 else "is-negative"

    def fmt_range(item: object) -> str:
        if not isinstance(item, dict) or item.get("status") != "ok":
            return "N/D"
        return f"{float(item['minimum']):+.1%} a {float(item['maximum']):+.1%}"

    summaries = []
    cards = []
    rows = []
    for item in context["results"]:
        individual = context.get("series_results", {}).get(item["window"], {})
        window = _e(item["window"])
        eligible = item["peer_median"].get("eligible_peer_count", 0)
        peer_range = fmt_range(item["peer_range"])
        summaries.append(
            f'<article class="relative-summary" data-window="{window}"><h3>{window}</h3>'
            f'<div><span>QCOM</span><strong data-metric="qcom">{fmt(item["subject"])}</strong></div>'
            f'<div class="{judgment_class(item["excess_vs_peer_median"])}"><span>Exceso vs pares</span><strong data-metric="excess-peers">'
            f"{fmt(item['excess_vs_peer_median'], 'value')}</strong></div>"
            f'<div class="{judgment_class(item["excess_vs_benchmark"])}"><span>Exceso vs SOXX</span><strong data-metric="excess-soxx">'
            f"{fmt(item['excess_vs_benchmark'], 'value')}</strong></div>"
            f'<small class="eligibility-meta" data-metric="eligible">{eligible} de 3 pares elegibles</small></article>'
        )
        card_metrics = (
            ("QCOM", "qcom", "", fmt(item["subject"])),
            ("Mediana de pares", "peer-median", "", fmt(item["peer_median"])),
            ("SOXX", "soxx", "", fmt(item["benchmark"])),
            (
                "Exceso vs pares",
                "excess-peers",
                judgment_class(item["excess_vs_peer_median"]),
                fmt(item["excess_vs_peer_median"], "value"),
            ),
            (
                "Exceso vs SOXX",
                "excess-soxx",
                judgment_class(item["excess_vs_benchmark"]),
                fmt(item["excess_vs_benchmark"], "value"),
            ),
            ("Pares elegibles", "eligible", "is-secondary", f"{eligible} de 3"),
            ("Rango de pares", "peer-range", "", peer_range),
        )
        card_values = "".join(
            (f'<div class="{semantic_class}">' if semantic_class else "<div>")
            + f"<span>{label}</span>"
            f'<strong data-metric="{metric}">{value}</strong></div>'
            for label, metric, semantic_class, value in card_metrics
        )
        cards.append(
            f'<article class="relative-card" data-window="{window}"><h3>{window}</h3>'
            f'<div class="relative-card-values">{card_values}</div></article>'
        )
        rows.append(
            f'<tr data-window="{window}">'
            + "".join(
                (
                    f'<th headers="relative-window">{window}</th>',
                    f'<td headers="relative-qcom">{fmt(item["subject"])}</td>',
                    f'<td headers="relative-peer-median">{fmt(item["peer_median"])}</td>',
                    f'<td class="is-secondary" headers="relative-eligible">{eligible} / 3</td>',
                    f'<td headers="relative-peer-range">{peer_range}</td>',
                    f'<td headers="relative-nxpi">{fmt(individual.get("NXPI"))}</td>',
                    f'<td headers="relative-avgo">{fmt(individual.get("AVGO"))}</td>',
                    f'<td class="is-unavailable" headers="relative-mediatek">{fmt(individual.get("MEDIATEK"))}</td>',
                    f'<td headers="relative-soxx">{fmt(item["benchmark"])}</td>',
                    f'<td class="{judgment_class(item["excess_vs_peer_median"])}" headers="relative-excess-peers">'
                    f"{fmt(item['excess_vs_peer_median'], 'value')}</td>",
                    f'<td class="{judgment_class(item["excess_vs_benchmark"])}" headers="relative-excess-soxx">'
                    f"{fmt(item['excess_vs_benchmark'], 'value')}</td>",
                )
            )
            + "</tr>"
        )
    source_details = "".join(
        f"<li><code>{_e(entity)}</code>: fuente {_e(series.get('source_id') or 'sin fuente')}; "
        f"base {_e(series['price_basis'])}</li>"
        for entity, series in context["series"].items()
    )
    return (
        '<section id="relativo" class="relative-context"><p class="eyebrow">Contexto relativo</p>'
        "<h2>QCOM frente a pares y SOXX</h2><p>Retornos acumulados con series fechadas. "
        "SOXX permanece separado del universo de pares.</p>"
        '<div class="relative-summary-grid" aria-label="Resumen de desempeño relativo">'
        + "".join(summaries)
        + '</div><h3 class="relative-level-heading">Lectura por ventana</h3>'
        '<div class="relative-card-grid" aria-label="Comparación por ventana">'
        + "".join(cards)
        + '</div><p class="dispersion-note"><b>Lectura cautelosa:</b> la mediana usa solo '
        "2 de 3 pares elegibles. El rango visible muestra una dispersión alta entre NXPI y AVGO; "
        "revise ambos extremos antes de interpretar la mediana.</p>"
        '<details class="relative-detail"><summary>Detalle de pares y evidencia</summary>'
        '<p class="mediatek-status" data-status="unavailable"><b>MediaTek: no disponible.</b> '
        "No se adquirió una serie congelada comparable en USD; no se usa proxy ni sustituto.</p>"
        '<div class="table-scroll" role="region" aria-label="Detalle tabular desplazable" '
        'tabindex="0"><table><thead><tr>'
        '<th id="relative-window">Ventana</th><th id="relative-qcom">QCOM</th>'
        '<th id="relative-peer-median">Mediana de pares</th>'
        '<th id="relative-eligible">Elegibles</th><th id="relative-peer-range">Rango de pares</th>'
        '<th id="relative-nxpi">NXPI</th><th id="relative-avgo">AVGO</th>'
        '<th id="relative-mediatek">MediaTek</th><th id="relative-soxx">SOXX</th>'
        '<th id="relative-excess-peers">Exceso vs pares</th>'
        '<th id="relative-excess-soxx">Exceso vs SOXX</th></tr></thead><tbody>'
        + "".join(rows)
        + '</tbody></table></div><p><a href="#evidencia">Evidencia congelada verificada</a></p>'
        '<details class="provenance-detail"><summary>Identificadores y procedencia</summary><ul>'
        + source_details
        + f"</ul><p>Registro SHA-256: <code>{_e(context['provenance']['record'])}</code>. "
        f"Corte analítico: {_e(record.as_of)}.</p></details></details></section>"
    )


def _metric_card(metric: Metric) -> str:
    return (
        f'<article class="metric"><span>{_e(metric.label)}</span>'
        f"<strong>{_metric(metric.value, metric.unit)}</strong>"
        f"<small>{_e(metric.formula)}</small></article>"
    )


def _interpretation_card(item: dict[str, Any]) -> str:
    heading = "Tesis" if item["kind"] == "thesis" else "Contratesis"
    supports = ", ".join(f'<a href="#{_e(ref)}">{_e(ref)}</a>' for ref in item["supports"])
    contradicts = ", ".join(f'<a href="#{_e(ref)}">{_e(ref)}</a>' for ref in item["contradicts"])
    return (
        f'<article class="argument"><p class="eyebrow">{_e(item["kind"])}</p>'
        f"<h3>{heading}</h3><p>{_e(item['text'])}</p>"
        f'<p class="links">Apoya: {supports}<br>Contradice: {contradicts}</p></article>'
    )


def _risk_card(item: dict[str, Any]) -> str:
    evidence = ", ".join(f'<a href="#{_e(ref)}">{_e(ref)}</a>' for ref in item["evidence"])
    return (
        f"<details><summary>{_e(item['title'])}</summary>"
        f"<p>{_e(item['mechanism'])}</p>"
        f"<p><b>Condición de revisión:</b> {_e(item['review'])}</p>"
        f'<p class="links">Evidencia: {evidence}</p></details>'
    )


def _fact_row(fact: Fact) -> str:
    if fact.value is not None:
        value = f"{fact.value:,.0f} {_e(fact.unit)}"
    elif fact.text:
        value = _e(fact.text)
    else:
        value = "N/A — no disponible o no validado"
    return (
        f'<tr id="{_e(fact.id)}"><td><code>{_e(fact.id)}</code><br>{_e(fact.label)}</td>'
        f"<td>{value}</td><td>{_e(fact.period)}</td>"
        f'<td><a href="#{_e(fact.source_id)}">{_e(fact.source_id)}</a><br>'
        f"{_e(fact.locator)}</td></tr>"
    )


def _source_row(source: SourceDocument) -> str:
    return (
        f'<tr id="{_e(source.id)}"><td><code>{_e(source.id)}</code><br>'
        f"{_e(source.title)}</td><td>{_e(source.publisher)}<br>"
        f"Publicado: {source.publication_date}<br>{_e(source.reporting_period)}<br>"
        f"Recuperado: {source.retrieval_timestamp.isoformat()}</td>"
        f"<td>{source.byte_count:,} bytes<br><code>{_e(source.sha256)}</code><br>"
        f"{_e(source.media_type)}</td>"
        f'<td><a href="{_e(source.canonical_url)}" rel="noreferrer">Fuente externa</a><br>'
        f'<a href="{_e(source.discovery_url)}" rel="noreferrer">Descubrimiento</a><br>'
        f'<a href="{_e(source.download_url)}" rel="noreferrer">Descarga</a><br>'
        f"{_e(source.availability_evidence)}<br>"
        f"<code>{_e(source.repository_path)}</code></td></tr>"
    )


def _facts_table(rows: str) -> str:
    return (
        "<table><thead><tr><th>Hecho</th><th>Valor</th><th>Periodo</th>"
        f"<th>Fuente / localizador</th></tr></thead><tbody>{rows}</tbody></table>"
    )


def _sources_table(rows: str) -> str:
    return (
        "<table><thead><tr><th>Documento</th><th>Publicación</th>"
        f"<th>Identidad local</th><th>Acceso</th></tr></thead><tbody>{rows}</tbody></table>"
    )


def _styles() -> str:
    return """
:root { --bg:#09111d; --panel:#111d2d; --line:#263a52; --text:#edf5fc;
  --muted:#a9bad0; --cyan:#30c9e8; --amber:#f0b65a;
  --positive:#69d59a; --negative:#f08f86; }
* { box-sizing:border-box; } html { scroll-behavior:smooth; }
body { margin:0; background:var(--bg); color:var(--text);
  font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif; }
a { color:var(--cyan); } header,main,footer { max-width:1160px; margin:auto; padding:28px; }
header { display:grid; grid-template-columns:1fr auto; gap:24px; align-items:end;
  border-bottom:1px solid var(--line); }
.brand,.eyebrow { color:var(--cyan); text-transform:uppercase; letter-spacing:.12em;
  font-size:.75rem; font-weight:700; }
h1 { font-size:clamp(2.2rem,7vw,5rem); line-height:.95; margin:.25rem 0; }
h2 { font-size:1.65rem; margin-top:0; }
.badge { border:1px solid var(--amber); color:var(--amber); padding:8px 12px;
  border-radius:999px; }
nav { position:sticky; top:0; z-index:2; background:#09111df2;
  border-bottom:1px solid var(--line); display:flex; gap:18px; overflow:auto;
  padding:12px calc((100% - 1104px)/2); }
nav a { white-space:nowrap; text-decoration:none; color:var(--muted); }
section { padding:42px 0; border-bottom:1px solid var(--line); }
.lead { font-size:1.25rem; max-width:850px; }
.grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:18px; }
.metrics { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }
.fact-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }
.relative-summary-grid,.relative-card-grid { display:grid;
  grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }
.relative-summary,.relative-card { background:var(--panel); border:1px solid var(--line);
  border-radius:12px; padding:16px; min-width:0; }
.relative-summary h3,.relative-card h3 { margin:0 0 10px; }
.relative-summary div,.relative-card-values div { display:flex; justify-content:space-between;
  align-items:baseline; gap:12px; padding:5px 0; border-bottom:1px solid var(--line); }
.relative-summary span,.relative-card span { color:var(--muted); }
.relative-summary strong,.relative-card strong { text-align:right; }
.relative-summary small { display:block; margin-top:10px; }
.relative-level-heading { margin-top:26px; }
.relative-context > .eyebrow { color:var(--muted); }
.relative-context .is-positive strong,.relative-context td.is-positive { color:var(--positive); }
.relative-context .is-negative strong,.relative-context td.is-negative { color:var(--negative); }
.relative-context .is-secondary,.relative-context .is-unavailable,
.relative-context .provenance-detail,.relative-context .provenance-detail code { color:var(--muted); }
.eligibility-meta { color:var(--muted); }
.dispersion-note { border:1px solid var(--line); border-left-width:3px; border-radius:8px;
  padding:12px 16px; background:var(--panel); }
.relative-detail { margin-top:18px; }
.mediatek-status { max-width:760px; }
.table-scroll { max-width:100%; overflow-x:auto; }
.quant-fact { border:1px solid var(--line); border-radius:10px; padding:14px; }
.quant-fact strong { display:block; color:var(--cyan); font-size:1.25rem; }
.metric,.argument,details,.panel { background:var(--panel); border:1px solid var(--line);
  border-radius:12px; padding:18px; }
.metric strong { display:block; color:var(--cyan); font-size:1.8rem; }
small,.caption,.links { color:var(--muted); } svg { width:100%; height:auto; }
details { margin:10px 0; } summary { cursor:pointer; font-weight:700; }
table { width:100%; border-collapse:collapse; font-size:.88rem; }
th,td { text-align:left; vertical-align:top; padding:12px;
  border-bottom:1px solid var(--line); }
code { font-size:.78rem; overflow-wrap:anywhere; color:#c5d5e8; }
.warning { border-left:4px solid var(--amber); padding:14px 18px; background:#261e12; }
footer { color:var(--muted); }
@media(max-width:760px) { header,.grid,.metrics,.fact-grid,.relative-summary-grid,
  .relative-card-grid { grid-template-columns:1fr; }
  nav { padding:12px 18px; } main,header,footer { padding:20px; }
  .relative-summary,.relative-card { width:100%; }
  .relative-summary div,.relative-card-values div { gap:10px; }
  .relative-summary span,.relative-card span { min-width:0; }
  .relative-summary strong,.relative-card strong { flex:0 0 auto; }
  table { display:block; overflow-x:auto; } }
@media print { body { background:#fff; color:#111; } nav { display:none; }
  .metric,.argument,details,.panel { background:#fff; border-color:#bbb; }
  a { color:#075985; } }
""".strip()


def _git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=root, check=True, capture_output=True, text=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def render_research_report(
    *,
    record_path: Path,
    manifest_path: Path,
    output_path: Path,
    as_of: date,
    repository_root: Path = Path("."),
    result_manifest_path: Path | None = None,
) -> Path:
    """Validate local inputs and atomically render one offline HTML report."""
    root = repository_root.resolve()
    output = output_path.resolve()
    protected = {record_path.resolve(), manifest_path.resolve()}
    if output in protected or output.suffix.lower() != ".html":
        raise ValueError("output_path must be a distinct .html file")
    record = load_research_record(
        record_path=record_path, manifest_path=manifest_path, repository_root=root, as_of=as_of
    )
    payload = build_research_html(record).encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_bytes(payload)
    if output.exists():
        shutil.copy2(output, output.with_suffix(".previous.html"))
    temporary.replace(output)
    if b"javascript:" in payload.lower() or b"data:text/html" in payload.lower():
        raise ValueError("rendered HTML contains an unsafe URL")
    result_path = result_manifest_path or output.with_suffix(".manifest.json")
    if result_path.resolve() in protected or result_path.resolve() == output:
        raise ValueError("result manifest cannot overwrite an input or output")
    implementation = [
        root / "src/qhapaq_finance/research.py",
        root / "src/qhapaq_finance/research_report.py",
        root / "src/qhapaq_finance/cli.py",
    ]
    result = {
        "schema_version": "1.0",
        "issuer": record.issuer,
        "as_of": as_of.isoformat(),
        "inputs": record.input_hashes,
        "sources": {s.id: s.sha256 for s in record.sources},
        "code": {
            "head": _git(root, "rev-parse", "HEAD"),
            "dirty_status": _git(root, "status", "--short", "--untracked-files=all"),
            "implementation_sha256": {
                str(p.relative_to(root)): file_sha256(p) for p in implementation
            },
            "uv_lock_sha256": file_sha256(root / "uv.lock"),
        },
        "parameters": {"format": "self-contained-html", "language": "es"},
        "runtime": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": sys.platform,
            "timestamp_timezone": "UTC",
            "renderer_schema": "research-html-v1",
        },
        "output": {
            "name": output.name,
            "sha256": file_sha256(output),
            "byte_count": output.stat().st_size,
        },
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return output
