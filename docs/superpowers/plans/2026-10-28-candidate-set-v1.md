# CandidateSet v1 Implementation Plan

**Execution status (2026-10-29):** implemented in commit
`afa8257fcdb6fd80c5a78752b8da90b2cb771b8b`. The checklist below is preserved as
the original implementation plan, not used as a mutable execution ledger. Current
verification and remaining conditions are recorded in
[`docs/governance/H2_RECONCILIATION_AND_REUSE.md`](../../governance/H2_RECONCILIATION_AND_REUSE.md).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic, typed and fail-closed CandidateSet v1 boundary over authoritative Diamond Top-N results.

**Architecture:** Keep CandidateSet outside the Diamond engine. Consume `FunnelRun` without sorting, bind it to a minimal snapshot reference, preserve exact `SecurityRef` values, and compute a separately versioned canonical identity. Permit incomplete local sets but gate production reproducibility on `SnapshotStatus.COMPLETE`.

**Tech Stack:** Python 3.10+, frozen dataclasses, pytest, existing Diamond canonical JSON, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-10-28-candidate-set-v1-design.md`

## Global Constraints

- Do not modify production financial behavior, Diamond scoring/ranking, public Diamond serialization, dataset identity v2, caches, ResearchDossier, UI or Executive.
- Do not infer or manufacture `SecurityRef` values or snapshot completeness.
- Do not sort, filter around, or replace an unrankable selected result.
- Keep all original worktrees unchanged and deliver one H2-only commit.

## Review Focus

- A selected result lacks or conflicts with its `SecurityRef`: fail closed, never use ticker alone.
- Snapshot dataset, universe or cutoff conflicts with the funnel context: reject before creating a set.
- One selected result is unrankable: reject rather than silently shortening or filling the selection.
- Multiple securities share a ticker: preserve both exact identities and Diamond order.
- An incomplete snapshot is otherwise valid: build the inspectable set but reject production reproducibility.

---

### Task 1: CandidateSet contract and Diamond composition

**Files:**
- Create: `src/qhapaq_finance/candidate_set.py`
- Create: `tests/test_candidate_set.py`
- Create: `tests/test_candidate_set_integration.py`
- Create: `docs/superpowers/specs/2026-10-28-candidate-set-v1-design.md`
- Create: `docs/superpowers/plans/2026-10-28-candidate-set-v1.md`

**Interfaces:**
- Consumes: `SecurityRef`, `FunnelRun`, its existing authoritative result order, dataset identity, and the shared canonical JSON hasher.
- Produces: `SnapshotStatus`, `DiamondSnapshotRef`, `DiamondTopNPolicy`, `Candidate`, `CandidateSet`, `build_candidate_set()`, `candidate_set_identity()` and the production reproducibility gate.

- [ ] **Step 1: Write the FAST contract tests**

Cover literal expected ranks/order, deterministic identity, identity sensitivity, context mismatch, absent/conflicting identity, duplicate identity, ticker ambiguity, unrankable results, policy bounds and incomplete-snapshot gating.

- [ ] **Step 2: Run the contract tests and verify RED**

Run: `uv run --no-sync pytest -q -p no:cacheprovider tests/test_candidate_set.py`
Expected: collection error because `qhapaq_finance.candidate_set` does not exist.

- [ ] **Step 3: Implement the minimal immutable contract**

Create the public types and `build_candidate_set(funnel: FunnelRun, *, snapshot: DiamondSnapshotRef, universe_id: str, cutoff: date, policy: DiamondTopNPolicy) -> CandidateSet`. Reuse `sha256_canonical_json`; do not modify Diamond.

- [ ] **Step 4: Run FAST contract tests and verify GREEN**

Run: `uv run --no-sync pytest -q -p no:cacheprovider tests/test_candidate_set.py`
Expected: all tests pass with zero skips.

- [ ] **Step 5: Add the RED→GREEN frozen integration test**

Compose `LocalJsonProvider` and `run_funnel` with an explicitly `INCOMPLETE` synthetic snapshot reference. Assert exact Top-3 identities/ranks, dataset binding and the closed production gate. Run it first before adding any missing integration behavior; it should pass without production expansion because Task 1 already supplies the boundary.

- [ ] **Step 6: Verify repository gates and invariants**

Run CandidateSet tests, relevant Diamond dataset/serialization tests, INTEGRATION, ten FAST iterations with p50/p95, Ruff format/check, mypy, full collection comparison and FULL outside the restricted asyncio sandbox. Confirm the original worktree fingerprints remain unchanged.

- [ ] **Step 7: Review and commit once**

Inspect status and full diff, obtain whole-branch review, resolve Critical/Important findings through RED→GREEN if any, rerun gates, and create one commit containing only H2 CandidateSet v1.
