# Cold-Ticker SEC Acquisition v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `qhapaq analyze TICKER` automatically acquire missing SEC evidence, use companyfacts first, repair only typed recoverable gaps with bounded filing-native XBRL evidence, and expose truthful terminal progress without changing financial formulas or stable JSON semantics.

**Architecture:** `AnalysisOrchestrator.plan()` stays offline. `analyze()` may execute one deterministic SEC fast-path phase and at most one gap-directed filing fallback phase. A typed canonical gate decides fallback; a filing-native bridge converts verified XBRL artifacts into existing `RawFact`/`SemanticEvidence` inputs; CLI progress is optional typed events rendered to stderr only for interactive human output.

**Tech Stack:** Python 3.10/3.12, existing Qhapaq SEC/accounting/canonicalization stack, stdlib XML parsing unless proven insufficient, pytest, Ruff, mypy.

**Specs:**
- `docs/superpowers/specs/2026-09-18-cold-ticker-sec-acquisition-v2-design.md`
- `docs/superpowers/specs/2026-09-18-cold-ticker-sec-acquisition-filing-native-addendum.md`

**Supersedes plan:** `docs/superpowers/plans/2026-09-18-cold-ticker-sec-acquisition.md`

## Global Constraints

- Preserve `docs/engineering/qhapaq-analysis-resolution-contract.md` exactly unless a real contradiction is discovered and reported.
- `plan()` is network-free.
- `UNSUPPORTED_TICKER` is resolution-only.
- Maximum one company-reference refresh stays unchanged.
- Fast path: at most one `submissions` fetch + one `companyfacts` fetch.
- Filing fallback: maximum one explicitly planned phase, no recursion.
- HTTP retries/backoff/rate limiting remain solely in `SecClient`.
- Do not use `AcquisitionAgent.select()` while SEC is the only permitted provider.
- No raw exception-string matching to decide fallback.
- No ticker-specific production branches.
- No new financial formulas or second canonical engine.
- Filing labels alone never authorize extension mappings.
- Stable `--json` output must remain clean and deterministic.
- Human progress goes to stderr only when interactive.
- Preserve unrelated `.env.example` and `data/cache/sec/company_tickers.json` changes; never stage them.

---

### Task 1: Typed SEC canonical gate

**Files:**
- Create: `src/qhapaq_finance/sec_canonical_gate.py`
- Create: `tests/test_sec_canonical_gate.py`
- Reuse: `src/qhapaq_finance/accounting.py`
- Reuse: `src/qhapaq_finance/financial_promotion.py`

**Interfaces:**
- `SecCanonicalGateState`: `READY`, `GAP`, `BLOCKED`.
- `SecCanonicalGapReason`: stable semantic reason enum.
- `SecCanonicalGateResult(state, reason, snapshot)`.
- Gate accepts already-validated source facts/evidence and calls existing accounting promotion/normalization; it performs no valuation and no HTTP.

- [ ] Write failing tests for READY, recoverable GAP, and BLOCKED.
- [ ] Run `uv run --no-sync pytest -q tests/test_sec_canonical_gate.py` and verify RED.
- [ ] Implement the smallest typed gate. Where current accounting helpers erase the cause, expose a structured internal failure type instead of parsing final exception strings.
- [ ] Verify `tests/test_sec_canonical_gate.py tests/test_accounting.py tests/test_financial_promotion.py` GREEN.
- [ ] Commit `feat(sec): add typed canonical evidence gate`.

Acceptance: market/beta/risk-free/ERP/cost-of-debt readiness cannot affect this gate.

---

### Task 2: Single-fetch fast path and prefetched submissions discovery

**Files:**
- Modify: `src/qhapaq_finance/sec_evidence_provider.py`
- Modify: `src/qhapaq_finance/sec_corpus.py`
- Test: `tests/test_evidence_orchestration.py`
- Test: `tests/test_sec_corpus.py`

**Interfaces:**
- Introduce a validated immutable submissions bundle containing payload, staged identity, and derived filing descriptors.
- Derive latest original 10-K/10-Q from the bundle without another request.
- Expose/refactor filing export helpers so they can operate from an explicit filing descriptor and do not refetch companyfacts/submissions.

