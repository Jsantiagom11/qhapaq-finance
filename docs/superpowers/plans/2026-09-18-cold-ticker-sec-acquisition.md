# Cold-Ticker SEC Acquisition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `qhapaq analyze TICKER` automatically acquire missing SEC evidence through a bounded companyfacts-first path, fall back to filing-native evidence only for typed recoverable canonical gaps, and expose truthful terminal progress without changing finance or stable JSON semantics.

**Architecture:** Keep `AnalysisOrchestrator.plan()` offline. `analyze()` owns the request-level acquisition decision; `SecClient` remains the sole HTTP/retry/rate-limit owner. Introduce a typed SEC canonical gate and deterministic filing-fallback plan, reuse one prefetched submissions payload, and expose progress through an optional typed observer rendered by the CLI to stderr only in interactive human mode.

**Tech Stack:** Python 3.10/3.12, dataclasses/enums, existing SEC client/provider/corpus/accounting stack, argparse CLI, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-09-18-cold-ticker-sec-acquisition-v2-design.md`

## Global Constraints

- `AnalysisOrchestrator.plan()` remains network-free.
- `UNSUPPORTED_TICKER` remains exclusively authoritative-resolution-owned.
- Maximum one authoritative company-reference refresh per request remains unchanged.
- SEC evidence acquisition is separate from company-reference refresh.
- Fast path performs at most one companyfacts fetch and one submissions fetch per request.
- Maximum one filing-native fallback phase per request.
- No raw-exception substring matching to choose fallback.
- No ticker-specific production branches.
- No financial formula, `AnalysisResult` schema, or stable `--json` contract change unless an existing internal stage field can carry the state without schema expansion.
- All SEC HTTP uses `SecClient`; HTTP retry/backoff stays there.
- Human progress uses stderr only when interactive; JSON/non-TTY stays clean.
- Preserve unrelated local `.env.example` and SEC cache changes.

---

### Task 1: Typed SEC canonical gate

**Files:**
- Create: `src/qhapaq_finance/sec_canonical_gate.py`
- Create: `tests/test_sec_canonical_gate.py`
- Reuse: `src/qhapaq_finance/accounting.py`
- Reuse: `src/qhapaq_finance/financial_promotion.py`
- Reuse: `src/qhapaq_finance/financial_canonicalization.py`

**Interfaces:**
- Produce `SecCanonicalGateState(str, Enum)` with `READY`, `GAP`, `BLOCKED`.
- Produce `SecCanonicalGapReason(str, Enum)` with stable semantic reasons needed by tests: `MISSING_STANDARD_CONCEPT`, `STANDARD_CONCEPT_COVERAGE_GAP`, `REQUIRED_COMPONENT_MISSING`, `PERIOD_COVERAGE_GAP`, `AMBIGUOUS_CONTEXT`, `EXTENSION_DISCOVERY_REQUIRED`, `FILING_CONTEXT_REQUIRED`.
- Produce immutable `SecCanonicalGateResult(state, reason, snapshot)` where `snapshot` is `AccountingSnapshot | None`.
- Produce `evaluate_companyfacts_gate(companyfacts: Mapping[str, object], *, source_identity: str) -> SecCanonicalGateResult`.
- The function must reuse existing `extract_company_facts`, `MultiPeriodFinancialPromoter`, `accounting_evidence_policies`, `accounting_evidence_spec_from_promoted_facts`, and `normalize_accounting_snapshot`; it must not calculate valuation.

- [ ] **Step 1: Write failing unit tests for READY/GAP/BLOCKED classification**

Use minimal fixtures or existing companyfacts fixture fragments. Prove:

```python
result = evaluate_companyfacts_gate(valid_companyfacts, source_identity="fixture")
assert result.state is SecCanonicalGateState.READY
assert result.snapshot is not None
```

and prove a missing canonical concept is a typed GAP, while malformed identity/value structure is BLOCKED.

- [ ] **Step 2: Run focused test and confirm RED**

Run:

```bash
uv run --no-sync pytest -q tests/test_sec_canonical_gate.py
```

Expected: import/function failures.

- [ ] **Step 3: Implement the smallest typed gate**

Catch only known canonical/promotion/accounting exception classes at this boundary. Map structural/integrity contradictions to `BLOCKED`; map coverage/representation insufficiency to stable GAP reason enums. Do not parse exception message substrings as the final decision mechanism: introduce explicit helper branches close to the failing canonical requirement when needed.

- [ ] **Step 4: Verify focused tests GREEN**

```bash
uv run --no-sync pytest -q tests/test_sec_canonical_gate.py tests/test_accounting.py tests/test_financial_promotion.py
```

- [ ] **Step 5: Commit**

```bash
git add src/qhapaq_finance/sec_canonical_gate.py tests/test_sec_canonical_gate.py
git commit -m "feat(sec): add typed canonical evidence gate"
```

---

### Task 2: Single-fetch SEC fast path and deterministic filing fallback plan

**Files:**
- Modify: `src/qhapaq_finance/sec_evidence_provider.py`
- Modify: `src/qhapaq_finance/sec_corpus.py`
- Create or modify: `tests/test_sec_evidence_provider.py` if present; otherwise add provider tests to `tests/test_evidence_orchestration.py`
- Modify: `tests/test_sec_corpus.py`

**Interfaces:**
- Add an immutable typed representation for validated submissions discovery, e.g. `SecSubmissionsBundle(payload, staged, filings)`.
- Add provider operation that fetches submissions once and derives latest original 10-K/10-Q metadata from that payload without another HTTP call.
- Add immutable `FilingFallbackPlan` containing the selected filing descriptors/artifact requests for one fallback phase.
- Add `plan_filing_fallback(reason: SecCanonicalGapReason, submissions: SecSubmissionsBundle) -> FilingFallbackPlan`.
- Refactor SEC corpus filing export so fallback can consume prefetched submissions/companyfacts records rather than refetching them.

- [ ] **Step 1: Write failing tests proving exactly two fast-path HTTP calls**

Use a fake `SecClient`/transport recording URLs. Acquisition of companyfacts plus submissions plus derived 10-K/10-Q metadata must record exactly:

```text
.../api/xbrl/companyfacts/CIK##########.json
.../submissions/CIK##########.json
```

No third submissions fetch.

- [ ] **Step 2: Write failing tests for deterministic fallback planning**

For the same typed gap reason and submissions payload, `plan_filing_fallback()` must be byte/structurally deterministic, exclude amendments unless an existing policy explicitly requires them, and select only the bounded relevant filing set.

- [ ] **Step 3: Run focused tests and confirm RED**

```bash
uv run --no-sync pytest -q tests/test_sec_corpus.py tests/test_evidence_orchestration.py
```

- [ ] **Step 4: Implement provider reuse and prefetched corpus/fallback helpers**

Keep URL construction and payload validation in the existing SEC provider/corpus modules. Do not add another HTTP client. Reuse existing `_export_filing`/staging primitives for filing artifacts.

- [ ] **Step 5: Verify focused tests GREEN**

```bash
uv run --no-sync pytest -q tests/test_sec_corpus.py tests/test_evidence_orchestration.py tests/test_sec_acquisition.py tests/test_sec_client.py
```

- [ ] **Step 6: Commit**

```bash
git add src/qhapaq_finance/sec_evidence_provider.py src/qhapaq_finance/sec_corpus.py tests/test_sec_corpus.py tests/test_evidence_orchestration.py
git commit -m "feat(sec): reuse submissions for bounded filing discovery"
```

---

### Task 3: Wire cold acquisition into AnalysisOrchestrator

**Files:**
- Modify: `src/qhapaq_finance/analysis.py`
- Modify: `src/qhapaq_finance/acquisition_agent.py` only if a small deterministic planner capability is missing; do not route through `AcquisitionAgent.select()`.
- Modify: `tests/test_analysis.py`

**Interfaces:**
- Add optional progress observer parameter to `AnalysisOrchestrator.__init__`, e.g. `progress: Callable[[AnalysisProgressEvent], None] | None = None`.
- Add typed internal progress event enum/dataclass in `analysis.py` or a focused `analysis_progress.py` module if keeping `analysis.py` smaller.
- Add one internal method for bounded SEC recovery after `_plan_resolved()` returns acquisition-eligible `EVIDENCE_REQUIRED`.
- The method executes fast path once, evaluates the gate, optionally executes one fallback plan, re-evaluates once, then re-enters the existing downstream planning/analysis path.
- Existing local evidence path must remain zero-network.

- [ ] **Step 1: Add failing orchestration contract tests**

Cover:

```text
local sufficient -> acquisition calls == 0
cold valid -> fast path == 1 phase
fast READY -> fallback == 0
recoverable GAP -> fallback == 1
still GAP after successful fallback -> EVIDENCE_REQUIRED
network/integrity failure -> BLOCKED
market/capital-cost gap -> fallback remains 0
unsupported ticker -> same authoritative resolution behavior
plan() -> network calls == 0
```

Use fakes/fixtures; no live SEC.

- [ ] **Step 2: Add failing event-order test**

Expected event subsequence for fallback path:

```text
FAST_PATH_ACQUISITION_STARTED
FAST_PATH_ACQUISITION_COMPLETED
CANONICAL_GATE_GAP
FILING_FALLBACK_STARTED
FILING_FALLBACK_COMPLETED
CANONICALIZATION_COMPLETED
```

- [ ] **Step 3: Run focused tests and confirm RED**

```bash
uv run --no-sync pytest -q tests/test_analysis.py
```

- [ ] **Step 4: Implement bounded acquisition wiring**

Preserve the resolution contract before acquisition. Do not turn acquisition failures into `UNSUPPORTED_TICKER`. Do not loop by recursively calling `analyze()`; use explicit bounded phases and then one downstream continuation.

- [ ] **Step 5: Verify orchestration and resolution tests GREEN**

```bash
uv run --no-sync pytest -q tests/test_analysis.py tests/test_company_resolver.py tests/test_acquisition_agent.py
```

- [ ] **Step 6: Commit**

```bash
git add src/qhapaq_finance/analysis.py src/qhapaq_finance/analysis_progress.py tests/test_analysis.py
git commit -m "feat(analysis): acquire cold SEC evidence deterministically"
```

If `analysis_progress.py` is not created, omit it from staging.

---

### Task 4: Add non-invasive CLI progress and truthful acquisition UX

**Files:**
- Modify: `src/qhapaq_finance/cli.py`
- Modify: `src/qhapaq_finance/analysis_render.py`
- Modify: `tests/test_analysis.py`
- Modify: `tests/test_analysis_render.py`

**Interfaces:**
- CLI progress adapter consumes typed analysis progress events and writes concise lines to stderr.
- Progress adapter is enabled only for human TTY mode; disabled for `--json` and non-TTY.
- Renderer derives final acquisition summary solely from `AnalysisResult` stage state/reason; no I/O.

- [ ] **Step 1: Add failing CLI channel tests**

Prove:

```python
# interactive human
assert "Acquiring" in captured.err
assert captured.out.startswith("QHAPAQ")

