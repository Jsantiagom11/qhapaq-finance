import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from copy import deepcopy
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from qhapaq_finance import cli
from qhapaq_finance.data import file_sha256
from qhapaq_finance.research import (
    ResearchRecordError,
    _metric_value,
    _validate_relative_result_provenance,
    load_research_record,
)
from qhapaq_finance.research_report import (
    _quantitative_facts,
    build_research_html,
    render_research_report,
)

ROOT = Path(__file__).parents[1]
RECORD = ROOT / "data/research/qcom/research.json"
MANIFEST = ROOT / "data/research/qcom/manifest.json"


def test_metric_subtraction_allows_zero_subtrahend() -> None:
    assert _metric_value("f-current - f-prior", [10.0, 0.0]) == 10.0


@pytest.mark.parametrize("formula", ["f-current / f-prior", "(f-current / f-prior) - 1"])
def test_metric_division_rejects_zero_denominator(formula: str) -> None:
    with pytest.raises(ResearchRecordError, match="^metric denominator cannot be zero$"):
        _metric_value(formula, [10.0, 0.0])


def _load() -> object:
    return load_research_record(
        record_path=RECORD,
        manifest_path=MANIFEST,
        repository_root=ROOT,
        as_of=date(2026, 9, 1),
    )


def _copy_inputs(tmp_path: Path) -> tuple[Path, Path]:
    research = tmp_path / "data/research/qcom"
    raw = tmp_path / "data/raw/qcom"
    research.mkdir(parents=True)
    raw.mkdir(parents=True)
    shutil.copy2(RECORD, research / "research.json")
    shutil.copy2(MANIFEST, research / "manifest.json")
    shutil.copy2(ROOT / "data/research/qcom/universe.json", research / "universe.json")
    for source in json.loads(MANIFEST.read_text())["sources"]:
        destination = tmp_path / source["local_path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / source["local_path"], destination)
    relative_source = ROOT / "data/research/qcom/relative-context.json"
    relative_destination = research / "relative-context.json"
    shutil.copy2(relative_source, relative_destination)
    for series in json.loads(relative_source.read_text())["series"]:
        if series["price_basis"] != "unavailable":
            destination = tmp_path / series["local_path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / series["local_path"], destination)
    return research / "research.json", research / "manifest.json"


def _write(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_real_typed_record_and_financial_calculations() -> None:
    record = _load()
    values = {metric.id: metric.value for metric in record.metrics}
    assert values["m-revenue-growth-2025"] == pytest.approx(44284 / 38962 - 1)
    assert values["m-op-margin-2025"] == pytest.approx(12355 / 44284)
    assert values["m-fcf-2025"] == 12820
    assert record.issuer["ticker"] == "QCOM"
    assert all(source.availability_evidence for source in record.sources)


@pytest.mark.parametrize(
    "field",
    ["download_url", "discovery_url", "media_type", "availability_evidence"],
)
def test_missing_source_provenance_fails(tmp_path: Path, field: str) -> None:
    record, manifest = _copy_inputs(tmp_path)
    payload = json.loads(manifest.read_text())
    payload["sources"][0].pop(field)
    _write(manifest, payload)
    with pytest.raises(ResearchRecordError, match=field):
        load_research_record(
            record_path=record,
            manifest_path=manifest,
            repository_root=tmp_path,
            as_of=date(2026, 9, 1),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("retrieved_at", "2026-09-02T15:02:17"),
        ("download_url", "http://example.com/document.pdf"),
        ("discovery_url", "not-a-url"),
        ("media_type", "application pdf"),
        ("availability_evidence", "   "),
    ],
)
def test_malformed_provenance_fails(tmp_path: Path, field: str, value: str) -> None:
    record, manifest = _copy_inputs(tmp_path)
    payload = json.loads(manifest.read_text())
    if field == "retrieved_at":
        payload[field] = value
    else:
        payload["sources"][0][field] = value
    _write(manifest, payload)
    with pytest.raises(ResearchRecordError, match=field):
        load_research_record(
            record_path=record,
            manifest_path=manifest,
            repository_root=tmp_path,
            as_of=date(2026, 9, 1),
        )


def test_missing_retrieval_timestamp_fails(tmp_path: Path) -> None:
    record, manifest = _copy_inputs(tmp_path)
    payload = json.loads(manifest.read_text())
    payload.pop("retrieved_at")
    _write(manifest, payload)
    with pytest.raises(ResearchRecordError, match="retrieved_at"):
        load_research_record(
            record_path=record,
            manifest_path=manifest,
            repository_root=tmp_path,
            as_of=date(2026, 9, 1),
        )


def test_duplicate_json_keys_fail_closed(tmp_path: Path) -> None:
    record, manifest = _copy_inputs(tmp_path)
    content = record.read_text()
    record.write_text(content.replace('"status":', '"status":"duplicate",\n  "status":', 1))
    with pytest.raises(ResearchRecordError, match="duplicate key.*status"):
        load_research_record(
            record_path=record,
            manifest_path=manifest,
            repository_root=tmp_path,
            as_of=date(2026, 9, 1),
        )


def test_render_is_deterministic_and_contains_semantic_sections(tmp_path: Path) -> None:
    first = render_research_report(
        record_path=RECORD,
        manifest_path=MANIFEST,
        output_path=tmp_path / "first.html",
        as_of=date(2026, 9, 1),
        repository_root=ROOT,
    )
    second = render_research_report(
        record_path=RECORD,
        manifest_path=MANIFEST,
        output_path=tmp_path / "second.html",
        as_of=date(2026, 9, 1),
        repository_root=ROOT,
    )
    assert file_sha256(first) == file_sha256(second)
    content = first.read_text()
    for anchor in ("resumen", "negocio", "finanzas", "tesis", "valoracion", "evidencia"):
        assert f'id="{anchor}"' in content and f'href="#{anchor}"' in content
    assert "Research only — not investment advice" in content
    assert "44,284" in content and "90852abbb69e" in content
    assert "<script" not in content
    assert 'src="http' not in content.lower() and 'rel="stylesheet"' not in content.lower()


def test_result_manifest_covers_relative_inputs_and_runtime(tmp_path: Path) -> None:
    manifest_path = tmp_path / "result.json"
    render_research_report(
        record_path=RECORD,
        manifest_path=MANIFEST,
        output_path=tmp_path / "research.html",
        result_manifest_path=manifest_path,
        as_of=date(2026, 9, 1),
        repository_root=ROOT,
    )
    result = json.loads(manifest_path.read_text())
    assert result["inputs"]["relative_context"] == file_sha256(
        ROOT / "data/research/qcom/relative-context.json"
    )
    assert set(key for key in result["inputs"] if key.startswith("relative_series:")) == {
        "relative_series:AVGO",
        "relative_series:NXPI",
        "relative_series:QCOM",
        "relative_series:SOXX",
    }
    assert result["runtime"]["timestamp_timezone"] == "UTC"
    assert result["runtime"]["renderer_schema"] == "research-html-v1"


def _relative_article(content: str, css_class: str, window: str) -> str:
    match = re.search(
        rf'<article class="{css_class}" data-window="{window}">(.*?)</article>', content
    )
    assert match is not None
    return match.group(1)


def test_relative_summary_and_window_cards_render_correct_values() -> None:
    content = build_research_html(_load())
    expected = {
        "1Y": ("+5.8%", "-5.0%", "-99.1%", "+10.8%", "+104.9%", "-3.6% a +25.2%"),
        "3Y": ("+53.0%", "-122.5%", "-146.0%", "+175.5%", "+199.1%", "+11.8% a +339.3%"),
        "5Y": ("+26.1%", "-343.1%", "-209.3%", "+369.2%", "+235.4%", "+15.1% a +723.4%"),
    }
    for window, (qcom, excess_peers, excess_soxx, median, soxx, peer_range) in expected.items():
        summary = _relative_article(content, "relative-summary", window)
        assert f'data-metric="qcom">{qcom}' in summary
        assert f'data-metric="excess-peers">{excess_peers}' in summary
        assert f'data-metric="excess-soxx">{excess_soxx}' in summary
        assert 'data-metric="eligible">2 de 3 pares elegibles' in summary

        card = _relative_article(content, "relative-card", window)
        assert f'data-metric="qcom">{qcom}' in card
        assert f'data-metric="peer-median">{median}' in card
        assert f'data-metric="soxx">{soxx}' in card
        assert f'data-metric="excess-peers">{excess_peers}' in card
        assert f'data-metric="excess-soxx">{excess_soxx}' in card
        assert 'data-metric="eligible">2 de 3' in card
        assert f'data-metric="peer-range">{peer_range}' in card


def test_relative_detail_cells_align_with_entity_headers() -> None:
    content = build_research_html(_load())
    row_match = re.search(r'<tr data-window="1Y">(.*?)</tr>', content)
    assert row_match is not None
    cells = dict(
        re.findall(
            r'<(?:th|td)(?: class="[^"]+")? headers="([^"]+)">(.*?)</(?:th|td)>',
            row_match.group(1),
        )
    )
    assert cells == {
        "relative-window": "1Y",
        "relative-qcom": "+5.8%",
        "relative-peer-median": "+10.8%",
        "relative-eligible": "2 / 3",
        "relative-peer-range": "-3.6% a +25.2%",
        "relative-nxpi": "-3.6%",
        "relative-avgo": "+25.2%",
        "relative-mediatek": "N/A",
        "relative-soxx": "+104.9%",
        "relative-excess-peers": "-5.0%",
        "relative-excess-soxx": "-99.1%",
    }
    for header in cells:
        assert f'id="{header}"' in content


def test_relative_detail_uses_one_concise_mediatek_status_and_keeps_provenance_link() -> None:
    content = build_research_html(_load())
    assert content.count("MediaTek: no disponible.") == 1
    assert content.count("No se adquirió una serie congelada comparable en USD") == 1
    assert "No defensible frozen USD-comparable MediaTek return series" not in content
    assert content.count('headers="relative-mediatek">N/A') == 3
    assert '<a href="#evidencia">Evidencia congelada verificada</a>' in content
    assert 'class="provenance-detail"' in content
    assert "qcom-yahoo-chart-2026-09-02" in content
    assert "Registro SHA-256:" in content


def test_relative_primary_content_is_structurally_responsive() -> None:
    content = build_research_html(_load())
    assert 'class="relative-summary-grid"' in content
    assert 'class="relative-card-grid"' in content
    assert ".relative-card-grid { grid-template-columns:1fr; }" in content
    assert 'class="table-scroll" role="region"' in content
    assert ".table-scroll { max-width:100%; overflow-x:auto; }" in content


def test_relative_context_colors_only_directional_judgments() -> None:
    content = build_research_html(_load())
    for token in ("--positive", "--negative"):
        assert token in content
    for removed in ("--subject", "--peer", "--benchmark", "--warning", "--technical"):
        assert removed not in content
    assert 'class="relative-context"' in content
    assert 'class="is-negative"' in content
    assert 'class="eligibility-meta"' in content
    for removed in ("role-subject", "role-peer", "role-benchmark", "is-warning"):
        assert removed not in content


def test_canonical_relative_result_provenance_graph_validates() -> None:
    context = _load().relative_context
    assert context is not None
    _validate_relative_result_provenance(context)
    for result in context["results"]:
        assert result["peer_range"]["id"] == f"peer-range-{result['window']}"
        assert result["peer_range"]["inputs"] == result["peer_median"]["inputs"]


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("duplicate", "duplicate derived result ID"),
        ("dangling", "dangling input result ID"),
        ("aggregate", "invalid or cross-window input set"),
        ("circular", "circular derived-result dependency"),
        ("wrong-window", "invalid or cross-window input set"),
    ],
)
def test_invalid_relative_result_provenance_fails(mutation: str, match: str) -> None:
    canonical = _load().relative_context
    assert canonical is not None
    context = deepcopy(canonical)
    first = context["results"][0]
    if mutation == "duplicate":
        first["excess_vs_benchmark"]["id"] = first["excess_vs_peer_median"]["id"]
    elif mutation == "dangling":
        first["excess_vs_benchmark"]["inputs"][1] = "missing-result-1Y"
    elif mutation == "aggregate":
        first["peer_median"]["inputs"] = ["nxpi-return-1Y"]
    elif mutation == "circular":
        first["peer_median"]["inputs"][0] = first["excess_vs_peer_median"]["id"]
    else:
        first["excess_vs_benchmark"]["inputs"][1] = "soxx-return-3Y"
    with pytest.raises(ResearchRecordError, match=match):
        _validate_relative_result_provenance(context)


