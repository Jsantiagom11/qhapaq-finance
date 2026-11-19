# Cold-Ticker SEC Acquisition v2 — Design

## Purpose

Make `qhapaq analyze TICKER` recover from a cold local SEC state without manual fixture preparation, while preserving fail-closed finance, bounded network behavior, deterministic state transitions, and clean terminal UX.

This supersedes `2026-09-18-cold-ticker-sec-acquisition-design.md` for implementation intent.

## Product contract

`AnalysisOrchestrator.plan()` remains offline-only.

`AnalysisOrchestrator.analyze()` remains offline-first and may acquire SEC evidence only after authoritative company resolution has succeeded and the local evidence plan shows an acquisition-eligible SEC gap.

`UNSUPPORTED_TICKER` remains owned exclusively by authoritative ticker resolution.

## Acquisition strategy

The increment uses deterministic acquisition only. Do not use `AcquisitionAgent` as a selector when SEC is the single permitted provider.

Fast path per request:

1. Fetch `submissions` exactly once.
2. Fetch `companyfacts` exactly once.
3. Stage decoded entity bodies immutably.
4. Validate source identity/checksum and promote them into the trusted local SEC path used by canonical accounting.
5. Derive latest 10-K/10-Q discovery metadata locally from the already-fetched submissions payload; do not refetch submissions to derive metadata.
6. Evaluate the SEC canonical gate.

All SEC HTTP remains behind `SecClient`; no worker queue, distributed limiter, or second retry owner is introduced.

## SEC canonical gate

The filing fallback is controlled by a dedicated canonical SEC gate. It MUST NOT be triggered by `model_requirements.model_ready`, `data_quality_score`, missing market evidence, or missing capital-cost evidence.

The gate returns one of three typed states:

- `READY`
- `GAP`
- `BLOCKED`

Suggested internal shape:

```text
SecCanonicalGateResult
  state: READY | GAP | BLOCKED
  reason: SecCanonicalReason | None
  snapshot: AccountingSnapshot | None
```

`READY` requires the company-facts surface to support the existing generic accounting contract, including compatible canonical evidence for revenue/TTM anchoring, EBIT, D&A, capex, working-capital endpoints, effective-tax inputs, invested-capital endpoints, cash, marketable securities, debt, and valuation shares. Existing unit, period, sign, endpoint, finite-value, and ambiguity checks remain authoritative.

`GAP` is only for a condition plausibly repairable by filing-native evidence. Stable typed reasons may include:

- `MISSING_STANDARD_CONCEPT`
- `STANDARD_CONCEPT_COVERAGE_GAP`
- `REQUIRED_COMPONENT_MISSING`
- `PERIOD_COVERAGE_GAP`
- `AMBIGUOUS_CONTEXT`
- `EXTENSION_DISCOVERY_REQUIRED`
- `FILING_CONTEXT_REQUIRED`

`EXTENSION_DISCOVERY_REQUIRED` means filing-level evidence is needed; it does not claim a custom extension exists before that evidence is inspected.

`BLOCKED` covers acquisition/integrity/invariant failures that another filing should not attempt to repair, including malformed SEC payloads, source-identity mismatch, checksum/integrity failure, immutable staging conflict, contradictory metadata, network/config failures, and canonical invariant contradictions.

No fallback decision may depend on substring matching raw exception messages.

## Filing fallback

A `GAP` may cause exactly one filing-native fallback phase.

Introduce a deterministic `FilingFallbackPlan` derived from the typed gap reason and already-fetched submissions metadata. The plan selects the minimum bounded filing set necessary to repair the gap; it is not equivalent to blindly downloading every 10-K and 10-Q.

The permitted artifact surface is the existing SEC corpus surface: selected primary filing documents plus relevant XBRL/XML/XSD resources and `FilingSummary.xml` when available.

After fallback, verify/promote the acquired filing evidence and re-evaluate canonicalization exactly once.

- READY after fallback -> continue downstream.
- Still a legitimate coverage gap after successful fallback -> `EVIDENCE_REQUIRED`.
- Acquisition/integrity/invariant failure -> `BLOCKED`.

No recursive fallback or orchestration retry loop is allowed. HTTP retries remain owned by `SecClient`.

## State mapping

```text
local evidence sufficient
  -> zero acquisition

authoritative ticker negative
  -> UNSUPPORTED_TICKER

SEC network/config/staging/integrity failure
  -> BLOCKED

fast-path SEC canonical READY
  -> downstream market/capital-cost/reverse-DCF path

fast-path SEC canonical GAP
  -> one filing fallback phase

fallback READY
  -> downstream path

fallback succeeds but remains canonically insufficient
  -> EVIDENCE_REQUIRED

market/capital-cost gap after SEC READY
  -> existing downstream semantics
  -> never another SEC filing fallback
```

