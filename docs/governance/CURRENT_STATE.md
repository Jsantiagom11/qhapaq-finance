# Current state

Last verified: 2026-09-08

| Area | Status | Current fact |
| --- | --- | --- |
| Project identity | GO | Human name: **Qhapaq Finance**; repository/distribution: `qhapaq-finance`; package: `qhapaq_finance`; CLI: `qhapaq`. |
| Main baseline | GO | `main` includes QCOM/NVDA research, live market snapshots, Qhapaq One, market-cap fallback, and the first cash-normalization correction from PR #8. |
| Current review branch | GO | `fix/cycle-aware-cash-basis-v0.1` is the sole Qhapaq development candidate. |
| Product surface | GO (candidate) | `qhapaq <TICKER>` renders one offline decision surface with price, evidence, analytical cash basis, market-implied hurdle, sensitivity, thesis/counterthesis, risks, and invalidation. |
| Raw Expectations Gap | RETIRED | `recent FCF growth - implied 10Y CAGR`, `CLEARING HURDLE`, and `BELOW HURDLE` are removed because they could manufacture false confidence. |
| Cash basis | RUN-RATE ONLY | Comparative working-capital/timing adjustments plus explicit SBC policy produce an analytical **run-rate** cash basis. The schema rejects a `through_cycle` label under the current methodology. |
| Cyclical stress test | FAILS THROUGH-CYCLE CLAIM | Micron FY2022/FY2023 stress testing showed roughly +$3.423B vs -$5.073B under the same run-rate formula. Timing normalization does not normalize the business cycle. |
| Reverse DCF | GO | Equity cash flow is matched to equity value; `discount_rate` is cost of equity, not WACC. Default sensitivity is 8/9/10% CoE × 2/3/4% terminal growth. |
| Evidence integrity | GO / FAIL-CLOSED | Missing or invalid research/cash-basis provenance does not silently become an investment conclusion. |
| Company scope | BOUNDED | QCOM and NVDA remain the two product cases. Broad automatic coverage is deliberately deferred. |
| Architecture | GO | No server or frontend framework is required; HTML remains self-contained and deterministic from a frozen snapshot. |
| Quality | PENDING FINAL GATE | The cycle-aware branch must pass frozen sync, lock check, Ruff format/lint, cold mypy, full pytest, deterministic QCOM render, and PR review before merge. |

## Methodological limitations

- **Cycle:** run-rate timing adjustments are not a through-cycle earnings model.
- **Annualization:** H1 × 2 and 9M × 4/3 are mechanical diagnostics, not forecasts.
- **SBC:** current treatment deducts reported SBC as an economic-cost policy and forbids equivalent double counting; it is not a complete dilution model.
- **Forward support:** Qhapaq does not yet claim what growth/margins the business can sustainably support over a full cycle.
- **Valuation states:** `FAIR`, `STRETCHED`, `BROKEN`, expected return, and target price remain unsupported.
- **Maintenance:** thesis, counterthesis, cash-basis policy, risks, and invalidation still require human review.

## Open loops

- **FINAL CI + MERGE:** close `fix/cycle-aware-cash-basis-v0.1` only if the complete gate passes and no review thread blocks integration.
- **REAL BROWSER QA:** render QCOM and NVDA from integrated `main`; confirm the first viewport clearly communicates the run-rate limitation and market hurdle without dashboard clutter.
- **THROUGH-CYCLE RESEARCH:** investigate a defensible support-range methodology only after the run-rate product proves useful in real use.
- **MAINTENANCE TRIAL:** measure actual post-earnings update time before increasing the curated universe.

## Strategic state

Qhapaq is a curated reverse-engineering workstation, not a screener. The product may compress verified research and market-implied expectations, but it must distinguish **what is calculated** from **what is demonstrated**. Engineering sophistication is not evidence that current economics are durable.