def test_quantitative_facts_preserve_missing_and_numeric_zero_semantics() -> None:
    record = _load()
    missing_facts = tuple(
        replace(fact, value=None) if fact.id == "f-auto-2025" else fact for fact in record.facts
    )
    missing_panel = _quantitative_facts(replace(record, facts=missing_facts))
    assert 'data-unavailable="f-auto-2025"' in missing_panel
    assert 'data-fact-id="f-auto-2025"' not in missing_panel
    assert 'data-value="0' not in missing_panel

    zero_facts = tuple(
        replace(fact, value=0.0) if fact.id == "f-auto-2025" else fact for fact in record.facts
    )
    zero_panel = _quantitative_facts(replace(record, facts=zero_facts))
    assert 'data-fact-id="f-auto-2025" data-value="0.0"' in zero_panel
    assert 'data-unavailable="f-auto-2025"' not in zero_panel


def test_real_renderer_accepts_non_qcom_record_without_qcom_assumptions(tmp_path: Path) -> None:
    record_path, manifest_path = _copy_inputs(tmp_path)
    issuer = {
        "name": "Example Devices",
        "ticker": "EXM",
        "cik": "0000000001",
        "exchange": "NYSE",
    }
    manifest = json.loads(manifest_path.read_text())
    manifest["issuer"] = issuer
    source_ids: list[str] = []
    for index, source in enumerate(manifest["sources"], start=1):
        old_local = tmp_path / source["local_path"]
        new_local = tmp_path / f"data/raw/example/source-{index}.pdf"
        new_local.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(old_local, new_local)
        source_id = f"example-source-{index}"
        source_ids.append(source_id)
        source["id"] = source_id
        source["publisher"] = "Example Devices"
        source["title"] = f"Example primary document {index}"
        source["canonical_url"] = f"https://example.com/document-{index}"
        source["download_url"] = f"https://example.com/document-{index}.pdf"
        source["discovery_url"] = "https://example.com/investors"
        source["availability_evidence"] = "Dated issuer publication record."
        source["local_path"] = str(new_local.relative_to(tmp_path))
    _write(manifest_path, manifest)
    record = {
        "schema_version": "1.0",
        "issuer": issuer,
        "universe_path": "data/research/qcom/universe.json",
        "as_of": "2026-09-01",
        "status": "research-only",
        "summary": "Example Devices supplies verified industrial components.",
        "business": ["The issuer designs and licenses industrial components."],
        "facts": [
            {
                "id": "f-sales-current",
                "label": "Validated current-period sales",
                "value": 120,
                "unit": "USD million",
                "period": "Current period",
                "source_id": source_ids[0],
                "locator": "p. 1",
            },
            {
                "id": "f-sales-prior",
                "label": "Validated prior-period sales",
                "value": 100,
                "unit": "USD million",
                "period": "Prior period",
                "source_id": source_ids[0],
                "locator": "p. 1",
            },
            {
                "id": "f-disclosure",
                "label": "Issuer risk disclosure",
                "value": None,
                "text": "Customer demand may vary.",
                "unit": None,
                "period": "Current filing",
                "source_id": source_ids[1],
                "locator": "p. 2",
            },
        ],
        "metrics": [
            {
                "id": "m-growth",
                "label": "Sales growth",
                "formula": "(f-sales-current / f-sales-prior) - 1",
                "inputs": ["f-sales-current", "f-sales-prior"],
                "unit": "percent",
            }
        ],
        "assumptions": [{"id": "a-base", "text": "No probability assigned."}],
        "interpretations": [
            {
                "id": "i-thesis",
                "kind": "thesis",
                "text": "Sales increased in the observed periods.",
                "supports": ["f-sales-current", "f-sales-prior"],
                "contradicts": ["f-disclosure"],
            },
            {
                "id": "i-counter",
                "kind": "counterthesis",
                "text": "Demand variability remains a disclosed risk.",
                "supports": ["f-disclosure"],
                "contradicts": ["f-sales-current"],
            },
        ],
        "risks": [
            {
                "title": f"Observed risk {index}",
                "mechanism": "The issuer discloses demand variability.",
                "evidence": ["f-disclosure"],
                "review": "Review the next issuer filing.",
            }
            for index in range(1, 4)
        ],
        "invalidation": ["Condition one", "Condition two", "Condition three"],
        "valuation": {"status": "incomplete", "gap": "Validated market inputs unavailable."},
    }
    _write(record_path, record)
    _write(tmp_path / record["universe_path"], {"symbols": ["EXM"]})
    implementation = tmp_path / "src/qhapaq_finance"
    implementation.mkdir(parents=True)
    for name in ("research.py", "research_report.py", "cli.py"):
        shutil.copy2(ROOT / "src/qhapaq_finance" / name, implementation / name)
    shutil.copy2(ROOT / "uv.lock", tmp_path / "uv.lock")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    output = render_research_report(
        record_path=record_path,
        manifest_path=manifest_path,
        output_path=tmp_path / "example.html",
        as_of=date(2026, 9, 1),
        repository_root=tmp_path,
    )
    content = output.read_text()
    assert "Example Devices" in content
    assert "Validated current-period sales" in content
    for forbidden in ("QUALCOMM", "QCOM", "QCT", "handset", "automotive", "automoción"):
        assert forbidden.lower() not in content.lower()


