# Financial Kernel Strangler Design

## Status and scope

**Status:** proposed. This document authorizes neither production-code changes nor commits.

**Objective:** establish one generic route from public issuer evidence to FCFF, WACC, reverse DCF, and an explainable application artifact. QCOM and NVDA remain compatibility inputs during migration; neither is a kernel dependency.

**Non-goals:** portfolio optimization, BUY/HOLD/SELL labels, arbitrary price targets, ticker-specific promotion, an XBRL rewrite, or deleting legacy modules in the first three closures.

## Decision

Use a Strangler Fig: a small financial kernel owns temporal, accounting and valuation semantics; SEC/market code adapts external inputs; legacy cases adapt upward into one application artifact.

```text
SEC / market adapters -> promoted financial inputs -> financial kernel
                                                    -> AnalysisArtifact
legacy fixtures -----------------------------------> AnalysisArtifact
                                                    -> CLI / One / dashboard / agents
```

The kernel never imports adapters, presentation, CLI, or legacy cases. No adapter branches on a ticker. Missing required evidence returns a typed block reason; it never becomes zero.

## 1. Interfaces core

### Temporal contract

```python
@dataclass(frozen=True)
class TTMWindow:
    period_start: date
    period_end: date

    def __post_init__(self) -> None:
        if self.period_start >= self.period_end:
            raise FinancialKernelError("TTM_WINDOW_INVALID")

    @property
    def opening_balance_date(self) -> date:
        return self.period_start - timedelta(days=1)

    @property
    def closing_balance_date(self) -> date:
        return self.period_end
```

Promotion derives this window exactly once from revenue TTM. All flow inputs must match start, end and monetary unit. Opening NWC/NOA must end on `opening_balance_date`; closing NWC, cash, securities and debt on `closing_balance_date`. Cover-page shares outstanding remain allowed to have their own valid date semantics.

### Lineage as an annex, not arithmetic metadata

`financial_primitives.py` keeps primitive finite-number signatures. Lineage is not a `TraceableValue[float]`: that would couple arithmetic to SEC provenance and complicate pure tests.

```python
@dataclass(frozen=True)
class EvidenceRef:
    identifier: str
    content_identity: str | None


@dataclass(frozen=True)
class MetricTrace:
    metric: str
    evidence: tuple[EvidenceRef, ...]
    derivation: str | None = None


@dataclass(frozen=True)
class Lineage:
    traces: tuple[MetricTrace, ...]

    def for_metric(self, metric: str) -> MetricTrace: ...
```

Adapters create source traces. Domain boundaries compose them deterministically. An FCFF trace names NOPAT, D&A, capex and change-NWC plus its formula; `calculate_fcff()` receives only numbers. Snapshots, valuation outcomes and artifacts carry the immutable lineage annex.

### Optional invested capital, fail closed

```python
@dataclass(frozen=True)
class InvestedCapitalPair:
    opening_noa: float
    closing_noa: float
    opening_date: date
    closing_date: date

    def average(self) -> float: ...


@dataclass(frozen=True)
class AccountingSnapshot:
    window: TTMWindow
    invested_capital: InvestedCapitalPair | None
    lineage: Lineage

    @property
    def fcff(self) -> float | None: ...

    @property
    def roic(self) -> float | None: ...
```

| Opening NOA | Closing NOA | Result |
|---|---|---|
| present and compatible | present and compatible | `InvestedCapitalPair` |
| absent | absent | `None` |
| present | absent/incompatible/stale/unit-mismatched | `AccountingError("NOA_PAIR_INCOMPLETE")` |
| absent | present | `AccountingError("NOA_PAIR_INCOMPLETE")` |

`fcff` must not read the pair. ROIC, reinvestment-derived growth and ROIC-minus-WACC are `None` when it is absent. Valuation remains valid when FCFF, closing capital structure, market input and WACC are supported.

### Canonical valuation boundary

`valuation.py` stops defining a separate `CapitalCost` or `MarketSnapshot` for the generic path.

```python
@dataclass(frozen=True)
class ValuationInputs:
    accounting: AccountingSnapshot
    capital_cost: CapitalCostResult
    market: MarketInput
    assumptions: ValuationAssumptions


@dataclass(frozen=True)
class ValuationOutcome:
    fcff: float
    enterprise_value: float
    equity_value: float
    reverse_dcf: ReverseDcfOutcome
    roic: float | None
    diagnostics: tuple[Diagnostic, ...]
    lineage: Lineage
```

The constructor rejects missing FCFF, debt, cash, securities, valuation shares or incompatible identities. It permits absent invested capital. Existing `ResearchCase` remains a compatibility input until Closure 3.

### Application handoff

```python
@dataclass(frozen=True)
class AnalysisArtifact:
    schema_version: str
    identity: CompanyIdentity
    research_as_of: date
    window: TTMWindow
    evidence: EvidenceSummary
    accounting: AccountingSnapshot
    market: MarketInput
    capital_cost: CapitalCostResult
    valuation: ValuationOutcome
    conclusion: ExecutiveConclusion
    gates: tuple[Gate, ...]
    lineage: Lineage
    content_identity: str
```

