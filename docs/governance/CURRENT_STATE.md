# Current state

Last verified: 2026-09-02

| Area | Status | Current fact |
| --- | --- | --- |
| Project identity | GO | Human name: **Qhapaq Finance**; repository/distribution: `qhapaq-finance`; Python package: `qhapaq_finance`; CLI: `qhapaq`. |
| Current branch | GO | `feat/frozen-ecb-fx-snapshot` at inspected HEAD `92381c9`; no synchronization claim is made. |
| Stable baseline | GO | Commit `92381c9` contains the momentum methodological baseline, frozen ECB snapshot, and verified ECB renderer. |
| Quality | GO | Lock validation, format, lint, cold and incremental typing, tests, CLI smoke, and whitespace checks pass; see the 2026-08-31 daily report. |
| Packaging | GO | Hatchling builds `src/qhapaq_finance`; project version is `0.2.0`. |
| CLI | GO | The declared `qhapaq` entry point responds to `--help`. Live provider execution is not part of the verified baseline. |
| Dependencies | GO | `uv.lock` is committed and `uv lock --check` passes. |
| Frozen dataset | GO | The byte-frozen ECB daily EUR reference-rate snapshot is checksum-validated, documented, and loadable offline for 2015-01-02 through 2026-08-31. |
| Research reproducibility | PARTIAL | Dataset identity, point-in-time loading, deterministic ECB calculations, and the PNG renderer have recorded test and visual evidence. The PNG is an FX reproducibility demonstration, not equity research or an optimizer. |
| Company research | REVIEW | The QCOM evidence-to-report path now has frozen primary evidence, a typed record, deterministic offline HTML, and focused tests; portfolio and valuation inputs remain unresolved. |

## Open loops

- **REVIEW:** Inspect and accept the bounded QCOM evidence-to-report result before expanding scope.
- **UNRESOLVED INPUTS:** Research universe availability and company selection; portfolio horizon,
  reference currency, liquidity needs, risk tolerance, constraints, and comparison benchmark.
- **DEFERRED:** Predictive models and performance claims remain outside the baseline until the
  publication gates in `docs/AUDIT.md` have reproducible evidence.

## Strategic state

The methodological baseline and ECB reproducibility demonstration are stable at the inspected HEAD.
The next bottleneck is validating the evidence-to-report path for one real company without implying
that a watchlist is a portfolio or that the result is a one-stock recommendation. Five-company
expansion and portfolio optimization remain dependency-gated.