## User experience

Acquisition creates latency, so interactive human mode must expose truthful progress without contaminating machine output.

### Progress channel

Progress is emitted as typed orchestration events and rendered only by the CLI.

The domain/orchestrator never prints directly. Suggested event kinds:

- `RESOLUTION_STARTED`
- `FAST_PATH_ACQUISITION_STARTED`
- `FAST_PATH_ACQUISITION_COMPLETED`
- `CANONICAL_GATE_READY`
- `CANONICAL_GATE_GAP`
- `FILING_FALLBACK_STARTED`
- `FILING_FALLBACK_COMPLETED`
- `CANONICALIZATION_COMPLETED`

Rules:

- human TTY -> concise progress to `stderr`;
- `--plain` human TTY -> same semantic progress, ASCII only;
- `--json` -> no progress;
- non-TTY / redirected stdout -> no progress;
- no percentages, spinners with fabricated completion, or unstable timing data.

Example interactive sequence:

```text
Resolving JPM...
SEC  Acquiring company facts + submissions
SEC  Canonicalizing evidence
SEC  Filing fallback · PERIOD_COVERAGE_GAP
SEC  Verifying filing evidence
```

### Final report

The final renderer remains a pure `AnalysisResult` projection. It may summarize acquisition truth already carried by the plan/stages, but must not perform I/O or canonicalization.

Executive evidence examples:

```text
EVIDENCE
SEC ACQUISITION       Fast path
CANONICAL EVIDENCE    Verified
```

or

```text
EVIDENCE
SEC ACQUISITION       Filing fallback
CANONICAL EVIDENCE    Verified
```

Detailed mode may additionally show the typed fallback reason and attempted filing set. Raw implementation keys remain in `--json`, not in the human analyst view.

When bounded acquisition ran successfully but evidence remains insufficient, the old instruction `Acquire and verify the missing SEC evidence.` must not be shown. The report should state that acquisition was attempted and identify the remaining canonical gap.

When acquisition is operationally blocked, the human report should identify the blocking stage as SEC acquisition and give a concise retry-oriented next action without exposing raw exceptions.

## Implementation boundaries

Reuse, do not replace:

- `SecClient` for User-Agent, <=10 RPS configuration, process-wide pacing, Retry-After, and retries;
- `StructuredSecProvider` for typed SEC payload validation/staging;
- `DeterministicAcquisitionPlanner` / `BoundedAcquisitionRunner` where their contracts fit;
- `stage_sec_response` and immutable acquisition metadata;
- existing accounting promotion/normalization rules;
- existing SEC corpus filing artifact acquisition helpers;
- existing progressive CLI renderer and stable canonical JSON serializer.

Targeted refactoring is allowed where necessary to prevent duplicate `submissions` HTTP calls or to expose reusable filing acquisition from prefetched submissions. Do not build a parallel downloader or a second financial engine.

## Testing contract

Use TDD. Required behavior tests:

1. local evidence sufficient -> zero SEC acquisition calls;
2. cold valid ticker -> fast path fetches companyfacts once and submissions once;
3. 10-K/10-Q discovery reuses prefetched submissions;
4. fast-path gate READY -> no filing fallback;
5. typed recoverable GAP -> exactly one fallback phase;
6. fallback plan is deterministic and bounded by reason code;
7. fallback READY -> downstream analysis continues;
8. successful fallback but remaining gap -> `EVIDENCE_REQUIRED`;
9. malformed/integrity/staging/network/config failure -> `BLOCKED`;
10. market/capital-cost gap never triggers filing fallback;
11. unsupported ticker remains resolution-only;
12. no path performs more than one fallback phase;
13. `plan()` remains network-free;
14. all HTTP continues through `SecClient`;
15. no ticker-specific production branches;
16. human TTY emits progress only to stderr;
17. `--json` stdout remains byte/semantic-equivalent to canonical serialization and emits no progress;
18. non-TTY suppresses progress;
19. final human EVIDENCE_REQUIRED copy reflects whether acquisition was actually attempted;
20. QCOM/NVDA/AAPL and resolution-contract regressions remain green.

JPM cold-path tests must use fixtures/fakes in CI. Live SEC network is observable acceptance, not a deterministic test dependency.

## Completion boundary

The increment is complete when a resolved cold ticker can execute bounded SEC acquisition, companyfacts-first canonical gating, one gap-directed filing fallback when required, truthful state mapping, and non-invasive terminal progress; all repository gates are green and no acquisition/presentation behavior leaks into financial calculations or stable JSON semantics.