`ExecutiveConclusion` states what is observed, calculated, unavailable and conditional. It contains neither recommendation labels nor target prices. Presenters consume the artifact; they do not load fixtures or recalculate finance.

## 2. Promotion and adapter boundaries

`financial_canonicalization.py` is the SEC/XBRL parser/eligibility adapter. `financial_promotion.py` is the SEC policy adapter. Accounting accepts this transport contract, never raw XBRL or a SEC policy:

```python
@dataclass(frozen=True)
class PromotedFinancialInputs:
    window: TTMWindow
    flows: FlowInputs
    opening_balances: OperatingBalances
    closing_balances: OperatingBalances
    closing_capital_structure: CapitalStructureInputs
    valuation_shares: FinancialFact
    noa: InvestedCapitalFacts | None
    lineage: Lineage
```

Policy coverage is declared by domain groups: `FCFF_REQUIRED`, `CLOSING_CAPITAL_STRUCTURE_REQUIRED`, and `NOA_OPTIONAL_PAIR`. It must not reflect over `AccountingEvidenceSpec`; this removes the accounting/promotion circular dependency. The first migration may retain current fact classes at adapter boundaries, but chooses one kernel period enum with explicit conversions.

## 3. Topology of the orchestrator

Use Railway Oriented Programming with small local types, not an external monad library.

```python
T = TypeVar("T")


@dataclass(frozen=True)
class BlockReason:
    code: str
    message: str
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class StepSuccess(Generic[T]):
    value: T


@dataclass(frozen=True)
class StepBlocked:
    reason: BlockReason


StepResult = StepSuccess[T] | StepBlocked
```

| Coordinator | Input | Success | Block examples |
|---|---|---|---|
| `ResolveCompany` | normalized ticker | `CompanyIdentity` | unsupported ticker |
| `AcquireEvidence` | identity | `EvidenceBundle` | absent corpus/checksum mismatch |
| `PromoteFinancialEvidence` | bundle | `PromotedFinancialInputs` | ambiguous SEC concept/no TTM |
| `BuildAccountingSnapshot` | promoted inputs | `AccountingSnapshot` | endpoint mismatch/partial NOA |
| `LoadMarketInput` | identity, snapshot, date | `MarketInput` | stale/missing market evidence |
| `DeriveCapitalCost` | identity, accounting, market, rates | `CapitalCostResult` | debt/rate/beta absent |
| `RunValuation` | accounting, market, WACC, assumptions | `ValuationOutcome` | invalid valuation contract |
| `BuildAnalysisArtifact` | prior successes | `AnalysisArtifact` | lineage/identity inconsistency |

Each node returns `StepResult`. The façade uses `bind`/`map` and projects only the final state to `AnalysisStatus`; it does not contain a decision tree of financial checks. Planning may report all known gaps but execution stops at the first typed block.

## 4. Legacy inversion and presentation

```python
class LegacyCaseAdapter:
    def build_artifact(self, case: ResearchCase, *, root: Path) -> AnalysisArtifact: ...
```

The adapter is application infrastructure. It maps historical QCOM/NVDA fixtures to an artifact, preserves `source_mode="legacy"`, and must never represent them as canonical SEC promotion. Migrate One, dashboard and agents first to artifact inputs using this adapter. Then direct imports of `qcom_case`, `nvda_case`, and `load_fixture_case()` disappear from presentation.

## 5. Testing and error rules

- Stable errors include `TTM_WINDOW_INVALID`, `NOA_PAIR_INCOMPLETE`, and `CLOSING_BALANCE_ENDPOINT_MISMATCH`.
- `None` is allowed only for an unavailable optional analytical extension; required evidence blocks.
- Kernel tests use synthetic generic facts. AAPL/MSFT/QCOM/NVDA tests are adapter regressions, never branches.
- Comments explain financial invariants, provenance constraints or compatibility decisions only.
- Every closure uses:

```bash
uv lock --check
uv run --no-sync ruff check .
uv run --no-sync mypy src
uv run --no-sync pytest -q
git diff --check
```

## 6. Closures

**Closure 1 — temporal/accounting kernel.** Add `TTMWindow`, `Lineage`, and `InvestedCapitalPair`; adapt promotion output to an accounting input boundary; retain the legacy valuation path. Acceptance: endpoint rules, optional complete NOA, partial-NOA rejection, FCFF independence and deterministic lineage.

**Closure 2 — generic valuation and ROP pipeline.** Add canonical valuation input/output; eliminate duplicate models from the generic route; split `AnalysisOrchestrator` into ROP coordinators. Acceptance: a local SEC corpus completes or blocks explicitly without ticker branching; missing homogeneous NOA does not prevent FCFF/WACC/reverse DCF.

**Closure 3 — compatibility/presentation strangulation.** Add `LegacyCaseAdapter`, migrate One/dashboard/agents to artifacts and retain QCOM/NVDA as regression adapters. Acceptance: both routes render through one presentation contract; no presenter imports a legacy case or fixture loader.

Legacy removal is deferred until canonical coverage replaces it and artifact-equivalence tests exist. Portfolio work waits for stable issuer/security identity, content identity and explicit availability semantics.
