# Current state

Last verified: 2026-08-28

| Area | Status | Current fact |
| --- | --- | --- |
| Project identity | GO | Human name: **Qhapaq Finance**; repository/distribution: `qhapaq-finance`; Python package: `qhapaq_finance`; CLI: `qhapaq`. |
| Current branch | GO | `main`, synchronized with `origin/main` before this governance commit. |
| Stable baseline | GO | Commit `9fb4fe4` contains the renamed, installable methodological research baseline. |
| Quality | GO | Format, lint, tests, typing, and whitespace checks pass; see `EVIDENCE.md`. |
| Packaging | GO | Hatchling builds `src/qhapaq_finance`; project version is `0.2.0`. |
| CLI | GO | The declared `qhapaq` entry point responds to `--help`. Live provider execution is not part of the verified baseline. |
| Dependencies | GO | `uv.lock` is committed and `uv lock --check` passes. |
| Research reproducibility | NO-GO | No frozen point-in-time dataset, dataset checksum, or result manifest exists. No empirical or trading-edge claim is supported. |

## Open loops

- **UNKNOWN:** A frozen dataset and its identity, provenance, license, and checksum have not been
  established.
- **DEFERRED:** End-to-end walk-forward execution and a machine-readable result manifest depend on
  the frozen-data contract.
- **DEFERRED:** Predictive models and performance claims remain outside the baseline until the
  publication gates in `docs/AUDIT.md` have reproducible evidence.

## Strategic state

The software and identity baseline is stable. The current bottleneck is research reproducibility,
not additional model or architecture work. The next transition is to make one frozen dataset
independently identifiable and verifiable before expanding the experiment pipeline.
