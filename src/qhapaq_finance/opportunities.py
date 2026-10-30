"""Evidence-aware, deterministic research reports over Diamond results."""

from __future__ import annotations

import copy
import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from types import MappingProxyType
from typing import Any, cast

from qhapaq_finance.candidate_set import (
    CandidateSet,
    DiamondTopNPolicy,
    SnapshotStatus,
    build_candidate_set,
)

from .diamond.archetypes import Archetype
from .diamond.canonical_json import sha256_canonical_json
from .diamond.contracts import FundamentalObservation, FundamentalRecord, Methodology
from .diamond.engine import DiamondResult
from .diamond.funnel import FunnelRun
from .diamond.metrics import derive_financial_features
from .diamond.providers.sec_evidence import SecEvidenceManifest
from .diamond.snapshot import DiamondSnapshotManifest

OPPORTUNITY_REPORT_SCHEMA_VERSION = "diamond-opportunities-v0.1"
NON_RECOMMENDATION = (
    "This is a reproducible research-routing screen, not an investment recommendation, "
    "price target, or validated valuation."
)


class OpportunityReportError(ValueError):
    """The opportunity report cannot be built without violating its contract."""


@dataclass(frozen=True, slots=True)
class OpportunityReport:
    """Immutable wrapper around the canonical report document."""

    document: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "document",
            MappingProxyType(copy.deepcopy(dict(self.document))),
        )

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], copy.deepcopy(dict(self.document)))


_CATEGORY_FEATURES: dict[str, tuple[str, ...]] = {
    "quality": (
        "roic_proxy",
        "normalized_fcf_margin",
        "cash_conversion",
        "margin_dispersion",
        "fcf_margin_dispersion",
    ),
    "growth": (
        "revenue_cagr_5y",
        "revenue_cagr_3y",
        "fcf_margin_trend",
        "operating_margin_trend",
    ),
    "capital": (
        "net_debt_to_operating_income",
        "share_dilution_3y",
        "recent_share_change",
        "roic_proxy",
        "net_cash_indicator",
    ),
    "price": ("normalized_fcf_yield", "ebit_ev_yield"),
}

_ARCHETYPE_CATEGORIES: dict[Archetype, tuple[str, ...]] = {
    Archetype.COMPOUNDER: ("quality", "growth", "capital"),
    Archetype.QUALITY_VALUE: ("quality", "price", "capital"),
    Archetype.INFLECTION: ("growth", "quality", "price"),
}

_FEATURE_EVIDENCE_METRICS: dict[str, tuple[str, ...]] = {
    "roic_proxy": (
        "operating_income",
        "pretax_income",
        "income_tax_expense",
        "total_equity",
        "total_debt",
        "cash_and_equivalents",
        "marketable_securities",
    ),
    "normalized_fcf_margin": (
        "operating_cash_flow",
        "capital_expenditures",
        "revenue",
    ),
    "cash_conversion": (
        "operating_cash_flow",
        "capital_expenditures",
        "operating_income",
    ),
    "margin_dispersion": ("operating_income", "revenue"),
    "fcf_margin_dispersion": (
        "operating_cash_flow",
        "capital_expenditures",
        "revenue",
    ),
    "revenue_cagr_5y": ("revenue",),
    "revenue_cagr_3y": ("revenue",),
    "fcf_margin_trend": (
        "operating_cash_flow",
        "capital_expenditures",
        "revenue",
    ),
    "operating_margin_trend": ("operating_income", "revenue"),
    "net_debt_to_operating_income": (
        "total_debt",
        "cash_and_equivalents",
        "marketable_securities",
        "operating_income",
    ),
    "share_dilution_3y": ("diluted_shares",),
    "recent_share_change": (
        "shares_outstanding_latest",
        "shares_outstanding_fy1_end",
    ),
    "net_cash_indicator": (
        "total_debt",
        "cash_and_equivalents",
        "marketable_securities",
    ),
    "normalized_fcf_yield": (
        "operating_cash_flow",
        "capital_expenditures",
        "market_cap",
    ),
    "ebit_ev_yield": (
        "operating_income",
        "market_cap",
        "total_debt",
        "cash_and_equivalents",
        "marketable_securities",
    ),
}


