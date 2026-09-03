"""Typed, checksum-gated company research records."""

import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .data import file_sha256


class ResearchRecordError(ValueError):
    """Raised when research evidence violates the local contract."""


MAX_CALENDAR_DISTANCE_DAYS = 7


@dataclass(frozen=True)
class SourceDocument:
    id: str
    title: str
    publisher: str
    canonical_url: str
    local_path: Path
    repository_path: Path
    publication_date: date
    reporting_period: str
    retrieval_timestamp: datetime
    download_url: str
    discovery_url: str
    media_type: str
    availability_evidence: str
    sha256: str
    byte_count: int


@dataclass(frozen=True)
class Fact:
    id: str
    label: str
    value: float | None
    unit: str | None
    period: str
    source_id: str
    locator: str
    text: str | None = None


@dataclass(frozen=True)
class Metric:
    id: str
    label: str
    formula: str
    inputs: tuple[str, ...]
    unit: str
    value: float


@dataclass(frozen=True)
class ResearchRecord:
    issuer: dict[str, str]
    as_of: date
    status: str
    summary: str
    business: tuple[str, ...]
    sources: tuple[SourceDocument, ...]
    facts: tuple[Fact, ...]
    metrics: tuple[Metric, ...]
    assumptions: tuple[dict[str, Any], ...]
    interpretations: tuple[dict[str, Any], ...]
    risks: tuple[dict[str, Any], ...]
    invalidation: tuple[str, ...]
    valuation: dict[str, str]
    input_hashes: dict[str, str]
    relative_context: dict[str, Any] | None = None


def _read_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    try:

        def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, item in pairs:
                if key in result:
                    raise ResearchRecordError(f"duplicate key in {label}: {key}")
                result[key] = item
            return result

        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_keys
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResearchRecordError(f"invalid {label}: {path}") from exc
    if not isinstance(value, dict):
        raise ResearchRecordError(f"{label} root must be an object")
    return value


def _date(value: Any, field: str) -> date:
    if not isinstance(value, str):
        raise ResearchRecordError(f"{field} must be an ISO date")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ResearchRecordError(f"{field} must be a valid ISO date") from exc
    if parsed.isoformat() != value:
        raise ResearchRecordError(f"{field} must use YYYY-MM-DD")
    return parsed