def test_existing_output_is_preserved_before_replacement(tmp_path: Path) -> None:
    output = tmp_path / "research.html"
    output.write_text("old", encoding="utf-8")
    render_research_report(
        record_path=RECORD,
        manifest_path=MANIFEST,
        output_path=output,
        as_of=date(2026, 9, 1),
        repository_root=ROOT,
    )
    assert output.with_suffix(".previous.html").read_text() == "old"


@pytest.mark.parametrize("missing", ["manifest", "source"])
def test_missing_inputs_fail(tmp_path: Path, missing: str) -> None:
    record, manifest = _copy_inputs(tmp_path)
    if missing == "manifest":
        manifest.unlink()
    else:
        payload = json.loads(manifest.read_text())
        (tmp_path / payload["sources"][0]["local_path"]).unlink()
    with pytest.raises(FileNotFoundError):
        load_research_record(
            record_path=record,
            manifest_path=manifest,
            repository_root=tmp_path,
            as_of=date(2026, 9, 1),
        )


def test_source_hash_mismatch_fails(tmp_path: Path) -> None:
    record, manifest = _copy_inputs(tmp_path)
    payload = json.loads(manifest.read_text())
    source = tmp_path / payload["sources"][0]["local_path"]
    source.write_bytes(source.read_bytes() + b"x")
    with pytest.raises(ResearchRecordError, match="byte count mismatch"):
        load_research_record(
            record_path=record,
            manifest_path=manifest,
            repository_root=tmp_path,
            as_of=date(2026, 9, 1),
        )


