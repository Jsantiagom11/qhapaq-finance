"""Offline CLI composition for sealed Diamond opportunity reports."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Protocol, cast

from qhapaq_finance.sec_client import SecClientError

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
    replay_ranked_ids = _ranked_security_ids(replay)
    if replay.metadata.dataset_identity != source_run.metadata.dataset_identity:
        raise OpportunityCommandError("SNAPSHOT_REPLAY_MISMATCH")
    manifest = finalize_snapshot(
        staged,
        replay_dataset_identity=replay.metadata.dataset_identity,
        replay_ranked_security_ids=replay_ranked_ids,
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
        markdown_path = output / "opportunities.md"
        _atomic_write(json_path, opportunity_report_json(report))
        _atomic_write(markdown_path, opportunity_report_markdown(report))
    except _COMMAND_ERRORS as exc:
        parser.error(str(exc))

    payload = report.to_dict()
    print("status=COMPLETE")
    print(f"cutoff={payload['cutoff']}")
    print(f"selected={payload['summary']['selected_count']}")
    print(f"snapshot={manifest.root / MANIFEST_NAME}")
    print(f"json={json_path}")
    print(f"markdown={markdown_path}")


def _load_report(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpportunityCommandError("OPPORTUNITY_REPORT_UNREADABLE") from exc
    if not isinstance(payload, dict):
        raise OpportunityCommandError("OPPORTUNITY_REPORT_INVALID")
    if payload.get("schema_version") != OPPORTUNITY_REPORT_SCHEMA_VERSION:
        raise OpportunityCommandError("OPPORTUNITY_REPORT_SCHEMA_UNSUPPORTED")
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
                *(
                    [f"- `{item}`" for item in reasons]
                    if isinstance(reasons, list)
                    else []
                ),
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
