# Next actions

Queue reviewed: 2026-09-08. `DOING` is limited to two items; `NEXT` is limited to three.

## DOING

### Integrate Qhapaq One v0.1

- **Objective:** Integrate PR #5 for `feat/qhapaq-one-v0.1` after the governance refresh passes CI.
- **Why it matters:** Qhapaq needs one primary human-facing product that compresses market state, evidence, implied expectations, thesis, counterthesis, risks and invalidation into a roughly 30-second read without weakening reproducibility.
- **Definition of Done:** CI passes on Python 3.10 and 3.12; no blocking review thread remains; `qhapaq <TICKER>` renders the self-contained decision surface; QCOM reaches `UNDERWRITING` with complete inputs; missing NVDA evidence remains explicitly `INSUFFICIENT DATA`; merge into `main` is explicit and traceable.
- **Dependencies / blockers:** No known code blocker. Feature HEAD `1115260` passed CI run #55 before this governance refresh.

## NEXT

### Build bounded NVDA primary-evidence pack

- **Objective:** Add NVIDIA as the second validated company case using primary evidence while reusing the integrated market and Qhapaq One layers.
- **Why it matters:** NVDA is the intended high-velocity valuation case and tests whether Qhapaq can update market expectations continuously without pretending that slow-moving filing evidence is equally fresh.
- **Definition of Done:** Primary sources are frozen/checksum-gated; facts/calculations/assumptions/interpretations remain distinct; a compatible normalized FCF basis is explicit; Qhapaq One can combine the evidence pack with a separately timestamped market snapshot without hard-coded timeless market values.
- **Dependencies / blockers:** PR #5 integrated. Current NVDA market observations must remain separate from audit-grade evidence.

### Define evidence-backed Expectations Gap

- **Objective:** Compare the reverse-DCF market hurdle with a normalized, evidence-backed business expectation without manufacturing a forecast.
- **Why it matters:** This is the missing foundation for later state labels such as `FAIR`, `STRETCHED`, or `BROKEN`; without it those labels would be arbitrary scores.
- **Definition of Done:** Business-expectation inputs have explicit provenance or assumption status; comparison horizon and normalization rules are documented; sensitivity is visible; missing inputs yield `INSUFFICIENT DATA`; no target price or expected return is inferred.
- **Dependencies / blockers:** At least one validated case with both market hurdle and defensible normalized business expectation, preferably NVDA.

### Define portfolio-input contract before optimization

- **Objective:** Specify investor/context inputs required before any portfolio-weight recommendation or optimizer is implemented.
- **Why it matters:** Portfolio output without horizon, reference currency, liquidity needs, risk tolerance, constraints, benchmark, costs, and uncertainty assumptions would create false precision.
- **Definition of Done:** Required inputs and refusal/insufficient-data behavior are documented and testable.
- **Dependencies / blockers:** Validated multi-company records and explicit user/investor context.

## BLOCKED

Investor-specific valuation, allocation, and portfolio optimization remain dependency-gated.

## DEFERRED

- **Streaming daemon / sub-minute polling:** Add only when a concrete monitoring use case justifies continuous infrastructure. Current live access is on demand through `qhapaq <TICKER>`.
- **Provider redundancy:** Add a second provider when reliability or data coverage demonstrates the need; the adapter boundary already permits it.
- **Additional UI/dashboard surfaces:** Qhapaq One is the product surface; add interface complexity only when the 30-second read or deeper analysis demonstrably requires it.
- **Technical indicators / arbitrary AI scores / target prices:** Outside the current product contract.
- **Predictive models or momentum strategy expansion:** Defer until reproducible, benchmark-relative out-of-sample evidence supports a defined need.
- **Trading/performance claims:** Outside the current evidence boundary.

## DONE RECENTLY

- 2026-09-08: Implemented Qhapaq One v0.1 candidate with `qhapaq <TICKER>`, automatic market-snapshot freezing, market-cap-aware reverse DCF, responsive self-contained HTML, local scenario controls, honest state semantics, and deterministic product tests.
- 2026-09-08: Refactored Qhapaq One presentation into a packaged HTML resource so financial model logic remains separate from visual design.
- 2026-09-08: Feature HEAD `1115260` passed CI run #55 on Python 3.10 and 3.12 through frozen sync, lock check, Ruff format/lint, cold mypy, full pytest, deterministic QCOM render, and artifact upload before the governance refresh.
- 2026-09-08: PR #4 merged into `main` as `d9f9e95`, integrating timestamped market snapshots, FROZEN/SNAPSHOT/LIVE semantics, deterministic replay, and provider-independent reverse DCF.
- 2026-09-07: PR #3 merged into `main` as `d276ae4`, making the bounded QCOM evidence-to-report workflow the stable research baseline.
- 2026-09-07: Reconciled and fixed audit finding F1 in `_metric_value`, added regression coverage, and completed independent Gemini review: PASS; F1: RESOLVED.
- 2026-09-03: Completed automated QCOM release validation with deterministic offline rendering and canonical SHA-256 verification.
