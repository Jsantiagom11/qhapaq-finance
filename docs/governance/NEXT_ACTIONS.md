# Next actions

Queue reviewed: 2026-09-08. `DOING` is limited to two items; `NEXT` is limited to three.

## DOING

### Validate and integrate Normalized Cash Power v0.1

- **Objective:** Replace the raw recent-FCF Expectations Gap with an evidence-linked normalized cash base for QCOM and NVDA, plus explicit reverse-DCF sensitivity.
- **Why it matters:** A 30-second product is dangerous if its central metric is structurally noisy. Working capital, capex, taxes, SBC, and cyclicality must be visible before Qhapaq can compress the result.
- **Definition of Done:** Python 3.10 and 3.12 pass frozen sync, lock check, Ruff format/lint, cold mypy, full pytest, and deterministic QCOM render; old `Expectations gap`, `CLEARING HURDLE`, and recent-FCF-growth UI are absent; QCOM and NVDA load validated normalization bridges; reverse DCF uses Normalized Cash Power; 3×3 cost-of-equity/terminal-growth sensitivity is visible; missing normalization fails closed; no review threads block merge.
- **Dependencies / blockers:** Current candidate is `feat/normalized-cash-power-v0.1`. Methodology remains provisional until the cyclical stress test below.

## NEXT

### Cyclical semiconductor stress test

- **Objective:** Attempt to falsify the normalization method on a clearly cyclical semiconductor such as Micron across a peak and trough.
- **Why it matters:** A normalization model that turns peak-cycle cash into apparently durable earning power would create the exact false comfort Qhapaq is designed to avoid.
- **Definition of Done:** Reconstruct at least one peak and one trough using frozen evidence; apply the same normalization contract without ticker-specific rescue logic; document whether the resulting cash power and hurdle would have misled the user. Any material false-comfort result is a methodological failure, not a UI issue.
- **Maximum effort:** One bounded research cycle; do not build a third full company product surface unless the test justifies it.

### Visual QA QCOM + NVDA

- **Objective:** Judge the integrated real-browser Qhapaq One pages as a morning deep-work workstation.
- **Why it matters:** Mathematical correctness does not guarantee a useful product. The screen must expose assumptions, hurdle, normalization, thesis, and invalidation without empty-space waste or dashboard noise.
- **Definition of Done:** The first viewport answers what the market requires and what cash base is being underwritten; the normalization bridge and sensitivity are inspectable; thesis/counterthesis and invalidations remain readable; no misleading signal labels remain; QCOM and NVDA use the same visual grammar.
- **Dependencies / blockers:** Normalized Cash Power integrated into `main` and fresh local snapshots.

### Maintenance time trial

- **Objective:** Measure the human cost of updating a small curated universe after earnings.
- **Why it matters:** The product is only viable if evidence, normalization, thesis, risks, and invalidation can be refreshed without turning earnings season into manual maintenance debt.
- **Definition of Done:** Time a real update workflow across at least five bounded cases when available. Treat >4 hours for five companies as a serious product warning and >5 hours for ten companies as a kill-threshold signal.
- **Dependencies / blockers:** At least one real reporting-cycle update after the normalization contract stabilizes.

## BLOCKED

- Any `FAIR`, `STRETCHED`, `BROKEN`, expected-return, or recommendation state is blocked until a cycle-aware forward-support range is separately validated.
- Investor-specific allocation and optimization remain dependency-gated by explicit investor inputs and multi-company evidence.

## DEFERRED

- Broad automated coverage or hundreds of tickers.
- SaaS infrastructure, authentication, billing, and multi-user features.
- Streaming daemon / sub-minute polling.
- Additional dashboard surfaces, technical indicators, arbitrary AI scores, and target prices.
- Predictive ML, automated trading, broker execution, and performance claims.
- A second market provider until observed reliability/coverage requires it.

## DONE RECENTLY

- 2026-09-08: PR #7 merged as `cb493f3`, fixing provider market-cap omission with generic fallbacks rather than ticker-specific logic.
- 2026-09-08: PR #6 merged as `5bdcf56`, adding the bounded NVDA research case. Its raw recent-FCF Expectations Gap is now intentionally being retired after adversarial methodological review.
- 2026-09-08: PR #5 merged as `35f77e9`, establishing Qhapaq One as the primary product surface.
- 2026-09-08: Independent adversarial review classified Qhapaq as a conditional-go product with strong product utility but insufficient methodological rigor in the raw recent-FCF gap. The project direction was narrowed to a curated reverse-engineering workstation.
- 2026-09-07: PR #3 established the reproducible QCOM evidence baseline; PR #4 integrated timestamped market snapshots and provider-independent reverse DCF.
