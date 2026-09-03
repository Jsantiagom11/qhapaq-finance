# Next actions

Queue reviewed: 2026-09-02. `DOING` is limited to two items; `NEXT` is limited to three.

## DOING

None. Open new work only by moving a defined item from `NEXT`.

## NEXT

### One-company evidence-to-report workflow

- **Objective:** For one real company in the verified supplied research universe, transform
  validated primary-source evidence into a typed research record, thesis/counterthesis/invalidation,
  and an offline HTML report.
- **Why it matters:** This is the smallest end-to-end validation of the intended company-research
  workflow and its evidence boundary.
- **Definition of Done:** All acceptance criteria in `docs/PRODUCT_SPEC.md` pass, including
  provenance, invalid/missing evidence, availability-date behavior, deterministic calculations
  where applicable, offline rendering, evidence navigation, and recorded visual inspection.
- **Dependencies / blockers:** Verify that the supplied universe is accessible in the working
  environment, then select one company from it. Do not assume spreadsheets exist inside WSL or add
  private brokerage communications, account data, or personal transactions to the repository.

## BLOCKED

- Research-universe location and the one company to use are unresolved until the supplied material
  is verified locally.

## DEFERRED

- **Five-company expansion:** Depends on acceptance and review of the one-company workflow.
- **Portfolio-weight optimization:** Depends on validated multi-company records and explicit
  horizon, reference currency, liquidity needs, risk tolerance, constraints, comparison benchmark,
  cost model, and uncertainty method.
- **Predictive models or momentum strategy expansion:** Defer until reproducible,
  benchmark-relative out-of-sample evidence supports a defined need.

## DONE RECENTLY

- 2026-09-01: Rendered and visually inspected the verified ECB FX reproducibility demonstration.
- 2026-09-01: Froze and checksum-validated the official ECB daily EUR FX reference-rate snapshot.
- 2026-08-28: Established the lightweight governance workflow and current evidence baseline.
- 2026-08-28: Renamed the project, distribution, package, and CLI to Qhapaq Finance (`9fb4fe4`).
- 2026-08-28: Committed the dependency lock (`2ebc421`) and restored the quality baseline
  (`5ff2c1e`).
