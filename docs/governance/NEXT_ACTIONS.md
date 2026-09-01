# Next actions

Queue reviewed: 2026-09-01. `DOING` is limited to two items; `NEXT` is limited to three.

## DOING

None. Open new work only by moving a defined item from `NEXT`.

## NEXT

### Verified Research Tear Sheet

- **Objective:** Generate an evidence-gated Research Tear Sheet using only the checksum-validated
  frozen ECB snapshot and a machine-readable result manifest.
- **Why it matters:** Dataset identity is now verified; the next bottleneck is preserving that
  identity through the research configuration, computation, and report outputs.
- **Definition of Done:** Offline execution records dataset and manifest checksums, configuration,
  Git SHA, dependency lock, metrics, warnings, and artifacts without overstating evidence.
- **Dependencies / blockers:** Use the committed frozen ECB contract; do not introduce live or
  synthetic fallback data.

## BLOCKED

None currently.

## DEFERRED

- **Predictive models or strategy expansion:** Defer until the baseline can produce reproducible,
  benchmark-relative out-of-sample evidence.

## DONE RECENTLY

- 2026-09-01: Froze and checksum-validated the official ECB daily EUR FX reference-rate snapshot.
- 2026-08-28: Established the lightweight governance workflow and current evidence baseline.
- 2026-08-28: Renamed the project, distribution, package, and CLI to Qhapaq Finance (`9fb4fe4`).
- 2026-08-28: Committed the dependency lock (`2ebc421`) and restored the quality baseline
  (`5ff2c1e`).
