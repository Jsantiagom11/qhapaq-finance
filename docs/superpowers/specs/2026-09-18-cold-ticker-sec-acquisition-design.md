# Cold-Ticker SEC Acquisition — Design

## Purpose

Enable `qhapaq analyze TICKER` to recover from a cold local SEC evidence state by performing bounded, auditable SEC acquisition and then re-entering the existing canonical analysis pipeline.

This increment does not redesign the financial engine. It wires existing acquisition, staging, SEC provider, canonicalization, and analysis boundaries together so a valid ticker can move from `EVIDENCE_REQUIRED` toward a truthful terminal state without manual fixture preparation.

## Scope

In scope:

- automatic SEC acquisition for already-resolved companies when required SEC evidence is missing or stale;
- `submissions` and `companyfacts` as the fast path;
- one deterministic canonical-quality gate after fast-path acquisition;
- one bounded filing-native fallback when the fast path has a recoverable SEC canonical gap;
- re-canonicalization after fallback;
- deterministic mapping to `COMPLETED`, `EVIDENCE_REQUIRED`, or `BLOCKED`;
- reuse of the existing `SecClient`, `StructuredSecProvider`, staging, acquisition planner/runner, and canonicalization contracts.

Out of scope:

- distributed rate limiting or worker queues;
- changing ticker-resolution semantics;
- changing financial formulas, valuation semantics, or `AnalysisResult` schema;
- changing CLI presentation or JSON contracts;
- hardcoded ticker-specific production logic;
- broad filing scraping;
- unrestricted retries or orchestration loops;
- portfolio analysis.

## Existing Boundaries to Reuse

The implementation must reuse the existing architecture rather than build parallel paths:

- `AnalysisOrchestrator` owns request-level orchestration.
- `DeterministicAcquisitionPlanner` and `BoundedAcquisitionRunner` own bounded acquisition decisions and attempts.
- `StructuredSecProvider` owns typed SEC endpoint acquisition for company facts, submissions, and filing discovery metadata.
- `SecClient` owns User-Agent headers, process-wide request pacing, retry/backoff, and Retry-After handling.
- `stage_sec_response` / SEC staging own immutable source capture and checksums.
- accounting promotion and normalization own SEC-to-canonical accounting semantics.
- valuation and research builders remain downstream consumers and must not be changed to accommodate acquisition.

## Request Flow

```text
qhapaq analyze TICKER
        |
        v
resolve company offline-first
        |
        v
plan local evidence
        |
        +-- sufficient ------------------------------> existing analysis path
        |
        +-- missing/stale SEC evidence
                |
                v
        FAST PATH ACQUISITION
        submissions + companyfacts
                |
                v
        immutable staging
                |
                v
        verify / promote into local canonical evidence
                |
                v
        SEC canonical gate
          |          |          |
          |          |          +--> BLOCKED
          |          |
          |          +-------------> GAP
          |                           |
          |                           v
          |                    filing-native fallback
          |                    latest required 10-K/10-Q artifacts
          |                           |
          |                           v
          |                    verify / promote
          |                           |
          |                           v
          |                    re-canonicalize ONCE
          |                      |           |
          |                      |           +--> BLOCKED
          |                      |
          |                      +--------------> still insufficient
          |                                      -> EVIDENCE_REQUIRED
          |
          +-------------------------------> READY
                                             |
                                             v
                                   market / capital cost / reverse DCF
                                             |
                                             v
                                        truthful final state
```

## Canonical Quality Gate

The filing fallback must not be triggered by `model_requirements.model_ready` and must not use an aggregate `data_quality_score` threshold.

Those signals are too broad: they may include market, beta, risk-free, ERP, cost-of-debt, or other non-SEC dependencies that additional SEC filings cannot repair.

The fallback trigger is the result of a dedicated SEC canonical gate evaluated after company-facts promotion and accounting normalization.

### Top-Level States

The gate returns exactly one of:

- `SEC_CANONICAL_READY`
- `SEC_CANONICAL_GAP`
- `SEC_CANONICAL_BLOCKED`

The external state is intentionally small. `GAP` and `BLOCKED` carry typed reason codes so acquisition decisions never depend on parsing exception strings.

### READY

`SEC_CANONICAL_READY` means the SEC-derived canonical accounting boundary can satisfy the inputs required by the generic Reverse-DCF path.

At minimum:

