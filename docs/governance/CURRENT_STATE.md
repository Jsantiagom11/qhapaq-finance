# Current state

Last verified: 2026-09-07

| Area | Status | Current fact |
| --- | --- | --- |
| Project identity | GO | Human name: **Qhapaq Finance**; repository/distribution: `qhapaq-finance`; Python package: `qhapaq_finance`; CLI: `qhapaq`. |
| Main baseline | GO | `origin/main` is `6f6f966`; it remains the stable merged baseline until the current review branch is accepted. |
| Current review branch | GO | `feat/qcom-research-relative-context-v0.1` is published and tracked on GitHub. The validated code head before this governance refresh was `06ca04d`; at PR creation it was 6 commits ahead of `main` and 0 behind. |
| Quality | GO | Local gate passed lock validation, sync, Ruff lint, 76 tests, cold mypy on 11 source files, and `git diff --check`; the GitHub Actions push run for `06ca04d` also completed successfully. |
| Packaging | GO | Hatchling builds `src/qhapaq_finance`; project version is `0.2.0`. |
| CLI | GO | The declared `qhapaq` entry point responds to `--help`; the QCOM research path renders deterministically offline from committed evidence. |
| Dependencies | GO | `uv.lock` is committed and `uv lock --check` passes. `yfinance` remains an optional data dependency with a module-scoped mypy override. |
| Frozen dataset | GO | The byte-frozen ECB daily EUR reference-rate snapshot is checksum-validated, documented, and loadable offline for 2015-01-02 through 2026-08-31. |
| Research reproducibility | GO (bounded workflow) | The QCOM evidence-to-report path has frozen evidence, typed facts/calculations, relative context, deterministic offline HTML, result-manifest identity, canonical SHA-256 verification, tests, and recorded visual QA. This does not generalize to a demonstrated trading edge. |
| Company research | GO (one-company path) | The bounded QCOM workflow is technically validated for research use. It is not a holding recommendation, allocation, target price, or suitability result. |

## Open loops

- **PR REVIEW:** Review and integrate the QCOM candidate through PR #3; do not merge while governance or CI is inconsistent.
- **UNRESOLVED INVESTOR INPUTS:** Portfolio horizon, reference currency, liquidity needs, risk tolerance, constraints, comparison benchmark, cost model, and uncertainty method remain required before investor-specific portfolio outputs.
- **DEFERRED:** Five-company expansion, portfolio optimization, predictive models, and performance claims remain outside the current bounded acceptance scope.

## Strategic state

The merged `main` branch remains the stable baseline. The current candidate extends that baseline from an ECB reproducibility demonstration to a bounded one-company research workflow with committed evidence and deterministic rendering. The immediate bottleneck is disciplined PR review and integration, not additional model complexity or broader universe expansion.