def test_relative_series_hash_mismatch_fails(tmp_path: Path) -> None:
    record, manifest = _copy_inputs(tmp_path)
    relative = tmp_path / "data/research/qcom/relative-context.json"
    payload = json.loads(relative.read_text())
    series = payload["series"][0]
    source = tmp_path / series["local_path"]
    source.write_bytes(source.read_bytes() + b"x")
    with pytest.raises(ResearchRecordError, match="relative series QCOM byte count mismatch"):
        load_research_record(
            record_path=record,
            manifest_path=manifest,
            repository_root=tmp_path,
            as_of=date(2026, 9, 1),
        )


def test_declared_missing_relative_context_fails(tmp_path: Path) -> None:
    record, manifest = _copy_inputs(tmp_path)
    (tmp_path / "data/research/qcom/relative-context.json").unlink()
    with pytest.raises(FileNotFoundError, match="relative context not found"):
        load_research_record(
            record_path=record,
            manifest_path=manifest,
            repository_root=tmp_path,
            as_of=date(2026, 9, 1),
        )


def test_relative_results_are_independent_of_host_timezone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs = []
    for zone in ("UTC", "America/Lima"):
        monkeypatch.setenv("TZ", zone)
        time.tzset()
        outputs.append(deepcopy(_load().relative_context))
    assert outputs[0] == outputs[1]