# json
assert captured.err == ""
json.loads(captured.out)

# non-TTY
assert captured.err == ""
```

- [ ] **Step 2: Add failing renderer copy tests**

When acquisition was attempted successfully but canonical evidence remains insufficient, output must not say `Acquire and verify the missing SEC evidence.`. It must say acquisition was attempted/completed and show a meaningful remaining next action.

For a successful fallback-completed analysis, executive evidence should identify `SEC ACQUISITION` as `Filing fallback`; `--detail` may show the typed reason.

- [ ] **Step 3: Run focused tests and confirm RED**

```bash
uv run --no-sync pytest -q tests/test_analysis.py tests/test_analysis_render.py
```

- [ ] **Step 4: Implement progress adapter and final report copy**

No spinner dependency. No timing/progress percentages. Keep `--plain` ASCII. Keep `NO_COLOR` and width behavior unchanged.

- [ ] **Step 5: Verify UX/JSON regression tests GREEN**

```bash
uv run --no-sync pytest -q tests/test_analysis.py tests/test_analysis_render.py
```

- [ ] **Step 6: Commit**

```bash
git add src/qhapaq_finance/cli.py src/qhapaq_finance/analysis_render.py tests/test_analysis.py tests/test_analysis_render.py
git commit -m "feat(cli): show bounded SEC acquisition progress"
```

---

### Task 5: End-to-end regression and delivery

**Files:**
- Modify docs only if implementation behavior differs from the approved spec; do not silently change the contract.

- [ ] **Step 1: Run sentinel behavior**

```bash
uv run qhapaq analyze QCOM
uv run qhapaq analyze QCOM --detail --plain
uv run qhapaq analyze JPM --plain
uv run qhapaq analyze JPM --json
```

For deterministic local acceptance, QCOM must remain completed and zero-acquisition. JPM may terminate `COMPLETED`, `EVIDENCE_REQUIRED`, or `BLOCKED` depending on available non-SEC evidence/config, but must not stop solely because `automatic acquisition is disabled` when acquisition is configured and reachable.

- [ ] **Step 2: Run all quality gates**

```bash
python3 scripts/check_publication.py
uv lock --check
uv run --no-sync ruff format --check .
uv run --no-sync ruff check .
uv run --no-sync mypy --no-incremental src
uv run --no-sync pytest
git diff --check
```

- [ ] **Step 3: Inspect scope and contracts**

```bash
git status --short
git diff --stat main...HEAD
git diff main...HEAD -- src/qhapaq_finance tests docs/superpowers
```

Reject ticker hardcoding, second HTTP clients, recursive retry loops, raw exception-string decision logic, JSON changes, or unrelated local files.

- [ ] **Step 4: Push only on GREEN**

```bash
git push origin feat/cold-ticker-sec-acquisition
```

Do not merge `main` in this task. Final report must include STATUS, WHAT CHANGED, TESTS/GATES, observed QCOM/JPM results, acquisition bounds, JSON contract check, remaining blockers, and SHA.
