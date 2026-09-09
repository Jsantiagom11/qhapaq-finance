"""Offline, WebKit-first visual QA for the standalone dashboard.

Playwright is imported only inside ``run_visual_audit`` so it is never a normal
runtime dependency of the dashboard or its CLI.
"""

# ruff: noqa: E501
from __future__ import annotations

import argparse
import base64
import contextlib
import html
import json
import threading
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .dashboard import build_company_artifact, render_company_dashboard

PRIMARY_VIEWPORTS = (("portrait", 1024, 1366), ("landscape", 1366, 1024))
# Crosses the dashboard's 850px responsive breakpoint without expanding the matrix.
NARROW_VIEWPORT = ("narrow", 768, 1024)
PRIMARY_STATES = (
    ("simple", "paper"),
    ("simple", "night"),
    ("research", "paper"),
    ("research", "night"),
)
NARROW_STATES = (("simple", "paper"), ("research", "night"))
TOUCH_MINIMUM, OVERFLOW_TOLERANCE = 44, 1


@dataclass(frozen=True)
class SnapshotSpec:
    name: str
    orientation: str
    viewport_width: int
    viewport_height: int
    view_mode: str
    theme: str
    primary: bool


def snapshot_name(orientation: str, view_mode: str, theme: str) -> str:
    return f"ipad-pro-13-{orientation}-{view_mode}-{theme}.png"


def audit_matrix() -> tuple[SnapshotSpec, ...]:
    specs: list[SnapshotSpec] = []
    for orientation, width, height in PRIMARY_VIEWPORTS:
        for view, theme in PRIMARY_STATES:
            specs.append(
                SnapshotSpec(
                    snapshot_name(orientation, view, theme),
                    orientation,
                    width,
                    height,
                    view,
                    theme,
                    True,
                )
            )
    orientation, width, height = NARROW_VIEWPORT
    for view, theme in NARROW_STATES:
        specs.append(
            SnapshotSpec(
                snapshot_name(orientation, view, theme),
                orientation,
                width,
                height,
                view,
                theme,
                False,
            )
        )
    return tuple(specs)


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass


@contextlib.contextmanager
def localhost_server(directory: Path) -> Iterator[str]:
    """Temporary localhost-only server, avoiding file:// WebKit storage quirks."""

    def handler(*args: Any, **kwargs: Any) -> _QuietHandler:
        return _QuietHandler(*args, directory=str(directory), **kwargs)

    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        worker.join()
        server.server_close()


def _diagnostic_script() -> str:
    return f"""() => {{
      const visible=e=>{{const s=getComputedStyle(e),r=e.getBoundingClientRect();return s.display!=='none'&&s.visibility!=='hidden'&&r.width>0&&r.height>0}};
      const root=document.documentElement, failures=[], clipping=[];
      const overflow=Math.max(0,root.scrollWidth-root.clientWidth);
      if(overflow>{OVERFLOW_TOLERANCE}) failures.push(`page horizontal overflow: ${{overflow}}px`);
      const organisms=[['dashboard header','.dashboard-header'],['control groups','.toolbar'],['Simple hero','.simple-hero'],['decision metrics','.decision-metrics'],['analytical metrics','.research-template .metric-grid'],['argument grid','.argument-grid'],['buy-zone visual','.buy-zone'],['research panels','.research-panel'],['evidence/provenance','.research-template section:last-child'],['tables','table']];
      const required=[['dashboard header','.dashboard-header'],['control groups','.toolbar'],...(document.querySelector('main').dataset.view==='simple'?[['Simple hero','.simple-hero'],['decision metrics','.decision-metrics'],['argument grid','.argument-grid']]:[['decision metrics','.decision-metrics'],['analytical metrics','.research-template .metric-grid'],['buy-zone visual','.buy-zone'],['research panels','.research-panel'],['evidence/provenance','.research-template section:last-child'],['tables','table']])];
      for(const [name,selector] of required) if(![...document.querySelectorAll(selector)].some(visible)) failures.push(`required organism missing: ${{name}}`);
      for(const [name,selector] of organisms) for(const e of [...document.querySelectorAll(selector)].filter(visible)){{const r=e.getBoundingClientRect();if(!e.closest('.provenance')&&r.width>root.clientWidth+{OVERFLOW_TOLERANCE}) failures.push(`${{name}} exceeds viewport`)}}
      if(root.clientWidth<=850){{const grid=document.querySelector('.argument-grid');if(grid&&visible(grid)&&getComputedStyle(grid).gridTemplateColumns.trim().split(/\\s+/).length!==1)failures.push('narrow argument cards did not reduce to one column');const header=document.querySelector('.dashboard-header');if(header&&visible(header)&&getComputedStyle(header).display!=='block')failures.push('narrow header did not stack metadata');}}
      const touch=[...document.querySelectorAll('button,summary,input,select,textarea')].filter(visible).flatMap(e=>{{const r=e.getBoundingClientRect();return r.width<{TOUCH_MINIMUM}||r.height<{TOUCH_MINIMUM}?[{{label:(e.textContent||e.placeholder||e.tagName).trim().slice(0,80),width:Math.round(r.width),height:Math.round(r.height)}}]:[]}});
      for(const p of [...document.querySelectorAll('.metric-card,.argument-card,.research-panel,.buy-zone,.dashboard-header,.toolbar')].filter(visible)){{const s=getComputedStyle(p);if(!['hidden','clip'].includes(s.overflowX)&&!['hidden','clip'].includes(s.overflowY))continue;const r=p.getBoundingClientRect();for(const c of [...p.children].filter(visible)){{const q=c.getBoundingClientRect();if(q.right>r.right+1||q.bottom>r.bottom+1)clipping.push(p.className||p.tagName)}}}}
      return {{horizontal_overflow:overflow,layout_failures:[...new Set(failures)],touch_target_warnings:touch,clipping_warnings:[...new Set(clipping)]}};
    }}"""


