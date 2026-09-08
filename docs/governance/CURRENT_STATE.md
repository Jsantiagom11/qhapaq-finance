# Current state

Last verified: 2026-09-08

| Area | Status | Current fact |
| --- | --- | --- |
| Project identity | GO | Human name: **Qhapaq Finance**; repository/distribution: `qhapaq-finance`; Python package: `qhapaq_finance`; CLI: `qhapaq`. |
| Main baseline | GO | `origin/main` is `cb493f3d48f799814b36da095199f4b40e2f7d7a` (`cb493f3`), containing QCOM and NVDA research, Qhapaq One, live-market fallbacks, and PRs #3–#7. |
| Current review branch | GO | `feat/normalized-cash-power-v0.1` is the sole Qhapaq development candidate. It replaces the raw recent-FCF Expectations Gap rather than extending it. |
| Quality | PENDING | PR #7 passed the full Python 3.10/3.12 gate. The Normalized Cash Power candidate must pass frozen sync, lock check, Ruff format/lint, cold mypy, full pytest, and deterministic QCOM render before integration. |
| Audit posture | FAIL-CLOSED | Unknown research, missing normalization, missing equity value, and unsolved reverse-DCF cases remain `INSUFFICIENT DATA`. A normalization file with invalid provenance or inconsistent inputs raises instead of silently falling back. |
| Packaging | GO | Qhapaq One remains a Python model plus packaged self-contained HTML resource; no server or frontend framework is required. |
| CLI | GO | `qhapaq <TICKER>` remains the primary human-facing workflow. Advanced market/research/reverse-DCF paths remain available. |
| Dependencies | GO | No new runtime framework or network dependency is introduced by cash normalization. |
| Research reproducibility | GO | QCOM retains byte-frozen primary evidence. NVDA retains checksum-gated SEC/IR evidence capsules with explicit provenance and no claim that the capsules are byte-for-byte source mirrors. |
| Company research | GO (two bounded cases) | QCOM and NVDA remain the two curated company cases. Broad automated company coverage is not a current product objective. |
| Market observations | GO | `FROZEN`, `SNAPSHOT`, and `LIVE` data speeds remain separated; freshness depends on `observed_at`, not retrieval time. |
| Equity-value input | GO | Provider market cap is preferred. If unavailable, Qhapaq can derive equity value from observed price × evidence-backed filing shares and display the provenance. |
| Reverse DCF | GO | The model uses equity cash flow and equity value. `discount_rate` is explicitly interpreted as **cost of equity**, not WACC. Default sensitivity is 8/9/10% cost of equity × 2/3/4% terminal growth. |
| Raw Expectations Gap | RETIRED | `recent FCF growth - implied 10Y FCF CAGR`, `CLEARING HURDLE`, and `BELOW HURDLE` are removed from the candidate because the comparison can manufacture false signals from working-capital, capex, tax timing, and cyclicality. |
| Normalized Cash Power | CANDIDATE | A separate evidence-linked normalization artifact bridges reported FCF proxy to analytical cash power using comparative working-capital deltas, explicit timing adjustments where justified, and an explicit SBC economic-cost policy. |
| Qhapaq One | CANDIDATE | The primary screen now emphasizes Evidence → Equity Value → Normalized Cash Power → Market Requires → Sensitivity → Thesis/Counterthesis → Risks/Invalidation. It does not claim that current business performance can sustain the hurdle. |

## Methodological limitations that remain open

- **Cycle risk:** comparative-delta normalization can still be wrong if the prior comparable period was itself abnormal or the business changed structurally.
- **SBC policy:** v0.1 deducts SBC as an economic cost and forbids an equivalent second dilution charge. This is explicit but not a complete per-share dilution model.
- **Annualization:** H1 × 2 and 9M × 4/3 are mechanical diagnostics, not forecasts or normalized full-cycle earnings power.
- **Forward support:** Qhapaq does not yet estimate a defensible sustainable-growth range. Therefore it does not output `FAIR`, `STRETCHED`, `BROKEN`, `CLEARING`, or an expected return.
- **Maintenance burden:** thesis, counterthesis, normalization policy, risks, and invalidation still require human review. Scalability has not been demonstrated.

## Open loops

- **NORMALIZED CASH POWER CI:** Run the full repository gate on `feat/normalized-cash-power-v0.1` and fix every failure without broadening scope.
- **CYCLICAL STRESS TEST:** After integration, test the method on a clearly cyclical semiconductor such as Micron at peak and trough conditions. If peak cash is normalized into false comfort, the methodology fails.
- **VISUAL QA:** Render QCOM and NVDA from integrated `main` and confirm the 30-second hierarchy without reintroducing dashboard clutter.
- **MAINTENANCE TRIAL:** Time a real post-earnings update across a small company set before increasing the curated universe.
- **DEFERRED:** SaaS infrastructure, hundreds-of-tickers coverage, portfolio optimization, predictive models, streaming daemons, alerts, broker execution, technical indicators, arbitrary scores, and target prices remain outside scope.

## Strategic state

The product thesis is stronger than the retired metric. Qhapaq is being treated as a curated reverse-engineering workstation: expose the cash base, show what the price mathematically requires, make assumption sensitivity obvious, and force explicit invalidation. Engineering sophistication does not count as product validation; the next evidence must come from cyclical stress testing, maintenance time, and real morning-use visual QA.