def test_future_source_and_bad_date_fail(tmp_path: Path) -> None:
    record, manifest = _copy_inputs(tmp_path)
    payload = json.loads(manifest.read_text())
    payload["sources"][0]["publication_date"] = "2026-09-02"
    _write(manifest, payload)
    with pytest.raises(ResearchRecordError, match="published after cutoff"):
        load_research_record(
            record_path=record,
            manifest_path=manifest,
            repository_root=tmp_path,
            as_of=date(2026, 9, 1),
        )
    payload["sources"][0]["publication_date"] = "2026/09/01"
    _write(manifest, payload)
    with pytest.raises(ResearchRecordError, match="valid ISO date"):
        load_research_record(
            record_path=record,
            manifest_path=manifest,
            repository_root=tmp_path,
            as_of=date(2026, 9, 1),
        )


@pytest.mark.parametrize(
    "mutation,match",
    [
        ("duplicate", "duplicate fact"),
        ("dangling", "dangling source"),
        ("nonfinite", "finite or null"),
        ("unit", "invalid fact unit"),
        ("zero", "denominator"),
    ],
)
def test_invalid_fact_contracts_fail(tmp_path: Path, mutation: str, match: str) -> None:
    record, manifest = _copy_inputs(tmp_path)
    payload = json.loads(record.read_text())
    if mutation == "duplicate":
        payload["facts"].append(payload["facts"][0])
    elif mutation == "dangling":
        payload["facts"][0]["source_id"] = "missing"
    elif mutation == "nonfinite":
        payload["facts"][0]["value"] = float("inf")
    elif mutation == "unit":
        payload["facts"][0]["unit"] = "bananas"
    else:
        payload["facts"][1]["value"] = 0
    _write(record, payload)
    with pytest.raises(ResearchRecordError, match=match):
        load_research_record(
            record_path=record,
            manifest_path=manifest,
            repository_root=tmp_path,
            as_of=date(2026, 9, 1),
        )


