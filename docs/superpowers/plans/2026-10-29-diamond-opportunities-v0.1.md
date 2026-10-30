# Diamond Opportunities v0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a deterministic offline historical Diamond opportunity report backed by a sealed COMPLETE snapshot and exact CandidateSet.

**Architecture:** Add strict offline cache reads and selected-file auditing, seal those reads into a copied immutable snapshot, replay Diamond from that snapshot, then project the exact Top N plus source observations into JSON/Markdown and focused inspection. Existing ranking, financial and valuation logic remains unchanged.

**Tech Stack:** Python 3.10+, frozen dataclasses, argparse, existing Diamond/CandidateSet contracts, JSON/Markdown, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-10-29-diamond-opportunities-v0.1-design.md`

## Global Constraints

- Required explicit historical cutoff; no `date.today()` in the new path.
- Zero network access and zero source-cache mutation.
- No scoring, percentile, archetype, valuation or canonical-data changes.
- Missing evidence remains missing and blocks completeness where required.
- COMPLETE is written only after selected-file verification and successful replay.
- No new dependency, push or merge.

## Review Focus

- Stale exact-cutoff SEC evidence in offline mode must replay; a cutoff mismatch must fail without network.
- A cache miss hidden by an optional market/split path must still prevent COMPLETE.
- Snapshot identity must be independent of absolute source/output paths and detect one-byte mutation.
- Fewer than ten rankable companies must produce a shorter honest CandidateSet, not padding.
- Issuer-level accession metadata must never be represented as an exact per-metric filing locator.

---

### Task 1: Strict offline evidence reads and audit

**Files:**
- Modify: `src/qhapaq_finance/diamond/cache.py`
- Modify: `src/qhapaq_finance/diamond/providers/sec_evidence.py`
- Modify: `src/qhapaq_finance/diamond/cli.py`
- Test: `tests/test_diamond_live_funnel_slice.py`
- Test: `tests/test_diamond_sec_evidence.py`
- Test: `tests/test_diamond_cli.py`

**Interfaces:**
- Produces: `DiamondCache.read_paths: tuple[Path, ...]` containing only successful
  loads; `SecEvidenceStore(..., offline=True)` with `read_paths` and
  `resolved_manifests`; provider-level `read_paths` aggregation; and
  `_production_funnel_provider(..., offline=True)` with no live clients.

- [ ] Write tests proving stale exact-cutoff offline replay, explicit offline miss, read-path audit and offline provider wiring.
- [ ] Run the tests and confirm RED for missing offline/audit behavior.
- [ ] Implement the minimal offline and audit boundaries without changing online behavior.
- [ ] Run focused tests and confirm GREEN.
- [ ] Commit the task.

### Task 2: Snapshot sealing and verification

**Files:**
- Create: `src/qhapaq_finance/diamond/snapshot.py`
- Create: `tests/test_diamond_snapshot.py`

**Interfaces:**
- Consumes: selected absolute read paths, cache root, run metadata, universe and cutoff.
- Produces: frozen `SnapshotFile`, `StagedDiamondSnapshot` and
  `DiamondSnapshotManifest`; `stage_snapshot(...)` copies and hashes the selected
  inventory without claiming completeness; `finalize_snapshot(...)` atomically writes
  the first `COMPLETE` manifest only after replay equivalence; and
  `load_complete_snapshot(...)` verifies context and every byte. Snapshot identity is a
  canonical hash that excludes absolute paths.

- [ ] Write tests for finalization-last, path-independent identity, exact copied inventory, immutable COMPLETE reuse, context mismatch and one-byte tamper rejection.
- [ ] Run the tests and confirm RED because the module is absent.
- [ ] Implement atomic copied-file sealing and deterministic manifest verification.
- [ ] Run focused tests and confirm GREEN.
- [ ] Commit the task.

### Task 3: Evidence-aware opportunity report

**Files:**
- Modify: `src/qhapaq_finance/diamond/funnel.py`
- Create: `src/qhapaq_finance/opportunities.py`
- Create: `tests/test_opportunities.py`

**Interfaces:**
- Consumes: replayed `FunnelRun.records: tuple[FundamentalRecord, ...]`, verified
  `DiamondSnapshotManifest` and requested Top N.
- Produces: `build_opportunity_report(...)`, `opportunity_report_json(...)`,
  `opportunity_report_markdown(...)` and `focus_opportunity(...)`; the report embeds the
  exact CandidateSet, non-exclusive exclusion summary and explicit epistemic buckets.

- [ ] Write tests for exact order/identity, no artificial fill, exclusion reasons, epistemic separation, determinant evidence, issuer-level provenance labeling and deterministic serialization.
- [ ] Run the tests and confirm RED for the missing report boundary.
- [ ] Preserve source records in `FunnelRun` and implement the minimal report projection.
- [ ] Run focused tests and confirm GREEN.
- [ ] Commit the task.

### Task 4: User commands and vertical integration

**Files:**
- Modify: `src/qhapaq_finance/cli.py`
- Create: `src/qhapaq_finance/opportunities_cli.py`
- Create: `tests/test_opportunities_cli.py`

**Interfaces:**
- Produces: `run_opportunities(args)` for seal/replay/report orchestration,
  `run_opportunity(args)` for artifact-only focused projection, and public commands
  `qhapaq opportunities ...` / `qhapaq opportunity TICKER --report ...`.

- [ ] Write CLI tests for first seal/replay/report, existing snapshot replay, focused inspection, invalid ticker and no-analysis/no-network boundaries.
- [ ] Run the tests and confirm RED because commands are absent.
- [ ] Implement the command composition and atomic artifact writes.
- [ ] Run focused and CLI integration tests and confirm GREEN.
- [ ] Commit the task.

### Task 5: Real historical acceptance and reproducibility

**Files:**
- Create: `docs/governance/DIAMOND_OPPORTUNITIES_V0_1.md`
- Generate ignored artifacts under: `output/diamond-opportunities-2026-09-22/`

**Interfaces:**
- Consumes: protected Debt Zero cache at the explicit 2026-09-22 cutoff.
- Produces: sealed snapshot, JSON/Markdown report, focused candidate output and verification record.

- [ ] Run the real command and require zero requests/misses, a valid COMPLETE manifest and a real unpadded Top 10 when available.
- [ ] Run it again into a second report location and prove byte-identical JSON/Markdown plus identical identities/order.
- [ ] Run focused regressions, Ruff, mypy and the full suite.
- [ ] Record commands, hashes, counts, timings, limitations and artifact paths.
- [ ] Review the final diff and commit the task.