def _candidate_set_dict(candidate_set: CandidateSet) -> dict[str, object]:
    return {
        "candidate_set_id": candidate_set.candidate_set_id,
        "snapshot": {
            "snapshot_id": candidate_set.snapshot.snapshot_id,
            "dataset_identity": candidate_set.snapshot.dataset_identity,
            "universe_id": candidate_set.snapshot.universe_id,
            "cutoff": candidate_set.snapshot.cutoff.isoformat(),
            "status": candidate_set.snapshot.status.value,
        },
        "policy": {
            "kind": "DIAMOND_TOP_N",
            "limit": candidate_set.policy.limit,
        },
        "candidates": [
            {
                "security": {
                    "ticker": item.security.ticker,
                    "security_id": item.security.security_id,
                    "issuer_id": item.security.issuer_id,
                },
                "diamond_rank": item.diamond_rank,
                "selection_order": item.selection_order,
            }
            for item in candidate_set.candidates
        ],
    }


def _rankable_results(funnel: FunnelRun) -> tuple[DiamondResult, ...]:
    complete = funnel.evaluated_results or funnel.results
    return tuple(
        item
        for item in complete
        if item.archetypes.research_priority is not None and item.archetypes.surfaced_by is not None
    )


def _ranked_security_ids(results: tuple[DiamondResult, ...]) -> tuple[str, ...]:
    identifiers: list[str] = []
    for result in results:
        if result.source_security is None:
            raise OpportunityReportError("SOURCE_SECURITY_REQUIRED")
        identifiers.append(result.source_security.security_id)
    return tuple(identifiers)


def _exclusion_reasons(result: DiamondResult) -> tuple[str, ...]:
    reasons = {"NO_RESEARCH_PRIORITY"}
    if result.methodology is not Methodology.OPERATING_COMPANY:
        reasons.add("UNSUPPORTED_METHODOLOGY")
    if "FUNDAMENTALS_STALE" in result.diagnostics:
        reasons.add("FUNDAMENTALS_STALE")
    for category, coverage in result.coverage.items():
        if coverage != "READY":
            reasons.add(f"{category.upper()}_{coverage}")
    return tuple(sorted(reasons))


def _exclusions(funnel: FunnelRun) -> tuple[dict[str, int], list[dict[str, object]]]:
    complete = funnel.evaluated_results or funnel.results
    reason_counts: Counter[str] = Counter()
    blocked: list[dict[str, object]] = []
    missing_canonical = funnel.metadata.universe_count - funnel.metadata.canonical_records
    if missing_canonical > 0:
        reason_counts["MISSING_CANONICAL_RECORD"] += missing_canonical
    for result in complete:
        if result.archetypes.research_priority is not None:
            continue
        reasons = _exclusion_reasons(result)
        reason_counts.update(reasons)
        blocked.append(
            {
                "ticker": result.ticker,
                "company_name": result.company_name,
                "security_id": (
                    result.source_security.security_id
                    if result.source_security is not None
                    else None
                ),
                "issuer_id": (
                    result.source_security.issuer_id if result.source_security is not None else None
                ),
                "status": "BLOCKED_BY_DIAMOND",
                "reasons": list(reasons),
                "diagnostics": list(result.diagnostics),
                "coverage": dict(result.coverage),
                "next_research_questions": [
                    "Which missing canonical observations are required for a rankable score?",
                    "Is the methodology supported without changing Diamond's contracts?",
                ],
            }
        )
    return dict(sorted(reason_counts.items())), blocked


def _feature_values(record: FundamentalRecord) -> dict[str, float | None]:
    feature_set = derive_financial_features(record)
    values = asdict(feature_set.features)
    values["share_dilution_3y"] = feature_set.metrics.share_dilution_3y
    values["normalized_fcf_yield"] = feature_set.metrics.normalized_fcf_yield
    return cast(dict[str, float | None], values)


def _relevant_features(result: DiamondResult) -> tuple[str, ...]:
    surfaced = result.archetypes.surfaced_by
    if surfaced is None:
        return ()
    output: list[str] = []
    for category in _ARCHETYPE_CATEGORIES[surfaced]:
        for feature in _CATEGORY_FEATURES[category]:
            if feature not in output:
                output.append(feature)
    if surfaced is Archetype.INFLECTION and "operating_margin_trend" not in output:
        output.append("operating_margin_trend")
    return tuple(output)


