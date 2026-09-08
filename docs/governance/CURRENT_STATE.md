# Current state

Last verified: 2026-09-08

| Area | Status | Current fact |
| --- | --- | --- |
| Project identity | GO | Human name: **Qhapaq Finance**; repository/distribution: `qhapaq-finance`; Python package: `qhapaq_finance`; CLI: `qhapaq`. |
| Main baseline | GO | `origin/main` is `35f77e9667e0055c6f41dc6e7d538bb34fb91af7` (`35f77e9`), containing QCOM research, the live-market overlay, and integrated Qhapaq One v0.1 from PRs #3–#5. |
| Current review branch | GO | `feat/nvda-evidence-gap-v0.1` is published through PR #6. Candidate HEAD `abdf8a291ff6e5ed6b7e4702d4fdbb62ff4a85d3` (`abdf8a2`) passed functional CI before this governance refresh. |
| Quality | GO | CI run #73 passed on Python 3.10 and 3.12 through frozen sync, lock check, Ruff format/lint, cold mypy, full pytest, deterministic offline QCOM render, and artifact upload. |
| Audit review | PASS | QCOM finding F1 in `_metric_value` remains resolved and regression-covered. NVDA missing-data behavior remains fail-closed for unknown/unvalidated tickers. |
| Packaging | GO | Hatchling builds `src/qhapaq_finance`; project version remains `0.2.0`. Qhapaq One keeps presentation separate from model logic in a packaged self-contained HTML resource. |
| CLI | GO | `qhapaq <TICKER>` is the primary human-facing workflow. Existing advanced research, market, and reverse-DCF commands remain available. |
| Dependencies | GO | `uv.lock` is unchanged. `yfinance` remains an optional data dependency isolated to the market adapter; no server or frontend framework was added. |
| Research reproducibility | GO | QCOM retains byte-frozen primary evidence and deterministic report verification. NVDA adds checksum-gated local Qhapaq evidence capsules with explicit SEC/NVIDIA IR provenance; the capsules are explicitly not represented as byte-for-byte source mirrors. |
| Company research | GO (two bounded cases) | QCOM and NVDA are now validated bounded research cases. NVDA Q2 FY2027 facts, calculations, assumptions, thesis/counterthesis, three material risks, and three invalidation conditions are represented under the shared research contract. |
| Market observations | GO | `FROZEN`, `SNAPSHOT`, and `LIVE` data speeds remain separated. Freshness is based on `observed_at`, not retrieval time. |
| Equity-value input | GO (candidate) | Provider market capitalization is preferred. When omitted, Qhapaq One can derive effective equity value from observed price × evidence-backed filing shares and displays that provenance explicitly. |
| Expectations engine | GO | Reverse DCF remains provider-independent and outputs an implied constant FCF growth hurdle, not a target price or expected return. |
| Expectations Gap | GO (candidate) | PR #6 compares recent evidence-backed FCF-proxy growth with the market-implied hurdle. `CLEARING HURDLE` / `BELOW HURDLE` describe that diagnostic only; they are not valuation recommendations or forecasts. |
| Qhapaq One | GO (candidate) | NVDA can now reach `UNDERWRITING` with VERIFIED evidence, effective equity value, 10Y FCF hurdle, recent FCF growth, Expectations Gap, thesis/counterthesis, risks, invalidation, and live Scenario recomputation in one responsive offline view. |

## Open loops

- **PR #6 INTEGRATION:** Integrate `feat/nvda-evidence-gap-v0.1` after this governance-refresh HEAD passes CI and no blocking review thread remains.
- **VISUAL QA:** After integration, render `qhapaq NVDA` locally and inspect the real browser output at desktop width. Product DoD is not visually closed until the 30-second hierarchy is confirmed from the rendered page.
- **NORMALIZED FORWARD EXPECTATION:** Do not introduce `FAIR`, `STRETCHED`, or `BROKEN` from the current Expectations Gap. Those labels require a defensible normalized forward business expectation, not recent observed FCF growth.
- **UNRESOLVED INVESTOR INPUTS:** Portfolio horizon, reference currency, liquidity needs, risk tolerance, constraints, benchmark, costs, and uncertainty method remain required before investor-specific outputs.
- **DEFERRED:** Portfolio optimization, predictive models, streaming daemons, alerts, broker execution, technical-indicator dashboards, arbitrary scores, target prices, and performance claims remain outside the bounded acceptance scope.

## Strategic state

Qhapaq One now has the substantive layers needed for the intended 30-second product: current market observation, auditable research provenance, implied expectations, recent business delivery, an explicit gap, thesis/counterthesis, and invalidation. The next product gate is visual truth in the user's browser, not additional architecture or dashboard features.
