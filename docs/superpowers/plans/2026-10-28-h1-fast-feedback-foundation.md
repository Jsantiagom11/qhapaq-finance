# H1.1 Fast Feedback Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a deterministic FAST pytest cohort whose p95 is below 10 seconds without changing production behavior or full collection.

**Architecture:** Keep selection native to pytest. Register the five test layers centrally, classify pure modules locally, and enforce FAST isolation from pytest configuration through session teardown with a Python audit hook.

**Tech Stack:** Python 3.10+, pytest, uv, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-10-28-h1-fast-feedback-foundation-design.md`

## Global Constraints

- Do not modify production code, financial contracts, JSON contracts, CI, or the original five worktrees.
- Do not use wrappers, textual `-k` filters, skips, or automatic changed-file selection.
- Keep the complete pytest collection identical by node ID.
- Deliver one commit containing only H1.1.

## Review Focus

- A FAST test attempts socket creation: it must fail rather than reach a network or local service.
- A test carries both FAST and an environment marker: collection may succeed, but execution must fail explicitly.
- Module-level parametrization: every generated case must remain selected by FAST.
- Full collection: markers must not add, remove, rename, or skip node IDs.
- Python 3.10 and 3.12: collection must remain compatible when both runtimes are available.

---

### Task 1: Explicit FAST cohort and isolation

**Files:**
- Modify: `pyproject.toml`
- Modify: `tests/conftest.py`
- Modify: `tests/finance/test_accounting_primitives.py`
- Modify: `tests/finance/test_temporal.py`
- Modify: `tests/finance/test_valuation_contracts.py`
- Modify: `tests/test_diamond_scoring.py`
- Modify: `tests/test_diamond_metrics.py`
- Modify: `tests/test_diamond_percentiles.py`
- Modify: `tests/test_diamond_serialization.py`
- Modify: `tests/test_diamond_dataset_identity.py`
- Modify: `tests/test_diamond_canonical_json.py`
- Modify: `tests/executive/test_contracts.py`
- Modify: `tests/executive/test_goal_seek.py`

**Interfaces:**
- Consumes: existing pytest marker selection and existing deterministic tests.
- Produces: registered marker names, 122 FAST cases, and session-lifetime socket/environment isolation for FAST.

- [ ] **Step 1: Record RED**

Run: `uv run --no-sync pytest -q -p no:cacheprovider -m fast`
Expected: exit 5 because no tests are selected.

- [ ] **Step 2: Register markers and add FAST isolation**

Register all five marker names in `pyproject.toml`. Add a Python audit hook in `tests/conftest.py` that denies socket events for the exact FAST lane from configuration through teardown. Reject incompatible environment markers during collection.

- [ ] **Step 3: Mark the approved pure modules**

Add the module-level `pytestmark = pytest.mark.fast` declaration to each listed test module. Do not alter test bodies or expected values.

- [ ] **Step 4: Verify GREEN and deterministic performance**

Run FAST ten times, require 122 passed, zero skipped, and calculate p50/p95 from wall-clock samples. Expected: all exit 0 and p95 below 10 seconds.

- [ ] **Step 5: Verify collection and compatibility**

Compare sorted full node IDs before/after and require exact equality. Collect under Python 3.10 and 3.12 environments when available.

- [ ] **Step 6: Run repository quality gates and commit**

Run Ruff format/check, mypy, focused FAST, and full collection. Review status/diff, then create one H1.1-only commit.
