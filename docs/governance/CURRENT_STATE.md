# Current state

Last verified: 2026-09-07

| Area | Status | Current fact |
| --- | --- | --- |
| Project identity | GO | Human name: **Qhapaq Finance**; repository/distribution: `qhapaq-finance`; Python package: `qhapaq_finance`; CLI: `qhapaq`. |
| Main baseline | GO | `origin/main` is `6f6f966`; it remains the stable merged baseline until the current review branch is accepted. |
| Current review branch | GO | `feat/qcom-research-relative-context-v0.1` is published and tracked on GitHub. The reviewed candidate HEAD is `aadafe3cda5aa0d19497fd357eeb4ab4ca676b12` (`aadafe3`); PR #3 remains pending integration. |
| Quality | GO | Final local validation after the F1 fix: 3 targeted tests passed, full pytest passed with 79 tests, Ruff format check and Ruff check passed, `mypy --no-incremental src` passed, and `git diff --check` passed. GitHub Actions for candidate HEAD `aadafe3` completed successfully. |
| Audit review | PASS | Finding F1 in `_metric_value` was reconciled, fixed, regression-tested, independently reviewed by Gemini, and resolved. Gemini review verdict: PASS; F1: RESOLVED. |
| Packaging | GO | Hatchling builds `src/qhapaq_finance`; project version is `0.2.0`. |
| CLI | GO | The declared `qhapaq` entry point responds to `--help`; the QCOM research path renders deterministically offline from committed evidence. |
| Dependencies | GO | `uv.lock` is committed and `uv lock --check` passes. `yfinance` remains an optional data dependency with a module-scoped mypy override. |
| Frozen dataset | GO | The byte-frozen ECB daily EUR reference-rate snapshot is checksum-validated, documented, and loadable offline for 2015-01-02 through 2026-08-31. |
| Research reproducibility | GO (bounded workflow) | The QCOM evidence-to-report path has frozen evidence, typed facts/calculations, relative context, deterministic offline HTML, result-manifest identity, canonical SHA-256 verification, tests, and recorded visual QA. This does not generalize to a demonstrated trading edge. |
| Company research | GO (one-company path) | The bounded QCOM workflow is technically validated for research use. It is not a holding recommendation, allocation, target price, or suitability result. |

## Open loops

- **PR INTEGRATION:** Integrate the reviewed QCOM candidate through PR #3; integration remains the immediate action, and PR #3 has not been merged. Do not merge while governance or CI is inconsistent.
- **UNRESOLVED INVESTOR INPUTS:** Portfolio horizon, reference currency, liquidity needs, risk tolerance, constraints, comparison benchmark, cost model, and uncertainty method remain required before investor-specific portfolio outputs.
- **DEFERRED:** Five-company expansion, portfolio optimization, predictive models, and performance claims remain outside the current bounded acceptance scope.

## Strategic state

The merged `main` branch remains the stable baseline. The current candidate extends that baseline from an ECB reproducibility demonstration to a bounded one-company research workflow with committed evidence and deterministic rendering. The immediate bottleneck is disciplined PR review and integration, not additional model complexity or broader universe expansion.
