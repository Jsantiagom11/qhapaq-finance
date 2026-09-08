# Current state

Last verified: 2026-09-08

| Area | Status | Current fact |
| --- | --- | --- |
| Project identity | GO | Human name: **Qhapaq Finance**; repository/distribution: `qhapaq-finance`; Python package: `qhapaq_finance`; CLI: `qhapaq`. |
| Main baseline | GO | `origin/main` is `d9f9e95901d9a1cceb2c07611175b27bf8ddbb3a` (`d9f9e95`), containing the integrated QCOM research workflow and live-market overlay from PRs #3 and #4. |
| Current review branch | GO | `feat/qhapaq-one-v0.1` is published through PR #5. Feature HEAD `1115260458047a412a3b4be98e906db76376796b` (`1115260`) passed CI before this governance refresh. |
| Quality | GO | CI run #55 passed on Python 3.10 and 3.12: frozen sync, lock check, Ruff format/lint, cold mypy, full pytest, deterministic offline QCOM render, and artifact upload. |
| Audit review | PASS | QCOM finding F1 in `_metric_value` remains resolved and regression-covered. |
| Packaging | GO | Hatchling builds `src/qhapaq_finance`; project version remains `0.2.0`. Qhapaq One keeps its self-contained HTML presentation as a packaged resource separate from model logic. |
| CLI | GO (candidate) | Existing advanced paths remain available; PR #5 makes `qhapaq <TICKER>` the primary human-facing workflow, generating a timestamped market snapshot and one concise decision surface. |
| Dependencies | GO | `uv.lock` is unchanged by Qhapaq One. `yfinance` remains an optional data dependency isolated to network adapters. No framework or server dependency was added. |
| Frozen dataset | GO | The byte-frozen ECB daily EUR reference-rate snapshot remains checksum-validated and loadable offline for 2015-01-02 through 2026-08-31. |
| Research reproducibility | GO | The QCOM path retains frozen evidence, typed facts/calculations, relative context, deterministic offline HTML, result-manifest identity, canonical SHA-256 verification, tests, and recorded visual QA. |
| Company research | GO (one-company path) | QCOM is the validated company case. NVDA has no committed primary-evidence pack yet; Qhapaq One therefore reports `INSUFFICIENT DATA` rather than manufacturing a thesis or valuation state. |
| Market observations | GO | `FROZEN`, `SNAPSHOT`, and `LIVE` data speeds are integrated on `main`. Freshness is based on `observed_at`, not retrieval time, and live observations can be frozen to deterministic JSON. |
| Expectations engine | GO | Reverse DCF solves constant explicit-period equity-FCF growth implied by supplied equity value. It remains provider-agnostic and does not produce a target price or expected return. |
| Qhapaq One | GO (candidate) | PR #5 composes market state, validated research, reverse DCF, thesis/counterthesis, key risks and invalidation into one responsive offline HTML view. QCOM can reach `UNDERWRITING`; missing layers remain `INSUFFICIENT DATA`. |

## Open loops

- **PR #5 INTEGRATION:** Review and integrate `feat/qhapaq-one-v0.1` after this governance refresh passes CI.
- **NVDA EVIDENCE PACK:** Add a bounded NVIDIA primary-evidence record as the next company increment. Keep filing evidence separate from timestamped market observations and reuse Qhapaq One rather than creating another report surface.
- **EXPECTATIONS GAP:** Only after NVDA evidence is validated, define a normalized evidence-backed business expectation to compare against the reverse-DCF hurdle. Do not introduce `FAIR`, `STRETCHED`, or `BROKEN` labels before this comparison is defensible.
- **UNRESOLVED INVESTOR INPUTS:** Portfolio horizon, reference currency, liquidity needs, risk tolerance, constraints, comparison benchmark, cost model, and uncertainty method remain required before investor-specific portfolio outputs.
- **DEFERRED:** Portfolio optimization, predictive models, streaming daemons, alerts, broker execution, technical-indicator dashboards, arbitrary scores, target prices, and performance claims remain outside the current bounded acceptance scope.

## Strategic state

Qhapaq now separates slow audit-grade evidence from fast market observations and exposes those layers through one deliberately small decision product. The product contract is to make the market hurdle, evidence state, thesis, counterthesis, risks and invalidation understandable in roughly 30 seconds while preserving the ability to inspect deeper evidence and scenarios. The next value-producing increment is NVIDIA primary evidence, not additional interface complexity.
