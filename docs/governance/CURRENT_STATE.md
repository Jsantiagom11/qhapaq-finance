# Current state

Last verified: 2026-09-01

| Area | Status | Current fact |
| --- | --- | --- |
| Project identity | GO | Human name: **Qhapaq Finance**; repository/distribution: `qhapaq-finance`; Python package: `qhapaq_finance`; CLI: `qhapaq`. |
| Current branch | GO | `main`, synchronized with `origin/main` before this governance commit. |
| Stable baseline | GO | Commit `9fb4fe4` contains the renamed, installable methodological research baseline. |
| Quality | GO | Lock validation, format, lint, cold and incremental typing, tests, CLI smoke, and whitespace checks pass; see the 2026-08-31 daily report. |
| Packaging | GO | Hatchling builds `src/qhapaq_finance`; project version is `0.2.0`. |
| CLI | GO | The declared `qhapaq` entry point responds to `--help`. Live provider execution is not part of the verified baseline. |
| Dependencies | GO | `uv.lock` is committed and `uv lock --check` passes. |
| Frozen dataset | GO | The byte-frozen ECB daily EUR reference-rate snapshot is checksum-validated, documented, and loadable offline for 2015-01-02 through 2026-08-31. |
| Research reproducibility | PARTIAL | Dataset identity and point-in-time loading are verified; no research-result manifest or verified tear sheet exists. No empirical or trading-edge claim is supported. |

## Open loops

- **NEXT:** Build the bounded verified Research Tear Sheet using only the frozen ECB snapshot and
  emit a machine-readable result manifest.
- **DEFERRED:** Predictive models and performance claims remain outside the baseline until the
  publication gates in `docs/AUDIT.md` have reproducible evidence.

## Strategic state

The software, identity, and first frozen-data baseline are stable. The next bottleneck is connecting
the verified ECB snapshot to an evidence-gated report with a complete result manifest without
weakening the publication gates.
