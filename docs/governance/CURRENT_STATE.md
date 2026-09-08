# Current state

Last verified: 2026-09-07

| Area | Status | Current fact |
| --- | --- | --- |
| Project identity | GO | Human name: **Qhapaq Finance**; repository/distribution: `qhapaq-finance`; Python package: `qhapaq_finance`; CLI: `qhapaq`. |
| Main baseline | GO | `origin/main` is `d276ae4f198c7b57df6a0e6340fb3ec5fca89d10` (`d276ae4`), containing the integrated QCOM evidence-to-report workflow from PR #3. |
| Current review branch | GO | `feat/live-market-overlay-v0.1` is published through PR #4. Candidate HEAD `d790d1fa063efa539483a2d03f291f69e925053d` (`d790d1f`) passed CI before this governance refresh. |
| Quality | GO | CI run #30 passed on Python 3.10 and 3.12: frozen sync, lock check, Ruff format/lint, cold mypy, full pytest, deterministic offline QCOM render, and artifact upload. |
| Audit review | PASS | QCOM finding F1 in `_metric_value` remains resolved and regression-covered. |
| Packaging | GO | Hatchling builds `src/qhapaq_finance`; project version remains `0.2.0`. |
| CLI | GO (candidate) | Existing research and tearsheet paths remain; PR #4 adds `qhapaq market` for timestamped live/snapshot observations and `qhapaq reverse-dcf` for provider-independent implied-growth analysis. |
| Dependencies | GO | `uv.lock` is committed and unchanged by PR #4. `yfinance` remains an optional data dependency and is isolated to network adapters. |
| Frozen dataset | GO | The byte-frozen ECB daily EUR reference-rate snapshot remains checksum-validated and loadable offline for 2015-01-02 through 2026-08-31. |
| Research reproducibility | GO | The QCOM path has frozen evidence, typed facts/calculations, relative context, deterministic offline HTML, result-manifest identity, canonical SHA-256 verification, tests, and recorded visual QA. |
| Company research | GO (one-company path) | QCOM is the validated company case. NVDA research evidence has not yet been added; no NVDA report or recommendation is claimed. |
| Market observations | GO (candidate) | PR #4 introduces separate `FROZEN`, `SNAPSHOT`, and `LIVE` data speeds. Market freshness is based on `observed_at`, not retrieval time, and live observations can be frozen to deterministic JSON. |
| Expectations engine | GO (candidate) | Reverse DCF solves constant explicit-period equity-FCF growth implied by supplied equity value. It is provider-agnostic and does not produce a target price or expected return. |

## Open loops

- **PR #4 INTEGRATION:** Review and integrate `feat/live-market-overlay-v0.1` after the refreshed governance state passes CI.
- **NVDA CASE:** Add a bounded NVIDIA primary-evidence record only after the market-overlay increment is integrated. Keep filing evidence separate from timestamped market observations.
- **UNRESOLVED INVESTOR INPUTS:** Portfolio horizon, reference currency, liquidity needs, risk tolerance, constraints, comparison benchmark, cost model, and uncertainty method remain required before investor-specific portfolio outputs.
- **DEFERRED:** Portfolio optimization, predictive models, streaming daemons, alerts, broker execution, and performance claims remain outside the current bounded acceptance scope.

## Strategic state

Qhapaq now has a stable reproducible company-research baseline on `main`. The current candidate adds a
multi-speed market-data layer so fast-changing observations can update independently of slow-moving,
audit-grade evidence. The next bounded company increment is NVDA, using the same evidence contract plus
the new market snapshot and expectations layers rather than duplicating the QCOM implementation.