def test_issuer_universe_and_unsafe_paths_fail(tmp_path: Path) -> None:
    record, manifest = _copy_inputs(tmp_path)
    payload = json.loads(record.read_text())
    payload["issuer"]["ticker"] = "NOPE"
    manifest_payload = json.loads(manifest.read_text())
    manifest_payload["issuer"]["ticker"] = "NOPE"
    _write(record, payload)
    _write(manifest, manifest_payload)
    with pytest.raises(ResearchRecordError, match="not a member"):
        load_research_record(
            record_path=record,
            manifest_path=manifest,
            repository_root=tmp_path,
            as_of=date(2026, 9, 1),
        )
    payload["universe_path"] = "../outside.json"
    _write(record, payload)
    with pytest.raises(ResearchRecordError, match="safe"):
        load_research_record(
            record_path=record,
            manifest_path=manifest,
            repository_root=tmp_path,
            as_of=date(2026, 9, 1),
        )


def test_html_escapes_text_and_rejects_protected_output(tmp_path: Path) -> None:
    unsafe = replace(_load(), summary="<img src=x onerror=alert(1)>")
    content = build_research_html(unsafe)
    assert "&lt;img" in content and "<img src=x" not in content
    with pytest.raises(ValueError, match="distinct"):
        render_research_report(
            record_path=RECORD,
            manifest_path=MANIFEST,
            output_path=RECORD,
            as_of=date(2026, 9, 1),
            repository_root=ROOT,
        )


