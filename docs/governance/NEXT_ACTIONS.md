# Next actions

Queue reviewed: 2026-09-08. `DOING` is limited to two items; `NEXT` is limited to three.

## DOING

### Close cycle-aware run-rate correction

- **Objective:** Integrate `fix/cycle-aware-cash-basis-v0.1` only after the complete repository gate passes.
- **Why it matters:** The Micron stress test demonstrated that timing normalization must not be presented as through-cycle earning power.
- **Definition of Done:** Python 3.10 and 3.12 pass frozen sync, lock check, Ruff format/lint, cold mypy, full pytest, and deterministic QCOM render; QCOM/NVDA render `RUN-RATE ONLY`; `through_cycle` is rejected by the cash-basis contract; no stale `Normalized Cash Power`, raw Expectations Gap, `CLEARING HURDLE`, or `UNDERWRITING` product labels remain; no review thread blocks merge.

## NEXT

### Real-browser QCOM + NVDA QA

- **Objective:** Open both pages from integrated `main` and judge the actual morning deep-work experience.
- **Definition of Done:** The first viewport makes price, evidence, analytical cash basis, `RUN-RATE ONLY`, market-implied hurdle, and assumption sensitivity obvious; the cycle caveat is visible without being alarmist; thesis/counterthesis and invalidation remain easy to inspect; no material empty-space or hierarchy defect remains.

### Through-cycle support-range research

- **Objective:** Determine whether Qhapaq can estimate a defensible sustainable cash/growth range without hiding cyclicality or structural change behind a generic moving average.
- **Guardrail:** Do not promote any formula to product state until it survives deliberately adverse historical cases. A failed falsification test blocks `FAIR`, `STRETCHED`, `BROKEN`, or expected-return states.

### Maintenance time trial

- **Objective:** Measure the human effort required to refresh evidence, cash basis, thesis, risks, and invalidation after earnings for a small curated universe.
- **Warning thresholds:** >4 active hours for five companies is a serious product warning; >5 hours for ten companies is a kill-threshold signal.

## BLOCKED

- `FAIR`, `STRETCHED`, `BROKEN`, expected return, target price, or recommendation states.
- Broad automated coverage or hundreds of tickers.
- Portfolio optimization without explicit investor/context inputs.

## DEFERRED

- SaaS infrastructure, auth, billing, and multi-user features.
- Streaming daemons / sub-minute polling.
- Technical indicators, arbitrary AI scores, and traditional dashboard clutter.
- Predictive ML, automated trading, broker execution, and performance claims.

## DONE RECENTLY

- 2026-09-08: PR #8 integrated the first evidence-linked cash normalization and reverse-DCF sensitivity while retiring the raw Expectations Gap.
- 2026-09-08: Micron FY2022/FY2023 stress testing falsified the stronger claim that timing-normalized cash is through-cycle cash power.
- 2026-09-08: The cash-basis contract was narrowed to `run_rate`; product state changed from `UNDERWRITING` to `RUN-RATE ONLY`; regression coverage now prevents unsupported promotion to `through_cycle`.
- 2026-09-08: PR #7 fixed provider market-cap omission with generic fallbacks; PR #6 added the bounded NVDA research case; PR #5 established Qhapaq One as the primary product surface.
