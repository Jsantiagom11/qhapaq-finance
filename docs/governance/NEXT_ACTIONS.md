# Next actions

Queue reviewed: 2026-09-08. `DOING` is limited to two items; `NEXT` is limited to three.

## DOING

### Integrate NVDA evidence + Expectations Gap

- **Objective:** Integrate PR #6 for `feat/nvda-evidence-gap-v0.1` after the governance-refresh HEAD passes CI.
- **Why it matters:** The current NVDA shell becomes the intended product only when market state, validated research, business delivery, implied expectations, and invalidation are visible together without false precision.
- **Definition of Done:** CI passes on Python 3.10 and 3.12; no blocking review thread remains; `qhapaq NVDA` can reach `UNDERWRITING` with VERIFIED evidence, effective equity value, 10Y FCF hurdle, recent FCF growth, Expectations Gap, thesis/counterthesis, three material risks, three invalidation conditions, and an enabled Scenario control; unknown tickers remain fail-closed; merge is explicit and traceable.
- **Dependencies / blockers:** Functional candidate HEAD `abdf8a2` passed CI run #73 before this governance refresh.

## NEXT

### Visual QA the real NVDA product

- **Objective:** Render `qhapaq NVDA` from integrated `main` in the user's browser and judge the actual 30-second reading hierarchy rather than the template in isolation.
- **Why it matters:** Product DoD requires visual truth: the user must immediately see what the market requires, what the business recently delivered, the gap, and what invalidates the thesis.
- **Definition of Done:** Desktop render has no material placeholders or broken hierarchy; price/freshness, equity value, hurdle, Expectations Gap, thesis/counterthesis, risks and invalidations are legible without excessive empty space; Scenario interaction works; any visual correction is bounded and evidence-neutral.
- **Dependencies / blockers:** PR #6 integrated and a fresh local market observation.

### Define normalized forward expectation only if product decisions require it

- **Objective:** Specify a defensible normalized forward business expectation before introducing valuation-state labels such as `FAIR`, `STRETCHED`, or `BROKEN`.
- **Why it matters:** The current Expectations Gap compares recent observed FCF growth with an implied constant-growth hurdle. That is useful for underwriting, but it is not itself a forecast or fair-value model.
- **Definition of Done:** Normalization horizon, reinvestment logic, margin assumptions, evidence/assumption boundaries, and sensitivity are explicit; missing inputs fail closed; no arbitrary score or target price is inferred.
- **Dependencies / blockers:** Visual QA confirms that the current hurdle/gap product is useful and identifies a concrete need for the next layer.

### Define portfolio-input contract before optimization

- **Objective:** Specify investor/context inputs required before any portfolio-weight recommendation or optimizer is implemented.
- **Why it matters:** Portfolio output without horizon, reference currency, liquidity needs, risk tolerance, constraints, benchmark, costs, and uncertainty assumptions would create false precision.
- **Definition of Done:** Required inputs and refusal/insufficient-data behavior are documented and testable.
- **Dependencies / blockers:** Validated multi-company records and explicit investor context.

## BLOCKED

Investor-specific valuation, allocation, and portfolio optimization remain dependency-gated.

## DEFERRED

- **Streaming daemon / sub-minute polling:** Add only when a concrete monitoring use case justifies continuous infrastructure. Current live access is on demand through `qhapaq <TICKER>`.
- **Provider redundancy:** Add a second provider only when reliability or coverage demonstrates the need; the adapter boundary already permits it.
- **Additional UI/dashboard surfaces:** Qhapaq One remains the product surface; add interface complexity only when the 30-second read demonstrably requires it.
- **Technical indicators / arbitrary AI scores / target prices:** Outside the product contract.
- **Predictive models or momentum strategy expansion:** Defer until reproducible, benchmark-relative out-of-sample evidence supports a defined need.
- **Trading/performance claims:** Outside the current evidence boundary.

## DONE RECENTLY

- 2026-09-08: PR #5 merged into `main` as `35f77e9`, making Qhapaq One v0.1 the primary product surface.
- 2026-09-08: Implemented NVDA Q2 FY2027 checksum-gated evidence capsules with explicit SEC/NVIDIA IR provenance, typed facts/calculations, annualized H1 analytical FCF proxy, recent FCF growth, thesis/counterthesis, three risks, and three invalidation conditions.
- 2026-09-08: Added provider-independent equity-value fallback from observed price × filing shares and exposed the provenance in Qhapaq One.
- 2026-09-08: Added Expectations Gap and scenario-aware `CLEARING HURDLE` / `BELOW HURDLE` diagnostics without introducing target prices or unsupported valuation labels.
- 2026-09-08: Functional candidate HEAD `abdf8a2` passed CI run #73 on Python 3.10 and 3.12 through frozen sync, lock check, Ruff format/lint, cold mypy, full pytest, deterministic QCOM render, and artifact upload before the governance refresh.
- 2026-09-08: PR #4 merged into `main` as `d9f9e95`, integrating timestamped market snapshots and provider-independent reverse DCF.
- 2026-09-07: PR #3 merged into `main` as `d276ae4`, establishing the bounded QCOM research baseline.
