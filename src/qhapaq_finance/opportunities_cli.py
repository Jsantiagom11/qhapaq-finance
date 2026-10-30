"""Offline CLI composition for sealed Diamond opportunity reports."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Protocol, cast

from qhapaq_finance.sec_client import SecClientError

from .candidate_set import (
    Candidate,
    CandidateSet,
    CandidateSetError,
    DiamondSnapshotRef,
    DiamondTopNPolicy,
    SnapshotStatus,
)
from .diamond.cache import DiamondCacheError
from .diamond.canonical_json import sha256_canonical_json
from .diamond.cli import _iso_date, _production_funnel_provider
from .diamond.contracts import FundamentalRecord, SecurityRef
from .diamond.funnel import FunnelRun, run_funnel
from .diamond.providers.sec import SecFirstProviderError
from .diamond.providers.sec_evidence import SecEvidenceError, SecEvidenceManifest
from .diamond.providers.sp500 import Sp500ProviderError
from .diamond.providers.yahoo import YahooProviderError
from .diamond.snapshot import (
    MANIFEST_NAME,
    DiamondSnapshotError,
    DiamondSnapshotManifest,
    finalize_snapshot,
    load_complete_snapshot,
    stage_snapshot,
)
from .opportunities import (
    OPPORTUNITY_REPORT_SCHEMA_VERSION,
    OpportunityReportError,
    build_opportunity_report,
    focus_opportunity,
    opportunity_report_json,
    opportunity_report_markdown,
)


class OpportunityCommandError(RuntimeError):
    """The offline command could not satisfy its integrity contract."""


class _AuditedProvider(Protocol):
    provider_requests: int
    cache_hits: int
    cache_misses: int
    read_paths: tuple[Path, ...]
    resolved_manifests: tuple[SecEvidenceManifest, ...]

    def universe(self, universe_id: str, as_of: date) -> tuple[SecurityRef, ...]: ...

    def fundamentals(
        self,
        securities: tuple[SecurityRef, ...],
        as_of: date,
        history_years: int = 5,
    ) -> tuple[FundamentalRecord, ...]: ...


def _atomic_write(target: Path, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _ranked_security_ids(run: FunnelRun) -> tuple[str, ...]:
    identifiers: list[str] = []
    for result in run.evaluated_results or run.results:
        if result.archetypes.research_priority is None:
            continue
        if result.source_security is None:
            raise OpportunityCommandError("SOURCE_SECURITY_REQUIRED")
        identifiers.append(result.source_security.security_id)
    return tuple(identifiers)


def _require_offline_run(run: FunnelRun) -> None:
    if run.metadata.provider_requests != 0:
        raise OpportunityCommandError("OFFLINE_PROVIDER_REQUEST_DETECTED")
    if run.metadata.cache_misses != 0:
        raise OpportunityCommandError("OFFLINE_CACHE_MISS")


def _run_offline(
    cache_root: Path,
    *,
    universe_id: str,
    cutoff: date,
) -> tuple[_AuditedProvider, FunnelRun]:
    provider = cast(
        _AuditedProvider,
        _production_funnel_provider(
            cache_root,
            refresh=False,
            offline=True,
        ),
    )
    run = run_funnel(
        provider,
        universe_id=universe_id,
        as_of=cutoff,
        depth=10_000,
    )
    _require_offline_run(run)
    return provider, run


def _verify_replay(
    run: FunnelRun,
    manifest: DiamondSnapshotManifest,
) -> None:
    ranked_ids = _ranked_security_ids(run)
    if run.metadata.dataset_identity != manifest.dataset_identity:
        raise OpportunityCommandError("SNAPSHOT_REPLAY_MISMATCH")
    if len(ranked_ids) != manifest.ranked_count:
        raise OpportunityCommandError("SNAPSHOT_REPLAY_MISMATCH")
    if sha256_canonical_json(list(ranked_ids)) != manifest.ranked_order_sha256:
        raise OpportunityCommandError("SNAPSHOT_REPLAY_MISMATCH")


def _load_or_seal(
    *,
    source_cache_root: Path,
    snapshot_root: Path,
    universe_id: str,
    cutoff: date,
) -> tuple[DiamondSnapshotManifest, _AuditedProvider, FunnelRun]:
    manifest_path = snapshot_root / MANIFEST_NAME
    if manifest_path.exists():
        manifest = load_complete_snapshot(
            snapshot_root,
            universe_id=universe_id,
            cutoff=cutoff,
        )
        replay_provider, replay = _run_offline(
            manifest.cache_root,
            universe_id=universe_id,
            cutoff=cutoff,
        )
        _verify_replay(replay, manifest)
        return manifest, replay_provider, replay

    source_provider, source_run = _run_offline(
        source_cache_root,
        universe_id=universe_id,
        cutoff=cutoff,
    )
    source_ranked_ids = _ranked_security_ids(source_run)
    staged = stage_snapshot(
        source_root=source_cache_root,
        snapshot_root=snapshot_root,
        selected_paths=source_provider.read_paths,
        universe_id=universe_id,
        cutoff=cutoff,
        dataset_identity=source_run.metadata.dataset_identity,
        ranked_security_ids=source_ranked_ids,
    )
    replay_provider, replay = _run_offline(
        staged.cache_root,
        universe_id=universe_id,
        cutoff=cutoff,
    )
    if replay.metadata.dataset_identity != source_run.metadata.dataset_identity:
        raise OpportunityCommandError("SNAPSHOT_REPLAY_MISMATCH")
    manifest = finalize_snapshot(
        staged,
        replay=replay,
    )
    return manifest, replay_provider, replay


_COMMAND_ERRORS = (
    DiamondCacheError,
    DiamondSnapshotError,
    OpportunityCommandError,
    OpportunityReportError,
    SecClientError,
    SecEvidenceError,
    SecFirstProviderError,
    Sp500ProviderError,
    YahooProviderError,
)


def run_opportunities(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(
        description="Build a sealed historical Diamond opportunity report offline"
    )
    parser.add_argument("--as-of", type=_iso_date, required=True)
    parser.add_argument("--universe", choices=("sp500",), default="sp500")
    parser.add_argument("--cache-root", type=Path, default=Path("data/cache/diamond"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args(arguments)
    if args.top < 1:
        parser.error("--top must be positive")

    output = args.output.resolve()
    source_cache_root = args.cache_root.resolve()
    if output.is_relative_to(source_cache_root) or source_cache_root.is_relative_to(output):
        parser.error("--output and --cache-root must not overlap")
    try:
        manifest, provider, replay = _load_or_seal(
            source_cache_root=source_cache_root,
            snapshot_root=output / "snapshot",
            universe_id=args.universe,
            cutoff=args.as_of,
        )
        report = build_opportunity_report(
            replay,
            snapshot=manifest,
            top=args.top,
            sec_manifests=provider.resolved_manifests,
        )
        json_path = output / "opportunities.json"
        json_checksum_path = output / "opportunities.json.sha256"
        markdown_path = output / "opportunities.md"
        json_document = opportunity_report_json(report)
        _atomic_write(json_path, json_document)
        _atomic_write(
            json_checksum_path,
            f"{hashlib.sha256(json_document.encode()).hexdigest()}  {json_path.name}\n",
        )
        _atomic_write(markdown_path, opportunity_report_markdown(report))
    except _COMMAND_ERRORS as exc:
        parser.error(str(exc))

    payload = report.to_dict()
    print("status=COMPLETE")
    print(f"cutoff={payload['cutoff']}")
    print(f"selected={payload['summary']['selected_count']}")
    print(f"snapshot={manifest.root / MANIFEST_NAME}")
    print(f"json={json_path}")
    print(f"json_sha256={json_checksum_path}")
    print(f"markdown={markdown_path}")


def _validated_candidate_set(
    payload: Mapping[str, object],
    manifest: DiamondSnapshotManifest,
) -> CandidateSet:
    try:
        raw = payload["candidate_set"]
        if not isinstance(raw, dict):
            raise OpportunityCommandError("OPPORTUNITY_REPORT_INVALID")
        raw_snapshot = raw["snapshot"]
        raw_policy = raw["policy"]
        raw_candidates = raw["candidates"]
        if (
            not isinstance(raw_snapshot, dict)
            or not isinstance(raw_policy, dict)
            or not isinstance(raw_candidates, list)
            or raw_policy.get("kind") != "DIAMOND_TOP_N"
        ):
            raise OpportunityCommandError("OPPORTUNITY_REPORT_INVALID")
        candidate_set = CandidateSet(
            snapshot=DiamondSnapshotRef(
                snapshot_id=str(raw_snapshot["snapshot_id"]),
                dataset_identity=str(raw_snapshot["dataset_identity"]),
                universe_id=str(raw_snapshot["universe_id"]),
                cutoff=date.fromisoformat(str(raw_snapshot["cutoff"])),
                status=SnapshotStatus(str(raw_snapshot["status"])),
            ),
            policy=DiamondTopNPolicy(limit=int(raw_policy["limit"])),
            candidates=tuple(
                Candidate(
                    security=SecurityRef(
                        ticker=str(item["security"]["ticker"]),
                        security_id=str(item["security"]["security_id"]),
                        issuer_id=str(item["security"]["issuer_id"]),
                    ),
                    diamond_rank=int(item["diamond_rank"]),
                    selection_order=int(item["selection_order"]),
                )
                for item in raw_candidates
                if isinstance(item, dict) and isinstance(item.get("security"), dict)
            ),
        )
        if len(candidate_set.candidates) != len(raw_candidates):
            raise OpportunityCommandError("OPPORTUNITY_REPORT_INVALID")
        candidate_set.require_production_reproducible()
        if raw.get("candidate_set_id") != candidate_set.candidate_set_id:
            raise OpportunityCommandError("OPPORTUNITY_REPORT_CANDIDATE_SET_MISMATCH")
    except (KeyError, TypeError, ValueError, CandidateSetError) as exc:
        raise OpportunityCommandError("OPPORTUNITY_REPORT_INVALID") from exc
    if (
        candidate_set.snapshot.snapshot_id != manifest.snapshot_id
        or candidate_set.dataset_identity != manifest.dataset_identity
        or candidate_set.universe_id != manifest.universe_id
        or candidate_set.cutoff != manifest.cutoff
    ):
        raise OpportunityCommandError("OPPORTUNITY_REPORT_SNAPSHOT_MISMATCH")
    opportunities = payload.get("opportunities")
    if not isinstance(opportunities, list) or len(opportunities) != len(candidate_set.candidates):
        raise OpportunityCommandError("OPPORTUNITY_REPORT_CANDIDATE_SET_MISMATCH")
    for candidate, opportunity in zip(
        candidate_set.candidates,
        opportunities,
        strict=True,
    ):
        if not isinstance(opportunity, dict) or (
            opportunity.get("rank") != candidate.diamond_rank
            or opportunity.get("ticker") != candidate.security.ticker
            or opportunity.get("security_id") != candidate.security.security_id
            or opportunity.get("issuer_id") != candidate.security.issuer_id
        ):
            raise OpportunityCommandError("OPPORTUNITY_REPORT_CANDIDATE_SET_MISMATCH")
    return candidate_set


def _load_report(path: Path) -> dict[str, object]:
    try:
        encoded = path.read_bytes()
        checksum_line = Path(f"{path}.sha256").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpportunityCommandError("OPPORTUNITY_REPORT_UNREADABLE") from exc
    checksum_parts = checksum_line.split()
    if (
        len(checksum_parts) != 2
        or checksum_parts[1] != path.name
        or checksum_parts[0] != hashlib.sha256(encoded).hexdigest()
    ):
        raise OpportunityCommandError("OPPORTUNITY_REPORT_CHECKSUM_MISMATCH")
    try:
        payload = json.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpportunityCommandError("OPPORTUNITY_REPORT_INVALID") from exc
    if not isinstance(payload, dict):
        raise OpportunityCommandError("OPPORTUNITY_REPORT_INVALID")
    if payload.get("schema_version") != OPPORTUNITY_REPORT_SCHEMA_VERSION:
        raise OpportunityCommandError("OPPORTUNITY_REPORT_SCHEMA_UNSUPPORTED")
    try:
        manifest = load_complete_snapshot(path.parent / "snapshot")
    except DiamondSnapshotError as exc:
        raise OpportunityCommandError("OPPORTUNITY_REPORT_SNAPSHOT_INVALID") from exc
    snapshot = payload.get("snapshot")
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("snapshot_id") != manifest.snapshot_id
        or payload.get("dataset_identity") != manifest.dataset_identity
        or payload.get("universe_id") != manifest.universe_id
        or payload.get("cutoff") != manifest.cutoff.isoformat()
    ):
        raise OpportunityCommandError("OPPORTUNITY_REPORT_SNAPSHOT_MISMATCH")
    _validated_candidate_set(payload, manifest)
    return payload


def _focused_markdown(focused: Mapping[str, object]) -> str:
    ticker = focused.get("ticker")
    company = focused.get("company_name")
    lines = [
        f"# {ticker} — {company}",
        "",
        f"Status: `{focused.get('status')}`",
        f"Report cutoff: `{focused.get('report_cutoff')}`",
        "",
    ]
    why = focused.get("why_selected")
    if isinstance(why, str):
        lines.extend(["## Why selected", "", why, ""])
    else:
        reasons = focused.get("reasons")
        lines.extend(
            [
                "## Why blocked",
                "",
                *([f"- `{item}`" for item in reasons] if isinstance(reasons, list) else []),
                "",
            ]
        )
    factors = focused.get("determinant_factors")
    if isinstance(factors, list):
        lines.extend(["## Determinant factors", ""])
        lines.extend(
            f"- `{item.get('feature')}`: value={item.get('value')}, "
            f"peer_percentile={item.get('peer_percentile')}"
            for item in factors
            if isinstance(item, dict)
        )
        lines.append("")
    risks = focused.get("risks_and_weaknesses")
    if isinstance(risks, list):
        lines.extend(["## Risks and weaknesses", ""])
        lines.extend(
            f"- `{item.get('feature', item.get('code'))}` — {item.get('kind')}"
            for item in risks
            if isinstance(item, dict)
        )
        lines.append("")
    provenance = focused.get("sec_provenance")
    if isinstance(provenance, dict):
        lines.extend(
            [
                "## Evidence provenance",
                "",
                f"- Scope: `{provenance.get('scope')}`",
                f"- CIK: `{provenance.get('cik')}`",
                f"- Latest in-scope filing date: `{provenance.get('latest_in_scope_filing_date')}`",
                f"- Latest in-scope accession: `{provenance.get('latest_in_scope_accession')}`",
                f"- Evidence revision: `{provenance.get('evidence_revision_sha256')}`",
                f"- Limitation: {provenance.get('warning')}",
                "",
            ]
        )
    evidence = focused.get("evidence")
    if isinstance(evidence, list):
        lines.extend(["## Evidence observations", ""])
        lines.extend(
            f"- `{item.get('metric_id')}` / `{item.get('fiscal_slot')}`: "
            f"value={item.get('value')} {item.get('unit_kind')}, "
            f"period_end={item.get('period_end')}, "
            f"publication_date={item.get('publication_date_status')}, "
            f"source={item.get('source_provider')}"
            for item in evidence
            if isinstance(item, dict)
        )
        lines.append("")
    epistemic = focused.get("epistemic")
    if isinstance(epistemic, dict):
        verified = epistemic.get("verified_facts")
        derived = epistemic.get("derived_metrics")
        inferences = epistemic.get("inferences")
        assumptions = epistemic.get("assumptions")
        insufficient = epistemic.get("insufficient_data")
        lines.extend(
            [
                "## Epistemic status",
                "",
                "### Verified facts",
                "",
                f"- {len(verified) if isinstance(verified, list) else 0} structured "
                "observations are linked above.",
                "",
                "### Derived metrics",
                "",
                *(
                    [f"- `{name}`" for name in sorted(derived)]
                    if isinstance(derived, dict)
                    else ["- unavailable"]
                ),
                "",
                "### Inference",
                "",
                *(
                    [f"- {item}" for item in inferences]
                    if isinstance(inferences, list)
                    else ["- none"]
                ),
                "",
                "### Assumptions",
                "",
                *(
                    [f"- {item}" for item in assumptions]
                    if isinstance(assumptions, list)
                    else ["- none"]
                ),
                "",
                "### Insufficient data",
                "",
                *(
                    [f"- {item}" for item in insufficient]
                    if isinstance(insufficient, list)
                    else ["- none identified"]
                ),
                "",
            ]
        )
    questions = focused.get("next_research_questions")
    if isinstance(questions, list):
        lines.extend(["## What to research next", ""])
        lines.extend(f"- {item}" for item in questions)
        lines.append("")
    lines.append(f"> {focused.get('disclaimer')}")
    return "\n".join(lines) + "\n"


def run_opportunity(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(
        description="Inspect one candidate or blocked company from a stored report"
    )
    parser.add_argument("ticker")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(arguments)
    try:
        focused = focus_opportunity(_load_report(args.report), args.ticker)
    except (OpportunityCommandError, OpportunityReportError) as exc:
        parser.error(str(exc))
    if args.json:
        print(
            json.dumps(
                focused,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n",
            end="",
        )
    else:
        print(_focused_markdown(focused), end="")


__all__ = ["run_opportunities", "run_opportunity"]