def _timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ResearchRecordError(f"{field} must be a non-empty ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ResearchRecordError(f"{field} must be a valid ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ResearchRecordError(f"{field} must include a UTC offset")
    return parsed


def _required_text(item: dict[str, Any], field: str, context: str) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ResearchRecordError(f"{context} {field} must be a non-empty string")
    return value


def _https_url(item: dict[str, Any], field: str, context: str) -> str:
    value = _required_text(item, field, context)
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ResearchRecordError(f"{context} {field} must be a valid https URL")
    return value


def _unique(items: list[dict[str, Any]], category: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        identifier = item.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise ResearchRecordError(f"{category} id must be a non-empty string")
        if identifier in result:
            raise ResearchRecordError(f"duplicate {category} id: {identifier}")
        result[identifier] = item
    return result


def _safe_local(root: Path, raw: Any) -> Path:
    if not isinstance(raw, str):
        raise ResearchRecordError("source local_path must be a string")
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts:
        raise ResearchRecordError("source local_path must be repository-relative and safe")
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(root):
        raise ResearchRecordError("source local_path escapes repository root")
    return resolved


def _metric_value(formula: str, values: list[float]) -> float:
    if any(value == 0 for value in values[1:]):
        raise ResearchRecordError("metric denominator cannot be zero")
    if formula.startswith("(") and formula.endswith("- 1") and len(values) == 2:
        return values[0] / values[1] - 1
    if " / " in formula and len(values) == 2:
        return values[0] / values[1]
    if " - " in formula and len(values) == 2:
        return values[0] - values[1]
    raise ResearchRecordError(f"unsupported metric formula: {formula}")


def load_research_record(
    *, record_path: Path, manifest_path: Path, repository_root: Path, as_of: date
) -> ResearchRecord:
    """Load and validate exact local evidence with no network or fallback path."""
    root = repository_root.resolve()
    record_file, manifest_file = record_path.resolve(), manifest_path.resolve()
    record, manifest = (
        _read_json(record_file, "research record"),
        _read_json(manifest_file, "research manifest"),
    )
    if record.get("schema_version") != "1.0" or manifest.get("schema_version") != "1.0":
        raise ResearchRecordError("unsupported schema_version")
    retrieved_at = _timestamp(manifest.get("retrieved_at"), "manifest retrieved_at")
    declared_as_of = _date(record.get("as_of"), "as_of")
    if declared_as_of != as_of:
        raise ResearchRecordError("requested cutoff does not match research record")
    issuer = record.get("issuer")
    if not isinstance(issuer, dict) or issuer != manifest.get("issuer"):
        raise ResearchRecordError("issuer mismatch between record and manifest")
    universe_path = _safe_local(root, record.get("universe_path"))
    universe = _read_json(universe_path, "research universe")
    raw_symbols = universe.get("symbols")
    if not isinstance(raw_symbols, list) or not all(isinstance(x, str) for x in raw_symbols):
        raise ResearchRecordError("research universe symbols must be strings")
    symbols: list[str] = raw_symbols
    if symbols != sorted(set(symbols)):
        raise ResearchRecordError("research universe symbols must be unique and sorted")
    if issuer.get("ticker") not in symbols:
        raise ResearchRecordError("issuer is not a member of the supplied research universe")

    raw_sources = manifest.get("sources")
    if not isinstance(raw_sources, list) or len(raw_sources) < 2:
        raise ResearchRecordError("at least two source documents are required")
    source_map = _unique(raw_sources, "source")
    sources: list[SourceDocument] = []
    for item in raw_sources:
        published = _date(item.get("publication_date"), "source publication_date")
        if published > as_of:
            raise ResearchRecordError(f"source {item['id']} was published after cutoff")
        local = _safe_local(root, item.get("local_path"))
        if not local.is_file():
            raise FileNotFoundError(f"research source not found: {local}")
        byte_count = item.get("byte_count")
        digest = item.get("sha256")
        if not isinstance(byte_count, int) or byte_count < 1 or local.stat().st_size != byte_count:
            raise ResearchRecordError(f"source {item['id']} byte count mismatch")
        if not isinstance(digest, str) or len(digest) != 64 or file_sha256(local) != digest:
            raise ResearchRecordError(f"source {item['id']} checksum mismatch")
        context = f"source {item['id']}"
        canonical_url = _https_url(item, "canonical_url", context)
        download_url = _https_url(item, "download_url", context)
        discovery_url = _https_url(item, "discovery_url", context)
        media_type = _required_text(item, "media_type", context)
        if "/" not in media_type or any(character.isspace() for character in media_type):
            raise ResearchRecordError(f"{context} media_type must be a valid media type")
        availability_evidence = _required_text(item, "availability_evidence", context)
        sources.append(
            SourceDocument(
                id=item["id"],
                title=_required_text(item, "title", context),
                publisher=_required_text(item, "publisher", context),
                canonical_url=canonical_url,
                local_path=local,
                repository_path=Path(item["local_path"]),
                publication_date=published,
                reporting_period=_required_text(item, "reporting_period", context),
                retrieval_timestamp=retrieved_at,
                download_url=download_url,
                discovery_url=discovery_url,
                media_type=media_type,
                availability_evidence=availability_evidence,
                sha256=digest,
                byte_count=byte_count,
            )
        )

    raw_facts = record.get("facts")
    if not isinstance(raw_facts, list) or not raw_facts:
        raise ResearchRecordError("facts must be a non-empty array")
    fact_map = _unique(raw_facts, "fact")
    facts: list[Fact] = []
    allowed_units = {"USD million", "percent", "count"}
    for item in raw_facts:
        source_id = item.get("source_id")
        if source_id not in source_map:
            raise ResearchRecordError(f"dangling source reference: {source_id}")
        value = item.get("value")
        text = item.get("text")
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ResearchRecordError(f"fact {item['id']} value must be finite or null")
        if text is not None and (not isinstance(text, str) or not text.strip()):
            raise ResearchRecordError(f"fact {item['id']} text must be non-empty or absent")
        if value is not None and text is not None:
            raise ResearchRecordError(f"fact {item['id']} cannot have both value and text")
        unit = item.get("unit")
        if value is not None and unit not in allowed_units:
            raise ResearchRecordError(f"invalid fact unit: {unit}")
        if value is None and text is not None and unit is not None:
            raise ResearchRecordError(f"text fact {item['id']} must not have a numeric unit")
        if value is None and text is None and unit is not None and unit not in allowed_units:
            raise ResearchRecordError(f"invalid fact unit: {unit}")
        facts.append(
            Fact(
                item["id"],
                str(item.get("label", "")),
                None if value is None else float(value),
                unit,
                str(item.get("period", "")),
                source_id,
                str(item.get("locator", "")),
                text,
            )
        )

    raw_metrics = record.get("metrics")
    if not isinstance(raw_metrics, list):
        raise ResearchRecordError("metrics must be an array")
    _unique(raw_metrics, "metric")
    metrics: list[Metric] = []
    for item in raw_metrics:
        inputs = item.get("inputs")
        if (
            not isinstance(inputs, list)
            or len(inputs) != 2
            or any(key not in fact_map for key in inputs)
        ):
            raise ResearchRecordError(f"metric {item['id']} has dangling or invalid inputs")
        values = [fact_map[key].get("value") for key in inputs]
        if any(value is None for value in values):
            raise ResearchRecordError(f"metric {item['id']} depends on unknown evidence")
        numeric: list[float] = []
        for value in values:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ResearchRecordError(f"metric {item['id']} has nonnumeric inputs")
            numeric.append(float(value))
        result = _metric_value(str(item.get("formula")), numeric)
        if not math.isfinite(result):
            raise ResearchRecordError(f"metric {item['id']} is nonfinite")
        metrics.append(
            Metric(
                item["id"],
                str(item.get("label", "")),
                str(item.get("formula")),
                tuple(inputs),
                str(item.get("unit", "")),
                result,
            )
        )

    interpretations = record.get("interpretations")
    if not isinstance(interpretations, list) or {
        x.get("kind") for x in interpretations if isinstance(x, dict)
    } != {"thesis", "counterthesis"}:
        raise ResearchRecordError("record requires thesis and counterthesis interpretations")
    for item in interpretations:
        for key in ("supports", "contradicts"):
            refs = item.get(key)
            if not isinstance(refs, list) or any(ref not in fact_map for ref in refs):
                raise ResearchRecordError(f"interpretation {item.get('id')} has dangling {key}")
    risks = record.get("risks")
    invalidation = record.get("invalidation")
    if (
        not isinstance(risks, list)
        or len(risks) < 3
        or not isinstance(invalidation, list)
        or len(invalidation) < 3
    ):
        raise ResearchRecordError("at least three risks and invalidation conditions are required")
    for risk in risks:
        if not isinstance(risk, dict):
            raise ResearchRecordError("risk entries must be objects")
        refs = risk.get("evidence")
        if not isinstance(refs, list) or not refs or any(ref not in fact_map for ref in refs):
            raise ResearchRecordError(f"risk {risk.get('title')} has dangling evidence")
    relative = load_relative_context(root, record.get("relative_context_path"), source_map, as_of)
    input_hashes = {
        "record": file_sha256(record_file),
        "manifest": file_sha256(manifest_file),
        "universe": file_sha256(universe_path),
    }
    if relative:
        input_hashes["relative_context"] = relative["provenance"]["record"]
        input_hashes.update(
            {
                f"relative_series:{entity}": digest
                for entity, digest in relative["provenance"]["series"].items()
            }
        )
    return ResearchRecord(
        issuer={str(k): str(v) for k, v in issuer.items()},
        as_of=as_of,
        status=str(record.get("status")),
        summary=str(record.get("summary")),
        business=tuple(str(x) for x in record.get("business", [])),
        sources=tuple(sources),
        facts=tuple(facts),
        metrics=tuple(metrics),
        assumptions=tuple(record.get("assumptions", [])),
        interpretations=tuple(interpretations),
        risks=tuple(risks),
        invalidation=tuple(str(x) for x in invalidation),
        valuation=dict(record.get("valuation", {})),
        input_hashes=input_hashes,
        relative_context=relative,
    )


def load_relative_context(
    root: Path, raw_path: Any, source_map: dict[str, dict[str, Any]], as_of: date
) -> dict[str, Any] | None:
    """Load frozen market context; absent context preserves v1.0 record compatibility."""
    if raw_path is None:
        return None
    path = _safe_local(root, raw_path)
    if not path.is_file():
        raise FileNotFoundError(f"relative context not found: {path}")
    payload = _read_json(path, "relative context")
    if (
        payload.get("schema_version") != "0.1"
        or _date(payload.get("as_of"), "relative_context as_of") != as_of
    ):
        raise ResearchRecordError("unsupported or mismatched relative_context")
    entities = payload.get("entities")
    if not isinstance(entities, list) or not entities:
        raise ResearchRecordError("relative_context entities must be non-empty")
    ids = {e.get("id") for e in entities if isinstance(e, dict)}
    if len(ids) != len(entities) or not {"QCOM", "NXPI", "MEDIATEK", "AVGO", "SOXX"} <= ids:
        raise ResearchRecordError("relative_context entities are incomplete or duplicated")
    series_by_entity = {
        s.get("entity_id"): s for s in payload.get("series", []) if isinstance(s, dict)
    }
    if set(series_by_entity) != {"QCOM", "NXPI", "MEDIATEK", "AVGO", "SOXX"}:
        raise ResearchRecordError("relative_context series are incomplete")
    for entity, series in series_by_entity.items():
        basis = series.get("price_basis")
        if basis not in {
            "adjusted_total_return",
            "adjusted_price",
            "unadjusted_close",
            "unavailable",
        }:
            raise ResearchRecordError(f"invalid price_basis for {entity}")
        source_id = series.get("source_id")
        if basis == "unavailable":
            if not series.get("unavailable_reason") or source_id is not None:
                raise ResearchRecordError(
                    f"unavailable series {entity} requires reason and no source"
                )
            continue
        if source_id not in source_map and not series.get("local_path"):
            raise ResearchRecordError(f"relative series {entity} has dangling source")
        local = _safe_local(root, series.get("local_path"))
        if not local.is_file():
            raise FileNotFoundError(f"relative series not found: {local}")
        byte_count = series.get("byte_count")
        digest = series.get("sha256")
        if not isinstance(byte_count, int) or byte_count < 1 or local.stat().st_size != byte_count:
            raise ResearchRecordError(f"relative series {entity} byte count mismatch")
        if not isinstance(digest, str) or len(digest) != 64 or file_sha256(local) != digest:
            raise ResearchRecordError(f"relative series {entity} checksum mismatch")
    peer_ids = {
        e["id"] for e in entities if e.get("role") == "peer" and e.get("included_in_peer_median")
    }
    if peer_ids != {"NXPI", "MEDIATEK", "AVGO"}:
        raise ResearchRecordError("approved peer universe mismatch")
    if any(e.get("role") == "benchmark" and e.get("id") != "SOXX" for e in entities):
        raise ResearchRecordError("benchmark must be SOXX")
    results = {}
    for entity, series in series_by_entity.items():
        results[entity] = _relative_series_results(root, series, source_map, as_of)
    windows = payload.get("methodology", {}).get("windows", ["1Y", "3Y", "5Y"])
    relative_results = []
    for window in windows:
        rows = {e: results[e].get(window) for e in results}
        q = rows["QCOM"]
        benchmark = rows["SOXX"]
        eligible = [
            rows[e]["return"]  # type: ignore[index]
            for e in peer_ids
            if rows[e] and rows[e].get("status") == "ok"  # type: ignore[index,union-attr]
        ]
        median = (
            sorted(eligible)[len(eligible) // 2]
            if len(eligible) % 2
            else (
                sum(sorted(eligible)[len(eligible) // 2 - 1 : len(eligible) // 2 + 1]) / 2
                if len(eligible) >= 2
                else None
            )
        )
        row = {
            "window": window,
            "subject": q,
            "benchmark": benchmark,
            "peer_median": {"status": "ok", "return": median, "eligible_peer_count": len(eligible)}
            if median is not None
            else {"status": "unavailable", "reason": "Fewer than two eligible core peers."},
        }
        if median is not None:
            peer_inputs = [
                f"{e.lower()}-return-{window}"
                for e in sorted(peer_ids)
                if rows[e] and rows[e].get("status") == "ok"  # type: ignore[union-attr]
            ]
            row["peer_median"]["id"] = f"peer-median-{window}"
            row["peer_median"]["inputs"] = peer_inputs
            row["peer_range"] = {
                "id": f"peer-range-{window}",
                "status": "ok",
                "minimum": min(eligible),
                "maximum": max(eligible),
                "inputs": peer_inputs,
            }
        else:
            row["peer_range"] = {
                "status": "unavailable",
                "reason": "Fewer than two eligible core peers.",
            }
        if q and q.get("status") == "ok":
            row["excess_vs_peer_median"] = (
                {
                    "id": f"qcom-excess-peer-{window}",
                    "status": "ok",
                    "value": q["return"] - median,
                    "inputs": [q["id"], f"peer-median-{window}"],
                }
                if median is not None
                else {"status": "unavailable", "reason": "Peer median unavailable."}
            )
            row["excess_vs_benchmark"] = (
                {
                    "id": f"qcom-excess-benchmark-{window}",
                    "status": "ok",
                    "value": q["return"] - benchmark["return"],
                    "inputs": [q["id"], benchmark["id"]],
                }
                if benchmark and benchmark.get("status") == "ok"
                else {"status": "unavailable", "reason": "Benchmark window unavailable."}
            )
        else:
            row["excess_vs_peer_median"] = {
                "status": "unavailable",
                "reason": "QCOM window unavailable.",
            }
            row["excess_vs_benchmark"] = {
                "status": "unavailable",
                "reason": "QCOM window unavailable.",
            }
        relative_results.append(row)
    payload["methodology"]["max_calendar_distance_days"] = MAX_CALENDAR_DISTANCE_DAYS
    context = {
        "methodology": payload["methodology"],
        "entities": entities,
        "series": series_by_entity,
        "results": relative_results,
        "series_results": {w: {e: results[e].get(w) for e in results} for w in windows},
        "provenance": {
            "record": file_sha256(path),
            "series": {
                entity: series["sha256"]
                for entity, series in series_by_entity.items()
                if series["price_basis"] != "unavailable"
            },
        },
    }
    _validate_relative_result_provenance(context)
    return context


def _validate_relative_result_provenance(context: dict[str, Any]) -> None:
    """Fail closed unless relative derived results form the expected acyclic graph."""
    windows = context["methodology"].get("windows")
    results = context.get("results")
    series_results = context.get("series_results")
    if (
        not isinstance(windows, list)
        or not isinstance(results, list)
        or not isinstance(series_results, dict)
    ):
        raise ResearchRecordError("invalid derived result provenance graph")

    nodes: dict[str, dict[str, Any]] = {}
    derived: list[tuple[str, str, dict[str, Any]]] = []

    def add_node(node: object, *, kind: str, window: str) -> None:
        if not isinstance(node, dict) or node.get("status") != "ok":
            return
        result_id = node.get("id")
        if not isinstance(result_id, str) or not result_id:
            raise ResearchRecordError("derived result provenance requires a valid result ID")
        if result_id in nodes:
            raise ResearchRecordError(f"duplicate derived result ID: {result_id}")
        nodes[result_id] = node
        if kind != "series":
            derived.append((kind, window, node))

    for window in windows:
        window_results = series_results.get(window)
        if not isinstance(window, str) or not isinstance(window_results, dict):
            raise ResearchRecordError("invalid derived result provenance graph")
        for result in window_results.values():
            add_node(result, kind="series", window=window)

    rows_by_window: dict[str, dict[str, Any]] = {}
    for row in results:
        if not isinstance(row, dict) or row.get("window") in rows_by_window:
            raise ResearchRecordError("invalid derived result provenance graph")
        window = row.get("window")
        if not isinstance(window, str) or window not in windows:
            raise ResearchRecordError("invalid derived result provenance graph")
        rows_by_window[window] = row
        for kind in (
            "peer_median",
            "peer_range",
            "excess_vs_peer_median",
            "excess_vs_benchmark",
        ):
            add_node(row.get(kind), kind=kind, window=window)
    if set(rows_by_window) != set(windows):
        raise ResearchRecordError("invalid derived result provenance graph")

    edges: dict[str, tuple[str, ...]] = {}
    for _, _, node in derived:
        inputs = node.get("inputs")
        if (
            not isinstance(inputs, list)
            or not inputs
            or any(not isinstance(input_id, str) for input_id in inputs)
        ):
            raise ResearchRecordError(f"derived result {node['id']} has invalid inputs")
        dangling = [input_id for input_id in inputs if input_id not in nodes]
        if dangling:
            raise ResearchRecordError(
                f"derived result {node['id']} has dangling input result ID: {dangling[0]}"
            )
        edges[node["id"]] = tuple(inputs)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(result_id: str) -> None:
        if result_id in visiting:
            raise ResearchRecordError("circular derived-result dependency")
        if result_id in visited:
            return
        visiting.add(result_id)
        for input_id in edges.get(result_id, ()):
            visit(input_id)
        visiting.remove(result_id)
        visited.add(result_id)

    for result_id in edges:
        visit(result_id)

    peer_ids = sorted(
        entity["id"]
        for entity in context["entities"]
        if entity.get("role") == "peer" and entity.get("included_in_peer_median")
    )
    for kind, window, node in derived:
        row = rows_by_window[window]
        window_results = series_results[window]
        qcom = window_results.get("QCOM")
        benchmark = window_results.get("SOXX")
        median = row.get("peer_median")
        if kind in {"peer_median", "peer_range"}:
            expected = sorted(
                window_results[peer]["id"]
                for peer in peer_ids
                if window_results.get(peer, {}).get("status") == "ok"
            )
        elif kind == "excess_vs_peer_median":
            if not isinstance(qcom, dict) or not isinstance(median, dict):
                raise ResearchRecordError("invalid derived result provenance graph")
            expected = [qcom.get("id"), median.get("id")]
        else:
            if not isinstance(qcom, dict) or not isinstance(benchmark, dict):
                raise ResearchRecordError("invalid derived result provenance graph")
            expected = [qcom.get("id"), benchmark.get("id")]
        if node["inputs"] != expected:
            raise ResearchRecordError(
                f"derived result {node['id']} has invalid or cross-window input set"
            )


def _relative_series_results(
    root: Path, series: dict[str, Any], source_map: dict[str, dict[str, Any]], as_of: date
) -> dict[str, Any]:
    if series["price_basis"] == "unavailable":
        return {
            w: {"status": "unavailable", "reason": series["unavailable_reason"]}
            for w in ("1Y", "3Y", "5Y")
        }
    source = source_map.get(series["source_id"], {"local_path": series["local_path"]})
    path = _safe_local(root, source["local_path"])
    data = _read_json(path, "market series")
    result = data.get("chart", {}).get("result", [None])[0]
    if not isinstance(result, dict):
        raise ResearchRecordError("invalid market series payload")
    timestamps = result.get("timestamp", [])
    closes = result.get("indicators", {}).get("adjclose", [{}])[0].get("adjclose", [])
    points = sorted(
        (datetime.fromtimestamp(t, tz=timezone.utc).date(), float(v))
        for t, v in zip(timestamps, closes, strict=False)
        if v is not None and datetime.fromtimestamp(t, tz=timezone.utc).date() <= as_of
    )
    if not points:
        return {
            w: {"status": "unavailable", "reason": "No observations on or before cutoff."}
            for w in ("1Y", "3Y", "5Y")
        }
    out: dict[str, Any] = {}
    for w, years in (("1Y", 1), ("3Y", 3), ("5Y", 5)):
        target = date(as_of.year - years, as_of.month, as_of.day)
        starts = [p for p in points if p[0] <= target]
        if not starts or (target - starts[-1][0]).days > MAX_CALENDAR_DISTANCE_DAYS:
            out[w] = {"status": "unavailable", "reason": "anniversary_anchor_outside_tolerance"}
            continue
        start, sv = starts[-1]
        end, ev = points[-1]
        out[w] = {
            "id": f"{series['entity_id'].lower()}-return-{w}",
            "status": "ok",
            "return": float(ev / sv - 1),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "source_id": series["source_id"],
            "price_basis": series["price_basis"],
            "start_value": sv,
            "end_value": ev,
        }
    return out
