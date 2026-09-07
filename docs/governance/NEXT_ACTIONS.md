# Next actions

Queue reviewed: 2026-09-07. `DOING` is limited to two items; `NEXT` is limited to three.

## DOING

### Review and integrate QCOM candidate

- **Objective:** Complete review of PR #3 for `feat/qcom-research-relative-context-v0.1` and merge only after code, CI, evidence, and governance are mutually consistent.
- **Why it matters:** The branch is the first bounded one-company evidence-to-report implementation and should become the next stable baseline only through a clean, auditable integration.
- **Definition of Done:** PR diff reviewed; GitHub Actions passes on the PR head; governance documents reflect the reviewed state; no unresolved blocking comments remain; merge into `main` is explicit and traceable.
- **Dependencies / blockers:** No known code blocker. Investor-specific valuation and portfolio outputs remain explicitly out of scope.

## NEXT

### Decide whether to expand company research scope

- **Objective:** Decide whether the validated one-company workflow should expand to a small multi-company research set.
- **Why it matters:** Expansion is useful only if it preserves the evidence contract and does not turn a research watchlist into an implied portfolio.
- **Definition of Done:** A bounded universe, evidence availability rule, comparison benchmark, and acceptance criteria are documented before implementation begins.
- **Dependencies / blockers:** PR #3 must be integrated first.

### Define portfolio-input contract before optimization

- **Objective:** Specify the investor/context inputs required before any portfolio-weight recommendation or optimizer is implemented.
- **Why it matters:** Portfolio output without horizon, reference currency, liquidity needs, risk tolerance, constraints, benchmark, costs, and uncertainty assumptions would create false precision.
- **Definition of Done:** Required inputs and refusal/insufficient-data behavior are documented and testable.
- **Dependencies / blockers:** Validated multi-company records and explicit user/investor context.

## BLOCKED

Investor-specific valuation, allocation, and portfolio optimization remain dependency-gated.

## DEFERRED

- **Predictive models or momentum strategy expansion:** Defer until reproducible, benchmark-relative out-of-sample evidence supports a defined need.
- **Trading/performance claims:** Outside the current evidence boundary.

## DONE RECENTLY

- 2026-09-07: Published `feat/qcom-research-relative-context-v0.1`; local release gate passed with 76 tests and cold mypy, and the GitHub Actions push run completed successfully.
- 2026-09-03: Completed automated QCOM release validation with deterministic offline rendering and canonical SHA-256 verification.
- 2026-09-02: Implemented the bounded QCOM evidence-to-report workflow and relative-context evidence contract.
- 2026-09-01: Rendered and visually inspected the verified ECB FX reproducibility demonstration.
- 2026-09-01: Froze and checksum-validated the official ECB daily EUR FX reference-rate snapshot.
- 2026-08-28: Established the lightweight governance workflow and renamed the project to Qhapaq Finance.
