# Financial Kernel Strangler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the duplicate, case-coupled financial path with a generic evidence-to-artifact kernel while retaining explicit legacy compatibility.

**Architecture:** Introduce temporal and lineage contracts first, then a generic accounting/valuation path controlled by typed railway results, and finally adapt legacy cases and presentation upward into `AnalysisArtifact`. Every closure is releasable independently.

**Tech Stack:** Python 3.12, frozen dataclasses, stdlib typing, pytest, Ruff, mypy, uv.

**Spec:** `docs/superpowers/specs/2026-09-16-financial-kernel-strangler-design.md`

## Global constraints

- Follow RED → minimum GREEN → regression for every task.
- Missing required evidence blocks; it never becomes `0`.
- Do not add ticker-specific production branches.
- Debt, cash and marketable securities remain required for EV/WACC.
- Invested capital is optional only as a complete opening/closing NOA pair.
- Do not commit, push, broadly stage, reset or clean.
- After each closure run the exact quality gate in the spec and report actual output.

---

## File map

| Path | Responsibility |
|---|---|
| `financial_temporal.py` | `TTMWindow` and shared endpoint invariants |
| `financial_lineage.py` | immutable metric/evidence lineage |
| `accounting.py` | promoted-input-to-snapshot kernel; no SEC policy imports |
| `financial_promotion.py` | SEC policy adapter and promoted-input builder |
| `valuation.py` | generic valuation input/outcome and formulas |
| `analysis_steps.py` | ROP results and application coordinators |
| `analysis.py` | thin façade and existing status projection |
| `analysis_artifact.py` | UI-independent application handoff |
| `legacy_case_adapter.py` | legacy fixture compatibility into artifact |
| `one.py`, `dashboard/serializer.py`, `agents/*` | artifact-only consumers |

## Closure 1: temporal/accounting kernel

### Task 1: TTMWindow

**Files:** create `src/qhapaq_finance/financial_temporal.py`, `tests/test_financial_temporal.py`; modify `accounting.py`, `financial_promotion.py`.

**Produces:** `TTMWindow(period_start: date, period_end: date)`.

- [ ] Write failing tests:

```python
def test_ttm_window_exposes_balance_endpoints() -> None:
    window = TTMWindow(date(2025, 6, 29), date(2026, 6, 27))
    assert window.opening_balance_date == date(2025, 6, 28)
    assert window.closing_balance_date == date(2026, 6, 27)


def test_ttm_window_rejects_empty_or_reversed_period() -> None:
    with pytest.raises(FinancialKernelError, match="TTM_WINDOW_INVALID"):
        TTMWindow(date(2026, 6, 27), date(2026, 6, 27))
```

- [ ] Run: `uv run --no-sync pytest tests/test_financial_temporal.py -q`; record the RED result.
- [ ] Add the immutable dataclass and replace duplicated opening/closing date arithmetic only where existing accounting tests cover the behavior.
- [ ] Run: `uv run --no-sync pytest tests/test_financial_temporal.py tests/test_accounting.py -q`.

### Task 2: lineage annex

**Files:** create `financial_lineage.py`, `tests/test_financial_lineage.py`; modify `accounting.py`.

**Produces:** `EvidenceRef`, `MetricTrace`, `Lineage` and snapshot lineage.

- [ ] Write a failing test that asserts FCFF lineage is ordered, deduplicated and includes the formula:

```python
def test_lineage_for_derived_fcff_is_ordered_and_deduplicated() -> None:
    trace = Lineage.from_metric_inputs(
        "fcff", ("nopat", "da", "capex", "change_nwc"), "NOPAT + D&A - capex - ΔNWC"
    ).for_metric("fcff")
    assert trace.evidence_ids == ("nopat", "da", "capex", "change_nwc")
```

- [ ] Run: `uv run --no-sync pytest tests/test_financial_lineage.py -q`; record RED.
- [ ] Implement lineage composition in accounting boundaries. Keep `calculate_fcff()` and every primitive numeric-only.
- [ ] Run: `uv run --no-sync pytest tests/test_financial_lineage.py tests/test_accounting.py -q`.

### Task 3: explicit NOA pair

**Files:** modify `accounting.py`, `tests/test_accounting.py`.

**Produces:** `InvestedCapitalPair | None` and ROIC availability semantics.

- [ ] Write failing tests for both-noa-absent, one-sided NOA, and endpoint-mismatched NOA.
- [ ] Run: `uv run --no-sync pytest tests/test_accounting.py -k 'noa or invested_capital' -q`; record RED.
- [ ] Implement the pair constructor: accept two compatible endpoints or neither; raise `NOA_PAIR_INCOMPLETE` otherwise. FCFF must not reference the pair.
- [ ] Run: `uv run --no-sync pytest tests/test_accounting.py tests/test_financial_promotion.py -q`.

### Closure 1 verification

- [ ] Run the full quality gate specified in the design document. Do not claim success without its output.

## Closure 2: generic valuation and railway pipeline

### Task 4: remove accounting/promotion schema reflection

**Files:** modify `financial_promotion.py`, `accounting.py`, `tests/test_financial_promotion.py`.

**Produces:** `PromotedFinancialInputs` and domain-owned metric groups.