def test_loader_has_no_network_or_model_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")),
    )
    assert _load().issuer["ticker"] == "QCOM"


def test_cli_help_success_and_invalid_input(tmp_path: Path) -> None:
    help_result = subprocess.run(
        [sys.executable, "-m", "qhapaq_finance.cli", "research", "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "--record" in help_result.stdout
    output = tmp_path / "cli.html"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "qhapaq_finance.cli",
            "research",
            "--record",
            str(RECORD),
            "--manifest",
            str(MANIFEST),
            "--output",
            str(output),
            "--as-of",
            "2026-09-01",
        ],
        cwd=ROOT,
        env={**os.environ},
        capture_output=True,
        text=True,
        check=True,
    )
    assert "issuer=QUALCOMM" in result.stdout and output.is_file()
    bad = subprocess.run(
        [
            sys.executable,
            "-m",
            "qhapaq_finance.cli",
            "research",
            "--record",
            str(tmp_path / "missing"),
            "--manifest",
            str(MANIFEST),
            "--output",
            str(tmp_path / "bad.html"),
            "--as-of",
            "2026-09-01",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert bad.returncode != 0


def test_cli_reports_identity_and_coverage_from_non_qcom_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    record_path, manifest_path = _copy_inputs(tmp_path)
    record_payload = json.loads(record_path.read_text())
    manifest_payload = json.loads(manifest_path.read_text())
    issuer = {"name": "Example Devices", "ticker": "EXM", "cik": "0000000001", "exchange": "NYSE"}
    record_payload["issuer"] = issuer
    manifest_payload["issuer"] = issuer
    manifest_payload["sources"][0]["title"] = "Example annual filing"
    universe_path = tmp_path / record_payload["universe_path"]
    _write(universe_path, {"symbols": ["EXM"]})
    _write(record_path, record_payload)
    _write(manifest_path, manifest_payload)
    validated = load_research_record(
        record_path=record_path,
        manifest_path=manifest_path,
        repository_root=tmp_path,
        as_of=date(2026, 9, 1),
    )

    def fake_render(**kwargs: object) -> Path:
        output = kwargs["output_path"]
        assert isinstance(output, Path)
        output.write_text("report", encoding="utf-8")
        return output

    monkeypatch.setattr(cli, "load_research_record", lambda **_: validated)
    monkeypatch.setattr(cli, "render_research_report", fake_render)
    output = tmp_path / "example.html"
    cli._research(
        [
            "--record",
            str(record_path),
            "--manifest",
            str(manifest_path),
            "--output",
            str(output),
            "--as-of",
            "2026-09-01",
        ]
    )
    stdout = capsys.readouterr().out
    assert "issuer=Example Devices (EXM)" in stdout
    assert "Example annual filing [FY ended 2025-09-28]" in stdout
    assert "QUALCOMM" not in stdout
