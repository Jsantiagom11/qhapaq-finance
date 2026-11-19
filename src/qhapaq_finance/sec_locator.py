"""Deterministic SEC filing locators for sealed Diamond observations."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter, defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from qhapaq_finance.diamond.cache import DiamondCache
from qhapaq_finance.diamond.canonical_json import canonical_json_bytes, sha256_canonical_json
from qhapaq_finance.diamond.contracts import FundamentalObservation
from qhapaq_finance.diamond.providers.sec_canonical import (
    CanonicalIssuerCache,
    CanonicalObservationProvenance,
    canonicalize_issuer_with_provenance,
)
from qhapaq_finance.diamond.providers.sec_evidence import (
    SecEvidenceError,
    SecEvidenceManifest,
    SecEvidenceStore,
)
from qhapaq_finance.diamond.snapshot import DiamondSnapshotError, load_complete_snapshot
from qhapaq_finance.financial_canonicalization import RawFact

SEC_LOCATOR_MATRIX_SCHEMA_VERSION = "qhapaq-sec-locator-matrix-v1"
Classification = Literal[
    "EXACT_FILING_MATCH",
    "ISSUER_LEVEL_ONLY",
    "AMBIGUOUS",
    "EVIDENCE_MISSING",
]
_CLASSIFICATIONS: tuple[Classification, ...] = (
    "AMBIGUOUS",
    "EVIDENCE_MISSING",
    "EXACT_FILING_MATCH",
    "ISSUER_LEVEL_ONLY",
)


class SecLocatorAuditError(RuntimeError):
    """A provenance sidecar cannot be produced without overstating evidence."""


def _read_json(path: Path, code: str) -> Mapping[str, object]:
    try:
        decoded: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SecLocatorAuditError(code) from exc
    if not isinstance(decoded, dict):
        raise SecLocatorAuditError(code)
    return decoded


def _mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise SecLocatorAuditError(code)
    return value


def _list(value: object, code: str) -> list[object]:
    if not isinstance(value, list):
        raise SecLocatorAuditError(code)
    return value


def _text(value: object, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SecLocatorAuditError(code)
    return value


def _integer(value: object, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SecLocatorAuditError(code)
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise SecLocatorAuditError("SOURCE_FILE_UNREADABLE") from exc
    return digest.hexdigest()


def _json_pointer_segment(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _companyfacts_metadata(
    payload: Mapping[str, object],
) -> dict[str, tuple[str, str | None]]:
    facts = _mapping(payload.get("facts"), "SEC_PAYLOAD_INVALID")
    metadata: dict[str, tuple[str, str | None]] = {}
    for taxonomy, concepts_raw in facts.items():
        if not isinstance(taxonomy, str):
            raise SecLocatorAuditError("SEC_PAYLOAD_INVALID")
        concepts = _mapping(concepts_raw, "SEC_PAYLOAD_INVALID")
        for concept, detail_raw in concepts.items():
            if not isinstance(concept, str):
                raise SecLocatorAuditError("SEC_PAYLOAD_INVALID")
            detail = _mapping(detail_raw, "SEC_PAYLOAD_INVALID")
            units = _mapping(detail.get("units"), "SEC_PAYLOAD_INVALID")
            for unit, rows_raw in units.items():
                if not isinstance(unit, str):
                    raise SecLocatorAuditError("SEC_PAYLOAD_INVALID")
                rows = _list(rows_raw, "SEC_PAYLOAD_INVALID")
                for index, row_raw in enumerate(rows):
                    row = _mapping(row_raw, "SEC_PAYLOAD_INVALID")
                    frame_raw = row.get("frame")
                    if frame_raw is not None and not isinstance(frame_raw, str):
                        raise SecLocatorAuditError("SEC_PAYLOAD_INVALID")
                    fact_id = f"{taxonomy}:{concept}:{unit}:{index}"
                    pointer = "/".join(
                        (
                            "",
                            "facts",
                            _json_pointer_segment(taxonomy),
                            _json_pointer_segment(concept),
                            "units",
                            _json_pointer_segment(unit),
                            str(index),
                        )
                    )
                    metadata[fact_id] = (pointer, frame_raw)
    return metadata


def _fact_payload(
    fact: RawFact,
    *,
    metadata: Mapping[str, tuple[str, str | None]],
    payload_sha256: str,
) -> dict[str, object]:
    try:
        pointer, frame = metadata[fact.fact_id]
    except KeyError as exc:
        raise SecLocatorAuditError("SEC_FACT_LOCATOR_MISSING") from exc
    identity_payload = {
        "payload_sha256": payload_sha256,
        "fact_id": fact.fact_id,
        "taxonomy": fact.taxonomy,
        "concept": fact.concept,
        "value": fact.value,
        "unit": fact.unit,
        "period_kind": fact.period_kind.value,
        "period_start": fact.start.isoformat() if fact.start is not None else None,
        "period_end": fact.end.isoformat(),
        "fiscal_year": fact.fiscal_year,
        "fiscal_period": fact.fiscal_period,
        "form": fact.filing_form,
        "accession": fact.accession,
        "filing_date": fact.filing_date.isoformat(),
        "dimensions": list(fact.dimensions),
        "consolidated": fact.consolidated,
    }
    return {
        **identity_payload,
        "fact_identity_sha256": sha256_canonical_json(identity_payload),
        "companyfacts_json_pointer": pointer,
        "companyfacts_frame": frame,
        "native_context_id": None,
        "native_context_status": "UNAVAILABLE_IN_COMPANY_FACTS",
        "publication_timestamp": None,
        "publication_timestamp_status": "UNAVAILABLE_IN_COMPANY_FACTS",
    }


def _observation_matches(row: Mapping[str, object], observation: FundamentalObservation) -> bool:
    expected = {
        "metric_id": observation.metric_id,
        "fiscal_slot": observation.fiscal_slot.value,
        "value": observation.value,
        "unit_kind": observation.unit_kind.value,
        "period_kind": observation.period_kind.value,
        "period_start": (
            observation.period_start.isoformat() if observation.period_start is not None else None
        ),
        "period_end": observation.period_end.isoformat(),
        "source_provider": observation.source_provider,
        "source_identity": observation.source_identity,
    }
    return all(row.get(name) == value for name, value in expected.items())


def _base_observation(
    *,
    opportunity: Mapping[str, object],
    row: Mapping[str, object],
) -> dict[str, object]:
    ticker = _text(opportunity.get("ticker"), "REPORT_OPPORTUNITY_INVALID")
    issuer_id = _text(opportunity.get("issuer_id"), "REPORT_OPPORTUNITY_INVALID")
    evidence_id = _text(row.get("evidence_id"), "REPORT_EVIDENCE_INVALID")
    return {
        "observation_id": f"{issuer_id}:{evidence_id}",
        "rank": _integer(opportunity.get("rank"), "REPORT_OPPORTUNITY_INVALID"),
        "ticker": ticker,
        "issuer_id": issuer_id,
        "evidence_id": evidence_id,
        "metric_id": _text(row.get("metric_id"), "REPORT_EVIDENCE_INVALID"),
        "fiscal_slot": _text(row.get("fiscal_slot"), "REPORT_EVIDENCE_INVALID"),
        "value": row.get("value"),
        "unit_kind": row.get("unit_kind"),
        "period_kind": row.get("period_kind"),
        "period_start": row.get("period_start"),
        "period_end": row.get("period_end"),
        "source_provider": row.get("source_provider"),
        "source_identity": row.get("source_identity"),
    }


def _classified(
    base: Mapping[str, object],
    *,
    classification: Classification,
    reason: str,
    sec_source: Mapping[str, object] | None = None,
    lineage: CanonicalObservationProvenance | None = None,
    metadata: Mapping[str, tuple[str, str | None]] | None = None,
    payload_sha256: str | None = None,
) -> dict[str, object]:
    facts = (
        [
            _fact_payload(
                fact,
                metadata=metadata or {},
                payload_sha256=payload_sha256 or "",
            )
            for fact in lineage.source_facts
        ]
        if lineage is not None
        else []
    )
    return {
        **base,
        "classification": classification,
        "reason": reason,
        "sec_source": dict(sec_source) if sec_source is not None else None,
        "derivation": (
            {
                "kind": lineage.derivation_kind,
                "formula": lineage.formula,
                "transformations": list(lineage.transformations),
            }
            if lineage is not None
            else None
        ),
        "source_facts": facts,
    }


def _summary(observations: list[dict[str, object]]) -> dict[str, object]:
    statuses = Counter(str(item["classification"]) for item in observations)
    by_company: dict[str, list[dict[str, object]]] = defaultdict(list)
    by_metric: dict[str, list[dict[str, object]]] = defaultdict(list)
    for item in observations:
        by_company[str(item["ticker"])].append(item)
        by_metric[str(item["metric_id"])].append(item)

    def coverage(rows: list[dict[str, object]]) -> dict[str, object]:
        counts = Counter(str(item["classification"]) for item in rows)
        return {
            "total": len(rows),
            "by_status": {status: counts[status] for status in _CLASSIFICATIONS},
            "exact_coverage_ratio": counts["EXACT_FILING_MATCH"] / len(rows),
        }

    return {
        "total_observations": len(observations),
        "by_status": {status: statuses[status] for status in _CLASSIFICATIONS},
        "exact_coverage_ratio": statuses["EXACT_FILING_MATCH"] / len(observations),
        "by_company": {key: coverage(by_company[key]) for key in sorted(by_company)},
        "by_metric": {key: coverage(by_metric[key]) for key in sorted(by_metric)},
    }


def _sec_artifact(
    *,
    manifest: SecEvidenceManifest,
    snapshot_files: Mapping[str, str],
) -> dict[str, object]:
    identity_hash = hashlib.sha256(manifest.request_identity.encode("utf-8")).hexdigest()
    index_path = f"sec/index/{identity_hash}.json"
    blob_path = f"sec/blobs/{manifest.blob_name}"
    try:
        index_sha256 = snapshot_files[index_path]
        blob_sha256 = snapshot_files[blob_path]
    except KeyError as exc:
        raise SecLocatorAuditError("SEC_ARTIFACT_NOT_IN_SNAPSHOT") from exc
    if blob_sha256 != manifest.payload_sha256:
        raise SecLocatorAuditError("SEC_BLOB_IDENTITY_MISMATCH")
    return {
        "cik": manifest.cik,
        "request_identity": manifest.request_identity,
        "data_as_of": manifest.data_as_of.isoformat(),
        "retrieved_at": manifest.retrieved_at.isoformat(),
        "payload_path": blob_path,
        "payload_sha256": manifest.payload_sha256,
        "manifest_path": index_path,
        "manifest_sha256": index_sha256,
        "evidence_revision_sha256": manifest.evidence_revision_sha256,
    }


def build_sec_locator_matrix(
    *,
    snapshot_root: Path,
    opportunities_path: Path,
) -> dict[str, object]:
    """Classify every determinant observation against verified sealed source facts."""

    try:
        snapshot = load_complete_snapshot(Path(snapshot_root))
    except DiamondSnapshotError as exc:
        raise SecLocatorAuditError(str(exc)) from exc
    report = _read_json(Path(opportunities_path), "OPPORTUNITIES_REPORT_INVALID")
    report_snapshot = _mapping(report.get("snapshot"), "OPPORTUNITIES_REPORT_INVALID")
    if (
        report_snapshot.get("snapshot_id") != snapshot.snapshot_id
        or report.get("dataset_identity") != snapshot.dataset_identity
    ):
        raise SecLocatorAuditError("REPORT_SNAPSHOT_MISMATCH")

    snapshot_files = {item.relative_path: item.sha256 for item in snapshot.files}
    evidence_store = SecEvidenceStore(
        root=snapshot.cache_root / "sec",
        client=None,
        legacy_cache=None,
        offline=True,
    )
    canonical_cache = CanonicalIssuerCache(DiamondCache(snapshot.cache_root / "canonical"))
    output: list[dict[str, object]] = []

    for opportunity_raw in _list(report.get("opportunities"), "OPPORTUNITIES_REPORT_INVALID"):
        opportunity = _mapping(opportunity_raw, "REPORT_OPPORTUNITY_INVALID")
        rows = [
            _mapping(item, "REPORT_EVIDENCE_INVALID")
            for item in _list(opportunity.get("evidence"), "REPORT_OPPORTUNITY_INVALID")
        ]
        sec_rows = [row for row in rows if row.get("source_provider") == "sec"]
        for row in rows:
            if row.get("source_provider") != "sec":
                output.append(
                    _classified(
                        _base_observation(opportunity=opportunity, row=row),
                        classification="EVIDENCE_MISSING",
                        reason="NOT_SEC_FILING_METRIC",
                    )
                )
        if not sec_rows:
            continue

        issuer_id = _text(opportunity.get("issuer_id"), "REPORT_OPPORTUNITY_INVALID")
        if not issuer_id.startswith("sec-cik:"):
            raise SecLocatorAuditError("REPORT_ISSUER_INVALID")
        cik = issuer_id.removeprefix("sec-cik:")
        declared = _mapping(opportunity.get("sec_provenance"), "REPORT_SEC_PROVENANCE_INVALID")
        try:
            resolved = evidence_store.resolve(cik, snapshot.cutoff)
            facts = evidence_store.load_facts(resolved.manifest)
        except SecEvidenceError as exc:
            output.extend(
                _classified(
                    _base_observation(opportunity=opportunity, row=row),
                    classification="EVIDENCE_MISSING",
                    reason=str(exc),
                )
                for row in sec_rows
            )
            continue
        manifest = resolved.manifest
        if any(
            (
                declared.get("cik") != manifest.cik,
                declared.get("payload_sha256") != manifest.payload_sha256,
                declared.get("evidence_revision_sha256") != manifest.evidence_revision_sha256,
            )
        ):
            raise SecLocatorAuditError("REPORT_SEC_PROVENANCE_MISMATCH")

        cached = canonical_cache.load(
            issuer_id=issuer_id,
            as_of=snapshot.cutoff,
            history_years=5,
            evidence_revision_sha256=manifest.evidence_revision_sha256,
        )
        traced = canonicalize_issuer_with_provenance(
            issuer_id=issuer_id,
            cik=cik,
            as_of=snapshot.cutoff,
            history_years=5,
            evidence_revision_sha256=manifest.evidence_revision_sha256,
            facts=facts,
        )
        if cached is None or traced is None:
            output.extend(
                _classified(
                    _base_observation(opportunity=opportunity, row=row),
                    classification="ISSUER_LEVEL_ONLY",
                    reason="CANONICAL_LINEAGE_UNAVAILABLE",
                )
                for row in sec_rows
            )
            continue
        if cached != traced.snapshot:
            raise SecLocatorAuditError("CANONICAL_REPLAY_MISMATCH")

        blob_path = snapshot.cache_root / "sec" / "blobs" / manifest.blob_name
        payload = _read_json(blob_path, "SEC_PAYLOAD_INVALID")
        metadata = _companyfacts_metadata(payload)
        artifact = _sec_artifact(manifest=manifest, snapshot_files=snapshot_files)
        lineages: dict[tuple[str, str, str], list[CanonicalObservationProvenance]] = defaultdict(
            list
        )
        for item in traced.provenance:
            key = (
                item.observation.metric_id,
                item.observation.fiscal_slot.value,
                item.observation.period_end.isoformat(),
            )
            lineages[key].append(item)

        for row in sec_rows:
            base = _base_observation(opportunity=opportunity, row=row)
            key = (
                str(base["metric_id"]),
                str(base["fiscal_slot"]),
                str(base["period_end"]),
            )
            candidates = lineages.get(key, [])
            if len(candidates) > 1:
                output.append(
                    _classified(
                        base,
                        classification="AMBIGUOUS",
                        reason="MULTIPLE_CANONICAL_LINEAGES",
                        sec_source=artifact,
                    )
                )
            elif not candidates or not _observation_matches(row, candidates[0].observation):
                output.append(
                    _classified(
                        base,
                        classification="ISSUER_LEVEL_ONLY",
                        reason="CANONICAL_OBSERVATION_MISMATCH",
                        sec_source=artifact,
                    )
                )
            else:
                output.append(
                    _classified(
                        base,
                        classification="EXACT_FILING_MATCH",
                        reason="CANONICAL_SELECTOR_REPLAY_MATCH",
                        sec_source=artifact,
                        lineage=candidates[0],
                        metadata=metadata,
                        payload_sha256=manifest.payload_sha256,
                    )
                )

    if not output:
        raise SecLocatorAuditError("REPORT_HAS_NO_OBSERVATIONS")
    output.sort(
        key=lambda item: (
            _integer(item["rank"], "REPORT_OPPORTUNITY_INVALID"),
            str(item["evidence_id"]),
        )
    )
    candidate_set = _mapping(report.get("candidate_set"), "OPPORTUNITIES_REPORT_INVALID")
    return {
        "schema_version": SEC_LOCATOR_MATRIX_SCHEMA_VERSION,
        "source": {
            "snapshot_id": snapshot.snapshot_id,
            "snapshot_canonicalizer_version": snapshot.canonicalizer_version,
            "dataset_identity": snapshot.dataset_identity,
            "ranked_order_sha256": snapshot.ranked_order_sha256,
            "candidate_set_id": candidate_set.get("candidate_set_id"),
            "cutoff": snapshot.cutoff.isoformat(),
            "opportunities_sha256": _sha256_file(Path(opportunities_path)),
        },
        "classification_definitions": {
            "EXACT_FILING_MATCH": (
                "Canonical selector replay equals the sealed canonical cache and exposes every "
                "source Company Facts row."
            ),
            "ISSUER_LEVEL_ONLY": (
                "Verified issuer payload exists but exact observation lineage is not proven."
            ),
            "AMBIGUOUS": "More than one canonical lineage remains for the observation key.",
            "EVIDENCE_MISSING": "No admissible SEC filing evidence can support this observation.",
        },
        "summary": _summary(output),
        "observations": output,
    }


def sec_locator_matrix_json(matrix: Mapping[str, object]) -> bytes:
    """Serialize the sidecar deterministically."""

    return canonical_json_bytes(matrix) + b"\n"


def write_sec_locator_matrix(
    *,
    snapshot_root: Path,
    opportunities_path: Path,
    output_path: Path,
) -> dict[str, object]:
    """Build and atomically write one deterministic sidecar."""

    matrix = build_sec_locator_matrix(
        snapshot_root=snapshot_root,
        opportunities_path=opportunities_path,
    )
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(sec_locator_matrix_json(matrix))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return matrix


__all__ = [
    "SEC_LOCATOR_MATRIX_SCHEMA_VERSION",
    "SecLocatorAuditError",
    "build_sec_locator_matrix",
    "sec_locator_matrix_json",
    "write_sec_locator_matrix",
]