def _factor_rows(
    result: DiamondResult,
    feature_values: Mapping[str, float | None],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    surfaced = result.archetypes.surfaced_by
    if surfaced is None:
        raise OpportunityReportError("RANKED_RESULT_INVALID")
    present = [
        (name, float(percentile))
        for name in _relevant_features(result)
        if (percentile := result.percentiles.get(name)) is not None
    ]
    strongest = sorted(present, key=lambda item: (-item[1], item[0]))[:4]
    weakest = sorted(present, key=lambda item: (item[1], item[0]))[:3]
    determinants: list[dict[str, object]] = [
        {
            "feature": name,
            "value": feature_values.get(name),
            "peer_percentile": percentile,
            "interpretation": (
                f"{name} ranks at the {percentile:.1f} peer percentile within "
                f"the {surfaced.value} research path."
            ),
        }
        for name, percentile in strongest
    ]
    weaknesses: list[dict[str, object]] = [
        {
            "kind": "RELATIVE_WEAKNESS",
            "feature": name,
            "value": feature_values.get(name),
            "peer_percentile": percentile,
        }
        for name, percentile in weakest
    ]
    weaknesses.extend({"kind": "DIAGNOSTIC", "code": code} for code in result.diagnostics)
    return determinants, weaknesses


def _evidence_row(observation: FundamentalObservation) -> dict[str, object]:
    return {
        "evidence_id": (
            f"{observation.metric_id}:{observation.fiscal_slot.value}:"
            f"{observation.period_end.isoformat()}"
        ),
        "classification": "CHECKSUM_VERIFIED_STRUCTURED_OBSERVATION",
        "metric_id": observation.metric_id,
        "fiscal_slot": observation.fiscal_slot.value,
        "value": observation.value,
        "unit_kind": observation.unit_kind.value,
        "period_kind": observation.period_kind.value,
        "period_start": (
            observation.period_start.isoformat() if observation.period_start is not None else None
        ),
        "period_end": observation.period_end.isoformat(),
        "publication_date": None,
        "publication_date_status": "UNAVAILABLE_IN_CANONICAL_OBSERVATION",
        "source_provider": observation.source_provider,
        "source_identity": observation.source_identity,
        "share_class_id": observation.share_class_id,
        "adjustment_basis_id": observation.adjustment_basis_id,
    }


def _determinant_evidence(
    record: FundamentalRecord,
    determinant_features: tuple[str, ...],
) -> list[dict[str, object]]:
    metric_ids = {
        metric_id
        for feature in determinant_features
        for metric_id in _FEATURE_EVIDENCE_METRICS.get(feature, ())
    }
    observations = sorted(
        (item for item in record.observations if item.metric_id in metric_ids),
        key=lambda item: (
            item.metric_id,
            item.fiscal_slot.value,
            item.period_end,
        ),
    )
    return [_evidence_row(item) for item in observations]


def _sec_provenance(
    record: FundamentalRecord,
    manifests: Mapping[str, SecEvidenceManifest],
) -> dict[str, object]:
    prefix = "sec-cik:"
    cik = record.issuer_id.removeprefix(prefix) if record.issuer_id.startswith(prefix) else None
    manifest = manifests.get(cik) if cik is not None else None
    warning = (
        "Issuer-level SEC metadata is not an exact per-metric locator; the canonical "
        "observation does not retain its filing accession/publication date."
    )
    if manifest is None:
        return {
            "status": "MISSING",
            "scope": "ISSUER_LEVEL_ONLY",
            "cik": cik,
            "warning": warning,
        }
    return {
        "status": "AVAILABLE",
        "scope": "ISSUER_LEVEL_ONLY",
        "cik": manifest.cik,
        "request_identity": manifest.request_identity,
        "data_as_of": manifest.data_as_of.isoformat(),
        "retrieved_at": manifest.retrieved_at.isoformat(),
        "payload_sha256": manifest.payload_sha256,
        "evidence_revision_sha256": manifest.evidence_revision_sha256,
        "latest_in_scope_filing_date": (
            manifest.latest_in_scope_filing_date.isoformat()
            if manifest.latest_in_scope_filing_date is not None
            else None
        ),
        "latest_in_scope_accession": manifest.latest_in_scope_accession,
        "warning": warning,
    }


def _opportunity(
    result: DiamondResult,
    record: FundamentalRecord,
    *,
    rank: int,
    manifests: Mapping[str, SecEvidenceManifest],
) -> dict[str, object]:
    if result.source_security is None or result.archetypes.surfaced_by is None:
        raise OpportunityReportError("RANKED_RESULT_INVALID")
    feature_values = _feature_values(record)
    determinants, weaknesses = _factor_rows(result, feature_values)
    determinant_names = tuple(str(item["feature"]) for item in determinants)
    evidence = _determinant_evidence(record, determinant_names)
    missing_features = sorted(name for name, value in feature_values.items() if value is None)
    missing_coverage = sorted(
        f"{name}:{status}" for name, status in result.coverage.items() if status != "READY"
    )
    why = (
        f"Diamond rank {rank}; {result.archetypes.surfaced_by.value} produced the "
        f"highest research-path score ({result.archetypes.research_priority:.2f})."
    )
    assumptions = [
        "Peer percentiles and archetype scores are deterministic Diamond model outputs.",
        "The ranking routes research; it does not estimate intrinsic value or expected return.",
        "SEC Company Facts is structured screening evidence, not filing-native certification.",
    ]
    insufficient = [
        *[f"Derived feature unavailable: {name}" for name in missing_features],
        *[f"Coverage limitation: {item}" for item in missing_coverage],
        "Exact per-metric SEC filing accession and publication date are unavailable.",
    ]
    return {
        "rank": rank,
        "ticker": result.ticker,
        "company_name": result.company_name,
        "security_id": result.source_security.security_id,
        "issuer_id": result.source_security.issuer_id,
        "sector": result.sector,
        "status": "INVESTIGABLE",
        "why_selected": why,
        "financial_period": {
            "period_type": record.fundamental_period_type.value,
            "period_end": record.fundamental_period_end.isoformat(),
            "cutoff": record.data_as_of.isoformat(),
        },
        "diamond": {
            "methodology": result.methodology.value,
            "peer_scope": result.peer_scope,
            "peer_count": result.peer_count,
            "surfaced_by": result.archetypes.surfaced_by.value,
            "scores": {
                **asdict(result.scores),
                **asdict(result.archetypes),
            },
            "percentiles": dict(result.percentiles),
            "coverage": dict(result.coverage),
            "diagnostics": list(result.diagnostics),
        },
        "metrics": asdict(result.metrics),
        "determinant_factors": determinants,
        "risks_and_weaknesses": weaknesses,
        "evidence": evidence,
        "sec_provenance": _sec_provenance(record, manifests),
        "epistemic": {
            "verified_facts": [item["evidence_id"] for item in evidence],
            "derived_metrics": {
                "compressed_metrics": asdict(result.metrics),
                "analytical_features": feature_values,
                "peer_percentiles": dict(result.percentiles),
            },
            "inferences": [why],
            "assumptions": assumptions,
            "insufficient_data": insufficient,
        },
        "limitations": [
            *insufficient,
            *[f"Diagnostic: {item}" for item in result.diagnostics],
        ],
        "next_research_questions": [
            "Do filing-native statements confirm the determinant observations and periods?",
            "What business drivers explain the strongest and weakest peer percentiles?",
            "Are normalized cash flows durable across a full operating cycle?",
            "Which material risks are absent from structured Company Facts evidence?",
        ],
    }


def build_opportunity_report(
    funnel: FunnelRun,
    *,
    snapshot: DiamondSnapshotManifest,
    top: int,
    sec_manifests: tuple[SecEvidenceManifest, ...] = (),
) -> OpportunityReport:
    """Build an exact CandidateSet plus explainable research projections."""

    if isinstance(top, bool) or not isinstance(top, int) or top < 1:
        raise OpportunityReportError("TOP_INVALID")
    if snapshot.status is not SnapshotStatus.COMPLETE:
        raise OpportunityReportError("SNAPSHOT_NOT_COMPLETE")
    if snapshot.dataset_identity != funnel.metadata.dataset_identity:
        raise OpportunityReportError("SNAPSHOT_DATASET_MISMATCH")
    if snapshot.coverage is not None and (
        snapshot.coverage.universe_securities != funnel.metadata.universe_count
        or snapshot.coverage.canonical_records != funnel.metadata.canonical_records
        or snapshot.coverage.rankable_records != funnel.metadata.ranked_records
        or snapshot.coverage.unrankable_records != funnel.metadata.unranked_records
    ):
        raise OpportunityReportError("SNAPSHOT_COVERAGE_MISMATCH")
    if not funnel.records:
        raise OpportunityReportError("SOURCE_RECORDS_REQUIRED")

    rankable = _rankable_results(funnel)
    if not rankable:
        raise OpportunityReportError("NO_RANKABLE_CANDIDATES")
    ranked_ids = _ranked_security_ids(rankable)
    if snapshot.ranked_count != len(
        ranked_ids
    ) or snapshot.ranked_order_sha256 != sha256_canonical_json(list(ranked_ids)):
        raise OpportunityReportError("SNAPSHOT_RANKED_ORDER_MISMATCH")

    records_by_ticker = {record.ticker: record for record in funnel.records}
    if len(records_by_ticker) != len(funnel.records):
        raise OpportunityReportError("SOURCE_RECORD_IDENTITY_CONFLICT")
    manifests_by_cik = {manifest.cik: manifest for manifest in sec_manifests}
    if len(manifests_by_cik) != len(sec_manifests):
        raise OpportunityReportError("SEC_MANIFEST_IDENTITY_CONFLICT")
    for manifest in sec_manifests:
        if manifest.data_as_of != snapshot.cutoff or (
            manifest.latest_in_scope_filing_date is not None
            and manifest.latest_in_scope_filing_date > snapshot.cutoff
        ):
            raise OpportunityReportError("SEC_MANIFEST_CONTEXT_MISMATCH")

    selection_count = min(top, len(rankable))
    selection_funnel = replace(funnel, results=rankable)
    candidate_set = build_candidate_set(
        selection_funnel,
        snapshot=snapshot.as_ref(),
        universe_id=snapshot.universe_id,
        cutoff=snapshot.cutoff,
        policy=DiamondTopNPolicy(limit=selection_count),
    )
    candidate_set.require_production_reproducible()

    opportunities: list[dict[str, object]] = []
    for rank, result in enumerate(rankable[:selection_count], start=1):
        record = records_by_ticker.get(result.ticker)
        if record is None or record.data_as_of != snapshot.cutoff:
            raise OpportunityReportError("SOURCE_RECORD_CONTEXT_MISMATCH")
        if any(item.period_end > snapshot.cutoff for item in record.observations):
            raise OpportunityReportError("LOOK_AHEAD_EVIDENCE_DETECTED")
        opportunities.append(
            _opportunity(
                result,
                record,
                rank=rank,
                manifests=manifests_by_cik,
            )
        )

    reason_counts, blocked = _exclusions(funnel)
    selected_count = len(opportunities)
    document: dict[str, object] = {
        "schema_version": OPPORTUNITY_REPORT_SCHEMA_VERSION,
        "report_kind": "HISTORICAL_DIAMOND_RESEARCH_ROUTING",
        "historical": True,
        "integrity_status": "PARTIAL_POINT_IN_TIME",
        "universe_id": snapshot.universe_id,
        "cutoff": snapshot.cutoff.isoformat(),
        "dataset_identity": funnel.metadata.dataset_identity,
        "snapshot": {
            "snapshot_id": snapshot.snapshot_id,
            "status": snapshot.status.value,
            "file_count": len(snapshot.files),
            "ranked_order_sha256": snapshot.ranked_order_sha256,
            **({"coverage": asdict(snapshot.coverage)} if snapshot.coverage is not None else {}),
        },
        "summary": {
            "universe_count": funnel.metadata.universe_count,
            "canonical_count": funnel.metadata.canonical_records,
            "eligible_count": funnel.metadata.ranked_records,
            "excluded_count": (funnel.metadata.universe_count - funnel.metadata.ranked_records),
            "requested_count": top,
            "selected_count": selected_count,
            "selection_shortfall": max(top - selected_count, 0),
            "provider_requests": funnel.metadata.provider_requests,
            "cache_hits": funnel.metadata.cache_hits,
            "cache_misses": funnel.metadata.cache_misses,
        },
        "exclusions": {
            "counts_are_nonexclusive": True,
            "reason_counts": reason_counts,
        },
        "candidate_set": _candidate_set_dict(candidate_set),
        "opportunities": opportunities,
        "blocked_companies": blocked,
        "global_limitations": [
            "The cutoff is historical and must not be described as today's screen.",
            "The Wikipedia universe cache declares the cutoff but is not "
            "membership-effective-dated; historical index membership cannot be "
            "independently certified.",
            "Company Facts provenance is issuer-level structured evidence; exact per-value "
            "filing round trips are not available in this snapshot.",
            "A Diamond rank is a research priority, not a recommendation or valuation.",
        ],
        "disclaimer": NON_RECOMMENDATION,
    }
    return OpportunityReport(document)


def opportunity_report_json(report: OpportunityReport) -> str:
    return (
        json.dumps(
            report.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )


def _render_value(value: object) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def opportunity_report_markdown(report: OpportunityReport) -> str:
    payload = report.to_dict()
    summary = payload["summary"]
    exclusions = payload["exclusions"]
    lines = [
        "# Diamond Opportunities — historical research report",
        "",
        f"- Cutoff: `{payload['cutoff']}`",
        f"- Universe: `{payload['universe_id']}`",
        f"- Snapshot: `{payload['snapshot']['snapshot_id']}` (`COMPLETE`)",
        f"- Dataset: `{payload['dataset_identity']}`",
        f"- Universe / canonical / eligible / excluded: "
        f"{summary['universe_count']} / {summary['canonical_count']} / "
        f"{summary['eligible_count']} / {summary['excluded_count']}",
        f"- Selected: {summary['selected_count']} of {summary['requested_count']} requested",
        "",
        f"> {payload['disclaimer']}",
        "",
        "## Exclusions",
        "",
        "Counts are non-exclusive.",
        "",
        "| Reason | Count |",
        "|---|---:|",
    ]
    lines.extend(
        f"| `{reason}` | {count} |" for reason, count in exclusions["reason_counts"].items()
    )
    for candidate in payload["opportunities"]:
        lines.extend(
            [
                "",
                f"## {candidate['rank']}. {candidate['ticker']} — {candidate['company_name']}",
                "",
                f"**Why selected:** {candidate['why_selected']}",
                "",
                f"Financial period: `{candidate['financial_period']['period_type']}` ending "
                f"`{candidate['financial_period']['period_end']}`; cutoff "
                f"`{candidate['financial_period']['cutoff']}`.",
                "",
                "### Determinant factors",
                "",
                "| Feature | Value | Peer percentile |",
                "|---|---:|---:|",
            ]
        )
        lines.extend(
            f"| `{item['feature']}` | {_render_value(item['value'])} | "
            f"{_render_value(item['peer_percentile'])} |"
            for item in candidate["determinant_factors"]
        )
        lines.extend(["", "### Risks and weaknesses", ""])
        lines.extend(
            f"- `{item.get('feature', item.get('code'))}` — {item['kind']}"
            for item in candidate["risks_and_weaknesses"]
        )
        provenance = candidate["sec_provenance"]
        lines.extend(
            [
                "",
                "### Evidence and provenance",
                "",
                f"- SEC provenance: `{provenance['status']}` / `{provenance['scope']}`",
                f"- Latest in-scope accession: "
                f"`{_render_value(provenance.get('latest_in_scope_accession'))}`",
                f"- Latest in-scope filing date: "
                f"`{_render_value(provenance.get('latest_in_scope_filing_date'))}`",
                f"- Warning: {provenance['warning']}",
                "",
                "| Metric | Slot | Value | Period end | Source |",
                "|---|---|---:|---|---|",
            ]
        )
        lines.extend(
            f"| `{item['metric_id']}` | `{item['fiscal_slot']}` | "
            f"{_render_value(item['value'])} | `{item['period_end']}` | "
            f"`{item['source_provider']}` |"
            for item in candidate["evidence"]
        )
        lines.extend(["", "### What to research next", ""])
        lines.extend(f"- {item}" for item in candidate["next_research_questions"])
    lines.extend(["", "## Global limitations", ""])
    lines.extend(f"- {item}" for item in payload["global_limitations"])
    return "\n".join(lines) + "\n"


def focus_opportunity(
    report: OpportunityReport | Mapping[str, object],
    ticker: str,
) -> dict[str, Any]:
    payload = (
        report.to_dict() if isinstance(report, OpportunityReport) else copy.deepcopy(dict(report))
    )
    normalized = ticker.strip().upper()
    for key in ("opportunities", "blocked_companies"):
        items = payload.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict) and item.get("ticker") == normalized:
                focused = copy.deepcopy(item)
                focused["report_cutoff"] = payload.get("cutoff")
                focused["snapshot_id"] = cast(dict[str, object], payload["snapshot"])["snapshot_id"]
                focused["disclaimer"] = payload.get("disclaimer")
                return cast(dict[str, Any], focused)
    raise OpportunityReportError("OPPORTUNITY_NOT_FOUND")


__all__ = [
    "NON_RECOMMENDATION",
    "OPPORTUNITY_REPORT_SCHEMA_VERSION",
    "OpportunityReport",
    "OpportunityReportError",
    "build_opportunity_report",
    "focus_opportunity",
    "opportunity_report_json",
    "opportunity_report_markdown",
]