- [ ] Write failing URL-recording tests proving exactly one submissions and one companyfacts fast-path fetch.
- [ ] Write failing test proving 10-K/10-Q discovery performs zero additional HTTP.
- [ ] Run focused tests and confirm RED.
- [ ] Implement reuse through existing `SecClient`, `stage_sec_response`, and validation functions.
- [ ] Run `tests/test_sec_corpus.py tests/test_evidence_orchestration.py tests/test_sec_acquisition.py tests/test_sec_client.py` GREEN.
- [ ] Commit `feat(sec): reuse submissions for acquisition discovery`.

Acceptance: no second HTTP client and no new retry owner.

---

### Task 3: Deterministic FilingFallbackPlan

**Files:**
- Create or modify a focused acquisition-planning module following current conventions; prefer `src/qhapaq_finance/sec_filing_plan.py` if no existing cohesive home exists.
- Test: `tests/test_sec_filing_plan.py`.

**Interfaces:**
- `FilingFallbackPlan`: immutable selected original filing descriptors and required artifact surface.
- `plan_filing_fallback(reason, submissions_bundle, requirement_context) -> FilingFallbackPlan`.

Mapping must be deterministic. Duration/TTM gaps may select the minimum annual/current/comparable filing set required by existing accounting temporal semantics. Instant/context gaps should not automatically download unrelated periods.

- [ ] Write failing table-driven tests for each supported reason class and exact selected accessions/forms.
- [ ] Prove same input produces same plan and no amendments are silently substituted for originals.
- [ ] Prove unsupported/non-repairable reasons produce no fallback plan.
- [ ] Implement minimal planner with no network access.
- [ ] Focused tests GREEN.
- [ ] Commit `feat(sec): plan bounded filing fallback`.

Acceptance: one plan may contain multiple explicit filings, but the orchestration phase occurs at most once.

---

### Task 4: Filing-native XBRL bridge

**Files:**
- Create: `src/qhapaq_finance/sec_filing_xbrl.py`
- Create: `tests/test_sec_filing_xbrl.py`
- Reuse/modify only where necessary: `src/qhapaq_finance/financial_canonicalization.py`
- Reuse: `src/qhapaq_finance/sec_corpus.py`

**Interfaces:**
- Parse verified local filing artifacts only; no HTTP.
- Produce existing `RawFact` values for filing-native facts.
- Produce existing `SemanticEvidence`/relationship structures for issuer extensions when structural evidence is sufficient.
- Expose one immutable result such as `FilingNativeEvidence(raw_facts, semantic_extensions, source_identities)`.

Required parsing behavior:
- resolve context start/end/instant and fiscal identity;
- resolve units/scales without guessing;
- preserve dimensions and consolidated status;
- bind accession/form/checksum lineage;
- parse XSD concept metadata and relevant presentation/calculation/label relationships;
- labels are supporting only;
- contradictory/incomplete relationships fail closed.

- [ ] Add compact frozen test fixtures representing: standard omitted fact, valid structural issuer extension, label-only extension, contradictory relationships, unit/context mismatch.
- [ ] Write failing tests proving standard filing-native evidence can repair a missing companyfacts observation.
- [ ] Write failing tests proving extension acceptance requires structural evidence and label-only mapping is rejected.
- [ ] Write failing tests for contradiction/context/unit/dimension failures.
- [ ] Implement using stdlib XML unless a dependency is demonstrably required; document any dependency decision.
- [ ] Run `tests/test_sec_filing_xbrl.py tests/test_financial_canonicalization.py` GREEN.
- [ ] Commit `feat(sec): parse verified filing native XBRL evidence`.

Acceptance: parser never calls network and never introduces an alternate canonical financial model.

---

### Task 5: Merge companyfacts + filing-native evidence into the canonical gate

**Files:**
- Modify: `src/qhapaq_finance/sec_canonical_gate.py`
- Modify: `src/qhapaq_finance/accounting.py` only through a generic evidence-input boundary if necessary.
- Test: `tests/test_sec_canonical_gate.py`
- Test: `tests/test_sec_filing_xbrl.py`

**Interfaces:**
- Fast path gate evaluates companyfacts-derived evidence.
- Post-fallback gate evaluates the union of companyfacts-derived facts plus verified filing-native `RawFact`/semantic evidence.
- Existing canonicalization decides conflicts; filing-native values do not override by source priority alone.

