# Next actions

Queue reviewed: 2026-09-07. `DOING` is limited to two items; `NEXT` is limited to three.

## DOING

### Integrate live market overlay v0.1

- **Objective:** Integrate PR #4 for `feat/live-market-overlay-v0.1` after the refreshed governance state passes CI.
- **Why it matters:** Qhapaq needs fast-changing market observations without weakening the frozen evidence contract used for company research.
- **Definition of Done:** CI passes on Python 3.10 and 3.12; no blocking review thread remains; `FROZEN`, `SNAPSHOT`, and `LIVE` semantics are documented; merge into `main` is explicit and traceable.
- **Dependencies / blockers:** No known code blocker. CI run #30 passed before the governance refresh.

## NEXT

### Build bounded NVDA research case

- **Objective:** Add NVIDIA as the second company case using primary evidence, timestamped market observations, and the reverse-DCF expectations layer.
- **Why it matters:** NVDA validates that the QCOM workflow is reusable while testing a company whose valuation changes materially faster than its filing evidence.
- **Definition of Done:** Primary sources are frozen/checksum-gated; research facts and calculations are typed; a market snapshot is separately timestamped; reverse-DCF assumptions are explicit; an offline report renders deterministically with visible evidence and freshness semantics.
- **Dependencies / blockers:** PR #4 integrated. Current NVDA market and valuation inputs must not be hard-coded as timeless facts.

### Compose research + market overlay in the HTML report

- **Objective:** Allow a company report to consume an optional market snapshot without mutating the underlying research record.
- **Why it matters:** A report should refresh price-sensitive interpretation without re-freezing filings or losing reproducibility.
- **Definition of Done:** The report shows filing cutoff, market `observed_at`, retrieval time, provider, freshness status, and reverse-DCF assumptions as separate provenance layers; stale/future observations are visible and test-covered.
- **Dependencies / blockers:** Stable market snapshot contract and one completed NVDA case.

### Define portfolio-input contract before optimization

- **Objective:** Specify investor/context inputs required before any portfolio-weight recommendation or optimizer is implemented.
- **Why it matters:** Portfolio output without horizon, reference currency, liquidity needs, risk tolerance, constraints, benchmark, costs, and uncertainty assumptions would create false precision.
- **Definition of Done:** Required inputs and refusal/insufficient-data behavior are documented and testable.
- **Dependencies / blockers:** Validated multi-company records and explicit user/investor context.

## BLOCKED

Investor-specific valuation, allocation, and portfolio optimization remain dependency-gated.

## DEFERRED

- **Streaming daemon / sub-minute polling:** Add only when a concrete monitoring use case justifies continuous infrastructure. Current live access is on demand.
- **Provider redundancy:** Add a second provider when reliability or data coverage demonstrates the need; the adapter boundary already permits it.
- **Predictive models or momentum strategy expansion:** Defer until reproducible, benchmark-relative out-of-sample evidence supports a defined need.
- **Trading/performance claims:** Outside the current evidence boundary.

## DONE RECENTLY

- 2026-09-07: PR #3 merged into `main` as `d276ae4`, making the bounded QCOM evidence-to-report workflow the stable baseline.
- 2026-09-07: Implemented PR #4 candidate with typed timestamped market snapshots, caller-owned freshness policy, optional yfinance live adapter, deterministic snapshot freezing/replay, provider-independent reverse DCF, CLI paths, documentation, and tests.
- 2026-09-07: CI run #30 passed on Python 3.10 and 3.12 through frozen sync, lock check, Ruff format/lint, cold mypy, full pytest, deterministic QCOM render, and artifact upload before the governance refresh.
- 2026-09-07: Reconciled and fixed audit finding F1 in `_metric_value`, added regression coverage, and completed independent Gemini review: PASS; F1: RESOLVED.
- 2026-09-03: Completed automated QCOM release validation with deterministic offline rendering and canonical SHA-256 verification.
- 2026-09-01: Froze and checksum-validated the official ECB daily EUR FX reference-rate snapshot.