- [ ] Write a failing test asserting that `FCFF_REQUIRED`, `CLOSING_CAPITAL_STRUCTURE_REQUIRED`, and `NOA_OPTIONAL_PAIR` each have declared policies.
- [ ] Run: `uv run --no-sync pytest tests/test_financial_promotion.py -k coverage -q`; record RED.
- [ ] Build `PromotedFinancialInputs` in the SEC adapter. Remove every import of `financial_promotion` from accounting, including function-local imports.
- [ ] Run: `uv run --no-sync pytest tests/test_financial_promotion.py tests/test_accounting.py -q`.

### Task 5: canonical valuation input/output

**Files:** modify `valuation.py`, create `tests/test_generic_valuation.py`, modify `tests/test_valuation.py`.

**Produces:** `ValuationInputs` and `ValuationOutcome`.

- [ ] Write failing tests:

```python
def test_generic_valuation_runs_reverse_dcf_without_invested_capital() -> None:
    outcome = value(ValuationInputs(accounting_without_noa, canonical_wacc, market, assumptions))
    assert outcome.fcff == accounting_without_noa.fcff
    assert outcome.roic is None


def test_generic_valuation_rejects_missing_debt_even_when_fcff_exists() -> None: ...
```

- [ ] Run: `uv run --no-sync pytest tests/test_generic_valuation.py -q`; record RED.
- [ ] Make the generic route consume `AccountingSnapshot`, `CapitalCostResult`, and `MarketInput`; retain `ResearchCase` only as a compatibility route.
- [ ] Run: `uv run --no-sync pytest tests/test_generic_valuation.py tests/test_valuation.py tests/test_capital_cost.py -q`.

### Task 6: ROP coordinators

**Files:** create `analysis_steps.py`, `tests/test_analysis_steps.py`; modify `analysis.py`, `tests/test_analysis.py`.

**Produces:** `StepSuccess[T]`, `StepBlocked`, `BlockReason`, `bind`, and one coordinator per specified node.

- [ ] Write a failing short-circuit test:

```python
def test_pipeline_stops_at_first_block_without_calling_downstream_node() -> None:
    blocked = StepBlocked(BlockReason("DEBT_EVIDENCE_REQUIRED", "debt missing"))
    assert bind(blocked, lambda _: pytest.fail("must not run")) == blocked
```

- [ ] Run: `uv run --no-sync pytest tests/test_analysis_steps.py -q`; record RED.
- [ ] Implement result combinators and coordinator nodes. The façade may project final status but may not own accounting, WACC, or valuation logic.
- [ ] Run: `uv run --no-sync pytest tests/test_analysis_steps.py tests/test_analysis.py tests/test_sec_corpus.py -q`.

### Closure 2 verification

- [ ] Run the full quality gate specified in the design document. Do not claim success without its output.

## Closure 3: artifact, legacy adapter and presentation

### Task 7: AnalysisArtifact

**Files:** create `analysis_artifact.py`, `tests/test_analysis_artifact.py`; modify `analysis.py`.

**Produces:** immutable artifact and deterministic executive conclusion.

- [ ] Write failing tests for artifact content-identity changes from lineage and for an unavailable ROIC that does not block valuation.
- [ ] Run: `uv run --no-sync pytest tests/test_analysis_artifact.py -q`; record RED.
- [ ] Implement artifact construction and conclusion fields for observed, calculated, unavailable and conditional states.
- [ ] Run: `uv run --no-sync pytest tests/test_analysis_artifact.py tests/test_analysis.py -q`.

### Task 8: legacy adapter upward

**Files:** create `legacy_case_adapter.py`; modify `qcom_case.py`, `nvda_case.py`, `tests/test_qcom_evidence.py`, `tests/test_nvda_evidence.py`.

**Produces:** legacy `AnalysisArtifact` with preserved source mode.

- [ ] Write a failing test that adapts QCOM and asserts `artifact.evidence.source_mode == "legacy"` and a valid valuation output.
- [ ] Run: `uv run --no-sync pytest tests/test_qcom_evidence.py tests/test_nvda_evidence.py -q`; record RED.
- [ ] Implement the adapter at the application boundary; it must preserve legacy provenance and may not claim canonical SEC promotion.
- [ ] Run: `uv run --no-sync pytest tests/test_qcom_evidence.py tests/test_nvda_evidence.py tests/test_analysis_artifact.py -q`.

### Task 9: artifact-only presentation

**Files:** modify `one.py`, `dashboard/serializer.py`, `agents/validation.py`, `tests/test_one.py`, `tests/test_dashboard.py`, `tests/test_agents.py`.

**Produces:** surfaces that consume only `AnalysisArtifact`.

- [ ] Write a failing test that builds One from an artifact and a serializer test monkeypatching `valuation.load_fixture_case` to fail if called.
- [ ] Run: `uv run --no-sync pytest tests/test_one.py tests/test_dashboard.py tests/test_agents.py -q`; record RED.
- [ ] Convert public presentation boundaries. Render artifact gates visibly; do not load a legacy fixture or recalculate finance.
- [ ] Run: `uv run --no-sync pytest tests/test_one.py tests/test_dashboard.py tests/test_agents.py tests/test_explainability.py -q`.

### Closure 3 verification

- [ ] Run the full quality gate specified in the design document. Do not claim success without its output.

## Self-review

- Tasks 1–3 cover temporal, lineage and NOA requirements.
- Tasks 4–6 cover policy isolation, valuation and ROP topology.
- Tasks 7–9 cover artifact creation, legacy inversion and presentation strangulation.
- All named issuers remain adapter regressions; no production task introduces ticker-specific behavior.
- No task stages or commits files.