- [ ] Write failing test where companyfacts yields GAP and one verified filing-native standard fact changes result toward READY.
- [ ] Write failing extension repair test through `FinancialCanonicalizer` structural semantics.
- [ ] Write conflict test proving disagreement fails closed instead of picking a convenient value.
- [ ] Implement minimum merge/adaptation layer.
- [ ] Run accounting/canonicalization/gate tests GREEN.
- [ ] Commit `feat(sec): canonicalize filing fallback evidence`.

Acceptance: successful file download without successful parsing/canonicalization never becomes READY.

---

### Task 6: Wire bounded recovery into AnalysisOrchestrator

**Files:**
- Modify: `src/qhapaq_finance/analysis.py`
- Create optionally: `src/qhapaq_finance/analysis_progress.py` if it keeps the orchestrator focused.
- Modify: `tests/test_analysis.py`

**Interfaces:**
- Optional typed progress observer.
- One explicit fast-path phase.
- One gate evaluation.
- At most one fallback plan/execution.
- One post-fallback gate evaluation.
- Then continue through the existing market/capital-cost/reverse-DCF path.

- [ ] Add failing contract tests: local sufficient=0 acquisition; cold valid=fast path; fast READY=0 fallback; GAP=1 fallback; still GAP=`EVIDENCE_REQUIRED`; infra/integrity=`BLOCKED`; downstream market gap=0 additional fallback; unsupported remains resolution-only; `plan()`=0 network.
- [ ] Add event-order test for fallback path.
- [ ] Run focused tests RED.
- [ ] Implement without recursive `analyze()` calls.
- [ ] Run `tests/test_analysis.py tests/test_company_resolver.py tests/test_acquisition_agent.py` GREEN.
- [ ] Commit `feat(analysis): recover cold SEC evidence`.

Acceptance: acquisition never manufactures `UNSUPPORTED_TICKER`.

---

### Task 7: Terminal UX for acquisition

**Files:**
- Modify: `src/qhapaq_finance/cli.py`
- Modify: `src/qhapaq_finance/analysis_render.py`
- Modify: `tests/test_analysis.py`
- Modify: `tests/test_analysis_render.py`

**Interfaces:**
- CLI maps typed progress events to concise stderr lines only for human TTY mode.
- `--json` and non-TTY suppress progress.
- Final renderer shows acquisition summary using structured result/stage state only.

- [ ] Add failing tests: TTY progress in stderr, final report in stdout; JSON stderr empty and canonical stdout exact; non-TTY stderr empty; `--plain` ASCII.
- [ ] Add renderer tests: fast path/fallback acquisition summary; detail may show typed fallback reason; acquisition-attempted `EVIDENCE_REQUIRED` must not tell user to acquire evidence again; BLOCKED gives SEC-acquisition-oriented next action without raw exception.
- [ ] Implement without spinner dependency, fabricated percentages, or timing data.
- [ ] Run presentation tests GREEN.
- [ ] Commit `feat(cli): expose SEC acquisition progress`.

Acceptance: renderer remains pure and JSON stays machine-clean.

---

### Task 8: Full verification and delivery

- [ ] Run sentinel outputs:

```bash
uv run qhapaq analyze QCOM
uv run qhapaq analyze QCOM --detail --plain
uv run qhapaq analyze JPM --plain
uv run qhapaq analyze JPM --json
```

QCOM must remain zero-acquisition and completed. JPM final state must be truthful; it need not be COMPLETED if downstream market/capital-cost evidence remains unavailable.

- [ ] Run full gates:

```bash
python3 scripts/check_publication.py
uv lock --check
uv run --no-sync ruff format --check .
uv run --no-sync ruff check .
uv run --no-sync mypy --no-incremental src
uv run --no-sync pytest
git diff --check
```

- [ ] Inspect final diff/status for ticker hardcoding, duplicated HTTP, recursive retries, raw exception decision logic, weakened tests, JSON drift, debug artifacts, `.env.example`, and SEC cache staging.
- [ ] If and only if GREEN, push `feat/cold-ticker-sec-acquisition`. Do not merge `main`.

Final report:

```text
STATUS
WHAT CHANGED
TESTS / GATES
QCOM OBSERVED RESULT
JPM OBSERVED RESULT
ACQUISITION BOUNDS
FILING-NATIVE BRIDGE RESULT
UX / JSON CONTRACT
REMAINING BLOCKERS
SHA
```