- revenue establishes one valid TTM window;
- EBIT is canonical and temporally compatible;
- depreciation/amortization is canonical;
- capex is canonical with valid sign semantics;
- working-capital opening/closing evidence is available and compatible;
- effective-tax inputs are available and compatible;
- invested-capital opening/closing evidence supports a computable primary financing identity;
- cash is canonical;
- marketable securities are canonical;
- debt is canonical;
- valuation shares are canonical with the required basis;
- required values are finite;
- period, unit, taxonomy, and endpoint-alignment invariants pass;
- no required metric remains ambiguous.

`READY` does not mean market data or capital-cost evidence is ready. Those remain separate downstream boundaries.

### GAP

`SEC_CANONICAL_GAP` is reserved for failures that are plausibly repairable by filing-native evidence.

Typed reason codes should include, as needed by the existing canonicalization contracts:

- `MISSING_STANDARD_CONCEPT`
- `AMBIGUOUS_CONTEXT`
- `PERIOD_COVERAGE_GAP`
- `STANDARD_CONCEPT_COVERAGE_GAP`
- `REQUIRED_COMPONENT_MISSING`
- `EXTENSION_DISCOVERY_REQUIRED`
- `FILING_CONTEXT_REQUIRED`

`EXTENSION_DISCOVERY_REQUIRED` means the standardized aggregate surface is insufficient and filing-level inspection is needed. It does not assert that the issuer actually uses a custom XBRL extension; that conclusion may only be made after filing-native evidence is inspected.

The exact internal enum may be narrower if the codebase can deterministically map multiple low-level causes to one stable semantic reason. Reason codes are internal typed orchestration semantics, not additions to the public `AnalysisResult` schema. They must not expose raw exception text as a contract.

A GAP may trigger the filing-native fallback exactly once.

### BLOCKED

`SEC_CANONICAL_BLOCKED` represents conditions that another filing download should not be expected to repair safely.

Examples:

- malformed SEC payload;
- checksum or integrity mismatch;
- immutable staging conflict;
- invalid source identity;
- contradictory source metadata;
- unsupported source representation;
- SEC/network/configuration failure during acquisition;
- failure to verify or promote an acquired artifact;
- internal canonicalization invariant violation that indicates inconsistent evidence rather than missing coverage.

These map to analysis `BLOCKED` and do not trigger filing fallback.

## Filing-Native Fallback

The fallback is gap-directed and bounded.

It must not scrape filings broadly. It should use submissions/discovery metadata already obtained to identify the most recent relevant 10-K/10-Q and acquire only the artifact set required by the unresolved SEC canonical gap.

The existing corpus builder demonstrates the permitted filing surface: primary filing document plus relevant XBRL/XML/XSD resources and `FilingSummary.xml` when available.

The fallback may perform one acquisition phase followed by one re-canonicalization phase. There is no recursive acquisition loop.

If filing-native evidence still cannot satisfy the canonical requirements without violating fail-closed semantics, the terminal state is `EVIDENCE_REQUIRED`, not `BLOCKED`, unless a true acquisition/integrity/invariant failure occurred.

## State Mapping

The request-level mapping is deterministic:

```text
authoritative ticker negative
    -> UNSUPPORTED_TICKER

SEC/network/config/staging/integrity failure
    -> BLOCKED

fast-path canonical READY
    -> continue analysis

fast-path canonical GAP
    -> filing fallback once

fallback canonical READY
    -> continue analysis

fallback completes successfully but canonical evidence remains insufficient
    -> EVIDENCE_REQUIRED

market/capital-cost evidence missing after SEC canonical READY
    -> existing downstream EVIDENCE_REQUIRED/BLOCKED semantics
```

`UNSUPPORTED_TICKER` remains exclusively owned by authoritative company resolution. Acquisition must never emit or infer it.

## Orchestrator Contract

`AnalysisOrchestrator.plan()` remains offline-only.

`AnalysisOrchestrator.analyze()` remains offline-first and may invoke acquisition only after a company has been resolved and the local plan identifies an SEC evidence gap that is eligible for acquisition.

The existing company-reference refresh contract remains unchanged:

```text
local resolve
  -> optional authoritative company-reference refresh (maximum 1)
  -> local resolve (maximum 1 post-refresh attempt)
```

SEC evidence acquisition is a separate bounded subsystem and must not be counted as or converted into company-reference refresh retries.

## Acquisition Bounds

At request level:

- one fast-path SEC acquisition phase;
- one canonical gate evaluation after fast path;
- at most one filing-native fallback phase;
- one canonical gate evaluation after fallback;
- no recursive or unbounded orchestration retries.

HTTP retry/backoff remains entirely owned by `SecClient`.

## Rate Limiting

No new queue, worker, Redis limiter, or token bucket is introduced in this increment.

All SEC requests continue through `SecClient`, which already owns:

- explicit User-Agent from SEC organization/contact configuration;
- process-wide concurrency-safe pacing;
- a configured maximum RPS bounded at or below 10;
- Retry-After handling;
- bounded retry/backoff for throttling and transient server errors.

A distributed limiter becomes a separate future concern only if Qhapaq introduces multiple concurrent processes/workers sharing one SEC request budget.

## Error Classification

The implementation must stop collapsing every accounting/corpus exception to `None` when that loss of information would prevent distinguishing `GAP` from `BLOCKED`.

Introduce the smallest typed result/error boundary necessary to preserve canonicalization cause without changing financial semantics.

Preferred shape:

```text
SecCanonicalGateResult
  state: READY | GAP | BLOCKED
  reason: typed reason code or None
  snapshot: canonical AccountingSnapshot only when READY
```

The exact class name is not contractual. The semantic separation is.

No fallback decision may be made by substring matching exception messages.

## Data Ownership

- acquired bytes first enter immutable staging;
- staged evidence is not trusted evidence by virtue of download success;
- verification/promotion must complete before canonicalization consumes the artifact as trusted local evidence;
- renderers never participate in acquisition or canonicalization;
- canonical finance remains downstream and unchanged.

## Testing Strategy

Use TDD and emphasize boundary/state tests over ticker-specific production logic.

Required regression coverage:

1. local SEC evidence sufficient -> zero acquisition calls;
2. cold valid ticker -> submissions/companyfacts fast path is attempted;
3. fast-path canonical READY -> no filing fallback;
4. recoverable canonical GAP -> exactly one filing fallback phase;
5. fallback canonical READY -> analysis continues downstream;
6. successful fallback but still insufficient -> `EVIDENCE_REQUIRED`;
7. malformed/integrity/staging/network/config failure -> `BLOCKED`;
8. market/capital-cost missing after SEC READY does not trigger filing fallback;
9. `UNSUPPORTED_TICKER` remains resolution-only;
10. no path performs more than one filing fallback phase;
11. `plan()` remains network-free;
12. HTTP traffic still flows only through `SecClient`;
13. no ticker-specific production branches;
14. existing QCOM/NVDA/AAPL and resolution contract regressions remain green;
15. JPM cold-path test uses fixtures/fakes for deterministic CI and proves the state transition rather than depending on live SEC network.

## Observable Acceptance

For a cold but valid ticker such as JPM in a controlled environment with SEC acquisition enabled:

```text
qhapaq analyze JPM
```

must no longer stop solely because automatic acquisition is disabled.

The command must demonstrate:

- authoritative company identity is preserved;
- missing SEC evidence triggers bounded acquisition;
- acquired source artifacts are staged immutably and verified/promoted;
- fast-path company facts are canonicalized first;
- filing-native fallback occurs only on a typed recoverable canonical gap;
- the request terminates without loops;
- the final state is truthful according to available SEC plus downstream market/capital-cost evidence.

Acceptance does not require JPM to reach `COMPLETED` if non-SEC downstream evidence remains unavailable. It requires the acquisition boundary to operate correctly and report the correct next state.

## Non-Negotiable Invariants

```text
cache miss                  != unsupported ticker
registry miss               != unsupported ticker
network/config/refresh fail != unsupported ticker
authoritative negative      == unsupported ticker

market-data gap             != SEC filing fallback trigger
capital-cost gap            != SEC filing fallback trigger
aggregate quality score     != SEC filing fallback trigger
model_ready false           != SEC filing fallback trigger

recoverable SEC canonical gap -> filing fallback at most once
integrity/acquisition failure  -> BLOCKED
successful but insufficient    -> EVIDENCE_REQUIRED
```

## Completion Boundary

This increment is complete when automatic cold-ticker SEC acquisition is wired end-to-end, the typed canonical gate governs filing fallback deterministically, all bounded-retry/state invariants are tested, observable cold-path behavior is demonstrated, and the full repository quality gates are green.

A separate future increment may optimize filing artifact targeting further, add multi-process rate coordination, or extend downstream market/capital-cost acquisition. Those are explicitly not prerequisites for this closure.