def _report_html(ticker: str, records: list[dict[str, Any]], image_sources: dict[str, str]) -> str:
    cards = "".join(
        f'''<article class="card {"fail" if r["layout_failures"] else "pass"}"><h3>{html.escape(r["name"].removesuffix(".png"))}</h3><p>{r["viewport_width"]} × {r["viewport_height"]} · {html.escape(r["view_mode"])} · {html.escape(r["theme"])}</p><img loading="lazy" src="{html.escape(image_sources.get(r["screenshot_path"], r["screenshot_path"]))}" alt="{html.escape(r["name"])}"><p><b>{"FAIL" if r["layout_failures"] else "PASS"}</b> · horizontal overflow: {r["horizontal_overflow"]}px</p><details><summary>Diagnostics ({len(r["touch_target_warnings"])} touch warnings)</summary><pre>{html.escape(json.dumps({k: r[k] for k in ("layout_failures", "touch_target_warnings", "clipping_warnings")}, indent=2))}</pre></details></article>'''
        for r in records
    )
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><title>{html.escape(ticker)} Visual QA</title><style>body{{margin:24px;background:#f4f1eb;color:#1c2730;font:15px/1.45 Arial,sans-serif}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:18px}}.card{{background:#fffdf8;border:1px solid #d6d1c7;padding:14px}}.pass{{border-top:4px solid #32634d}}.fail{{border-top:4px solid #8b4942}}h1,h3{{font-family:Georgia,serif}}img{{width:100%;height:auto;border:1px solid #d6d1c7}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}summary{{cursor:pointer}}</style><h1>{html.escape(ticker)} VISUAL QA</h1><p>WebKit-first offline review. iPad Pro 13 primary screenshots precede deliberately narrow responsive stress cases.</p><div class="grid">{cards}</div></html>"""


def write_report(destination: Path, ticker: str, records: list[dict[str, Any]]) -> Path:
    path = destination / "report.html"
    image_sources = {
        record["screenshot_path"]: "data:image/png;base64,"
        + base64.b64encode((destination / record["screenshot_path"]).read_bytes()).decode("ascii")
        for record in records
        if (destination / record["screenshot_path"]).is_file()
    }
    path.write_text(_report_html(ticker, records, image_sources), encoding="utf-8")
    return path


def write_manifest(
    destination: Path, metadata: dict[str, Any], records: list[dict[str, Any]]
) -> Path:
    path = destination / "manifest.json"
    path.write_text(
        json.dumps({**metadata, "snapshots": records}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def run_visual_audit(ticker: str, output_root: Path = Path("output/visual-audit")) -> Path:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Visual QA requires the optional extra. Run: uv sync --extra visual"
        ) from exc
    ticker, run_id = ticker.upper(), datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = output_root / ticker.lower() / run_id
    destination.mkdir(parents=True, exist_ok=False)
    dashboard = render_company_dashboard(
        build_company_artifact(ticker), destination / f"{ticker.lower()}-dashboard.html"
    )
    records: list[dict[str, Any]] = []
    with localhost_server(destination) as url, sync_playwright() as pw:
        browser = pw.webkit.launch(headless=True)
        try:
            for spec in audit_matrix():
                context = browser.new_context(
                    viewport={"width": spec.viewport_width, "height": spec.viewport_height},
                    is_mobile=True,
                    has_touch=True,
                    device_scale_factor=1,
                )
                page = context.new_page()
                page.goto(f"{url}/{dashboard.name}", wait_until="networkidle")
                page.add_style_tag(
                    content="*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}"
                )
                page.locator(f"#{spec.theme}-theme").click()
                page.locator(f"#{spec.view_mode}").click()
                page.wait_for_function(
                    "([view,theme])=>document.querySelector('main').dataset.view===view&&document.documentElement.dataset.theme===theme",
                    arg=[spec.view_mode, spec.theme],
                )
                diagnostics = page.evaluate(_diagnostic_script())
                page.screenshot(path=str(destination / spec.name), full_page=True)
                records.append({**asdict(spec), "screenshot_path": spec.name, **diagnostics})
                context.close()
        finally:
            version = browser.version
            browser.close()
    metadata = {
        "ticker": ticker,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dashboard_artifact": dashboard.name,
        "browser_engine": "webkit",
        "browser_version": version,
        "device_profile": {
            "name": "iPad Pro 13 style",
            "touch": True,
            "mobile_semantics": True,
            "device_scale_factor": 1,
            "note": "CSS viewport; WebKit cannot emulate every iPad hardware characteristic.",
        },
    }
    write_manifest(destination, metadata, records)
    write_report(destination, ticker, records)
    if any(r["layout_failures"] for r in records):
        raise RuntimeError(
            f"Visual audit found structural failures; inspect {destination / 'report.html'}"
        )
    return destination


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run offline WebKit visual QA for a Qhapaq dashboard"
    )
    parser.add_argument("ticker", choices=("QCOM", "VRTX", "CSCO"), type=str.upper)
    parser.add_argument("--device", default="ipad-pro-13", choices=("ipad-pro-13",))
    parser.add_argument("--output-root", type=Path, default=Path("output/visual-audit"))
    args = parser.parse_args(argv)
    try:
        output = run_visual_audit(args.ticker, args.output_root)
    except RuntimeError as exc:
        parser.exit(1, f"visual-audit error: {exc}\n")
    print(f"visual_audit={output}")


if __name__ == "__main__":
    main()
