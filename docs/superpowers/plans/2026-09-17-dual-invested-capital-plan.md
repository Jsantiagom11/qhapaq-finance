# Dual Invested Capital Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace generic bottom-up-only invested capital with a fail-closed primary financing identity and endpoint-local reconciliation audit.

**Architecture:** Promotion owns canonical mutually exclusive source choices. Accounting owns Pydantic component contracts, identity arithmetic, reconciliation, and compatibility `.average`. Generic analysis only consumes the resulting public contract and records stable reasons.

**Tech Stack:** Python 3.10+, Pydantic v2 (the one permitted added dependency), pytest, Ruff, mypy, uv.

**Spec:** `docs/superpowers/specs/2026-09-17-dual-invested-capital-design.md`

## Global Constraints

- Write and observe a failing behavior test before every production behavior change.
- Missing, unmapped, or consolidated facts never become `0.0`.
- No ticker branches, no SEC acquisition changes, and no new dependency.
- Do not stage, commit, reset, clean, or modify unrelated worktree changes.

---

### Task 1: Component contracts and reconciliation

**Files:**
- Modify: `src/qhapaq_finance/accounting.py`
- Test: `tests/test_accounting.py`

**Consumes:** endpoint component values with source provenance.

**Produces:** `DataState`, `ICMethod`, `ReconciliationStatus`, `ICComponent`,
`ICNode`, `ICReconciliation`, and compatible `InvestedCapitalPair`.

- [ ] **Step 1: Write failing tests** for reported zero, missing-not-zero,
  top-down arithmetic, bottom-up incomplete status, both reconciliation
  thresholds, zero-primary handling, independent endpoint status, and `.average`
  blocking only a material gap.
- [ ] **Step 2: Run tests to verify RED**

  Run: `UV_CACHE_DIR=/tmp/qhapaq-finance-uv-cache uv run --no-sync pytest tests/test_accounting.py -q`

  Expected: FAIL because dual engine types and constructors do not exist.

- [ ] **Step 3: Write minimal implementation** with Pydantic v2 models, state
  validation, explicit primary requirements, and reconciliation helper.
- [ ] **Step 4: Run the focused tests to verify GREEN.**

### Task 2: Canonical endpoint policy and promotion

**Files:**
- Modify: `src/qhapaq_finance/financial_promotion.py`
- Modify: `src/qhapaq_finance/accounting.py`
- Test: `tests/test_financial_promotion.py`, `tests/test_accounting.py`

**Consumes:** local SEC raw facts and the revenue-derived balance-sheet dates.

**Produces:** primary and audit component evidence for each endpoint with one
authorized debt, securities, and lease representation.

- [ ] **Step 1: Write failing tests** proving aliases cannot double count,
  primary missing components fail closed, a missing intangible leaves the
  bottom-up node `None`, and non-current operating liabilities are subtracted.
- [ ] **Step 2: Run tests to verify RED.**
- [ ] **Step 3: Implement policy groups and endpoint promotion**, carrying each
  fact's source IDs into component provenance and mapping unavailable facts to
  `MISSING_OR_CONSOLIDATED` without creating artificial values.
- [ ] **Step 4: Run promotion and accounting focused tests to verify GREEN.**

### Task 3: Generic integration and regressions

**Files:**
- Modify: `src/qhapaq_finance/analysis.py`
- Modify only if required for compatibility: `src/qhapaq_finance/qcom_case.py`, `src/qhapaq_finance/nvda_case.py`
- Test: `tests/test_accounting.py`, `tests/test_analysis.py`, existing QCOM/NVDA tests

**Consumes:** `InvestedCapitalPair.average` and its reconciliation statuses.

**Produces:** AAPL completion with stated financing-identity regression values
and machine-readable internal reasons for primary/reconciliation failure.

- [ ] **Step 1: Write failing frozen-corpus tests** for AAPL’s two top-down
  endpoints and average, incomplete AAPL opening bottom-up, and completed generic
  analysis when the other pre-existing gates are valid.
- [ ] **Step 2: Run tests to verify RED.**
- [ ] **Step 3: Make minimal adapter and analysis changes**, preserving existing
  external `AnalysisStatus` behavior and QCOM/NVDA numeric outputs.
- [ ] **Step 4: Run focused AAPL, QCOM, and NVDA tests to verify GREEN.**

### Task 4: Full verification

- [ ] Run `UV_CACHE_DIR=/tmp/qhapaq-finance-uv-cache uv lock --check`.
- [ ] Run `UV_CACHE_DIR=/tmp/qhapaq-finance-uv-cache uv run --no-sync ruff check .`.
- [ ] Run `UV_CACHE_DIR=/tmp/qhapaq-finance-uv-cache uv run --no-sync mypy src`.
- [ ] Run `UV_CACHE_DIR=/tmp/qhapaq-finance-uv-cache uv run --no-sync pytest -q`.
- [ ] Run `git diff --check` and the required status/diff reports.
