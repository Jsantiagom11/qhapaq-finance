# Executive Shortlist v0.1 Implementation Plan

> Execute task-by-task using strict RED → GREEN → Refactor → Commit.

## Goal

Add an executive shortlist pipeline over Diamond Funnel without changing
Diamond selection, scoring, classification, or ordering.

## Architectural Invariant

Diamond selects and orders.
Deep Analysis adds evidence.
Goal Seek calculates implied expectations.
Synthesis only translates.
Shortlist never reclassifies or reorders.

## Baseline

Verified Diamond Funnel Debt Zero v0.4 commit:

`93c5f85bae07a6076fa8d75617245d05b3d13c86`

Do not reopen Debt Zero design unless actual repository evidence contradicts
the verified baseline.

## Repository Ruling

Ruling: Executive Shortlist starts from dedicated branch
`feat/executive-shortlist-v0.1` at `93c5f85` — repository worktree evidence
proves that commit is the closed Debt Zero baseline — starting from the older
cold-ticker branch would omit nine verified Debt Zero commits.

## Task 1 — Executive Contracts

Create `src/qhapaq_finance/executive/contracts.py`.

Define:

- `ImpliedExpectationStatus`
  - `SOLVED`
  - `NO_SOLUTION_IN_RANGE`
  - `INPUTS_UNAVAILABLE`
- `ExecutiveEvidence`
- `ExecutiveContradiction`
- `ExecutiveAnalysisStatus`
- `ImpliedExpectationResult`
- `ExecutiveShortlistEntry`

Rules:

- `frozen=True` for immutability only.
- mypy provides static typing.
- `__post_init__` only enforces domain invariants:
  - finite numeric values;
  - no empty required strings;
  - if `conclusion_available is False`, `bottom_line` must be `None`.
- Start with RED tests for violated invariants.

## Task 2 — Revenue CAGR Goal Seek

Implement 1-D bisection over Revenue CAGR only.

Constants:

- `LOWER_BOUND = -0.30`
- `UPPER_BOUND = 0.70`
- `MAX_ITERATIONS = 50`

Tolerance:

`abs(estimated_equity - observed_market) / observed_market <= 0.001`

Rules:

- observed market non-finite or <= 0 -> `INPUTS_UNAVAILABLE`;
- missing known valuation inputs -> `INPUTS_UNAVAILABLE`;
- non-finite `run_valuation` result -> `GoalSeekEvaluationError`;
- use existing `run_valuation` only;
- mutate only `revenue_growth_cagr`;
- all other valuation assumptions remain fixed;
- bracket on residual `estimated_equity - observed_market`;
- exact endpoint solution first;
- same-sign endpoint residuals -> `NO_SOLUTION_IN_RANGE`;
- exhausted 50 iterations -> `GoalSeekConvergenceError`;
- no second DCF engine.

## Task 3 — Pure Deterministic Synthesis

Create pure `ExecutiveSynthesis.translate()`.

Inputs only:

- `surfaced_by`
- `evidence_dtos`
- `contradictions_dtos`
- `analysis_status`
- `expectation_result`

Rules:

- no `AnalyzeResult` parsing;
- no I/O;
- no financial recalculation;
- `bottom_line=None` when `conclusion_available=False`.

Add AST architecture test forbidding imports such as:

- `sec_client`
- `market_provider`
- `AnalysisOrchestrator`
- `valuation_engine`

Test detector on synthetic illegal source with `pytest.raises`, then validate
the real module cleanly.

## Task 4 — Concurrent DeepAnalysisOrchestrator

Create `DeepAnalysisOrchestrator`.

Rules:

- `asyncio.Semaphore(2)`;
- `asyncio.to_thread` for existing sync analyzer;
- preserve exact input index:
  `output[i].ticker == diamond_top_n[i].ticker`;
- never sort.

Before RED test:

- inspect repository and enumerate actual domain exception classes;
- do not invent placeholder exception classes.

Only real expected domain errors degrade to:

`conclusion_available=False`

Unexpected `KeyError`, `TypeError`, etc. must crash.

## Task 5 — qhapaq shortlist CLI

Add `qhapaq shortlist`.

Arguments:

- `--universe sp500`
- `--depth 5`
- `--format {text,json}`
- default format `text`

Test routing and semantic equivalence between JSON/text representations.

## Task 6 — Frozen Deterministic E2E

- freeze only I/O boundaries;
- use real Diamond, orchestrator, goal-seek and synthesis implementations;
- validate exact golden JSON and text;
- preserve order and provenance.

## Task 7 — Warm-Cache Real Top-5 Acceptance

Outside CI:

- run shortlist and funnel;
- programmatically assert:
  `shortlist_tickers == funnel_tickers`;
- verify provenance;
- traceable contradictions;
- valuation assumptions present;
- `bottom_line=None` when analysis incomplete.

## Task 8 — Full Regression and Integration Readiness

Run:

    uv run --no-sync ruff format --check .
    uv run --no-sync ruff check .
    uv run --no-sync mypy --no-incremental src
    uv run --no-sync pytest -q
    git diff --check

Also verify:

- protected paths unchanged;
- existing stash preserved;
- no runtime caches staged;
- `qhapaq analyze` unchanged;
- `qhapaq funnel` scoring/order unchanged.

Final state:

Branch verified and ready for integration.

## Safety

Never:

- `git reset --hard`
- blind `git clean`
- `git stash pop`
- `git stash drop`
- overwrite protected files
- stage runtime cache artifacts

If repository reality differs from plan assumptions, record:

`Ruling: <decision> — <repository evidence> — <cost if wrong>`

## Execution Rulings

Ruling: Task 2 cannot literally mutate `ValuationInput.revenue_growth_cagr` because the current `ValuationInput` has no `revenue_growth_cagr` field and `run_valuation()` is the existing FCFF/WACC metric kernel rather than a revenue-growth DCF — repository evidence in `src/qhapaq_finance/valuation.py` — implementing the frozen Task 2 wording literally would require inventing a second valuation path or silently changing the valuation contract. Resolve at Task 2 before implementation; Task 1 is unaffected.

Ruling: `ExecutiveEvidence.status` and `ExecutiveContradiction.severity` remain non-empty strings in v0.1 — the frozen contract names these fields but does not define new enum vocabularies — inventing enum values here would add a product decision not present in the approved architecture.

Ruling: Executive Shortlist v0.1 will solve market-implied explicit FCFF growth, not Revenue CAGR — the canonical forward/reverse DCF in `valuation.py` varies `ScenarioAssumptions.explicit_growth` through the shared FCFF present-value engine, while `ValuationInput/run_valuation()` contains no revenue-growth input and performs no forward projection — labeling the solved value as Revenue CAGR would be financially false, while introducing a revenue-to-FCFF projection would create a second valuation model prohibited by the architecture.

Ruling: Task 2 must reuse the canonical FCFF valuation engine exposed by `solve_fcff_implied_growth`/its shared `_pv_fcff` path, with Executive Shortlist bounds, tolerance, iteration/status semantics layered at the executive orchestration boundary — duplicating the present-value formula is prohibited.
