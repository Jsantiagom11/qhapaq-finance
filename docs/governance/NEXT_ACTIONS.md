# Next actions

Queue reviewed: 2026-08-28. `DOING` is limited to two items; `NEXT` is limited to three.

## DOING

None. Open new work only by moving a defined item from `NEXT`.

## NEXT

### Frozen dataset reproducibility: UNKNOWN → VERIFIED

- **Objective:** Define one point-in-time dataset artifact and verify its identity, provenance,
  license constraints, storage location, and checksum.
- **Why it matters:** Dataset identity is the current bottleneck for repeatable research and for
  every downstream empirical claim.
- **Definition of Done:** A documented acquisition procedure reproduces the same artifact; its
  checksum is independently verified; the allowed storage and redistribution policy is explicit.
- **Dependencies / blockers:** A suitable data source and licensing decision. Do not commit
  licensed or large data by default.

## BLOCKED

None currently. The dataset task has unresolved choices but can begin with source evaluation.

## DEFERRED

- **Walk-forward experiment manifest:** Defer until the frozen-data contract is verified. Its future
  evidence must include dataset checksum, configuration, Git SHA, dependency lock, applicable seed,
  walk-forward setup, metrics, and result manifest.
- **Predictive models or strategy expansion:** Defer until the baseline can produce reproducible,
  benchmark-relative out-of-sample evidence.

## DONE RECENTLY

- 2026-08-28: Established the lightweight governance workflow and current evidence baseline.
- 2026-08-28: Renamed the project, distribution, package, and CLI to Qhapaq Finance (`9fb4fe4`).
- 2026-08-28: Committed the dependency lock (`2ebc421`) and restored the quality baseline
  (`5ff2c1e`).
