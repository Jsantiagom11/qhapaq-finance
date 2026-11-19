# Diamond Funnel V0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Qhapaq Finance's deterministic offline Diamond Funnel discovery layer: provider-neutral canonical fundamentals, robust derived metrics, temporal/peer-safe percentile scoring, four compression scores, three research archetypes, local JSON input, provider-feasibility benchmarking, and CLI surfaces that never invoke deep SEC analysis implicitly.

**Architecture:** New code lives under `src/qhapaq_finance/diamond/` and depends only on stable Python/NumPy primitives plus existing Qhapaq conventions such as `StringEnum` and canonical JSON serialization. Provider normalization is outside the scoring core. The core is pure and deterministic: canonical local input -> validation -> features -> peer resolution -> percentiles -> compression -> archetypes -> diagnostics -> serializable result. Existing SEC acquisition, accounting promotion, Qhapaq One, and `analyze` remain untouched except for adding new CLI command dispatch.

**Tech Stack:** Python >=3.10, dataclasses, pathlib/json/csv, NumPy >=1.24, pytest >=8, Ruff, mypy, existing Qhapaq `StringEnum` and canonical serializer.

**Spec:** `docs/superpowers/specs/2026-09-20-diamond-funnel-design.md` plus the approved V0.1 Implementation Resolution Addendum.

## Global Constraints

- No production code before the owning test has been observed RED for the correct reason.
- Never convert null to zero.
- Never fabricate, forward-fill, or extrapolate missing financial values.
- `operating_cash_flow` means cash from operations after working-capital changes.
- `capital_expenditures` is stored as a positive outflow.
- Generic V0.1 scores only `OPERATING_COMPANY`; financials, insurers, REITs, and UNKNOWN methodology are visible but unranked.
- The scoring engine contains no provider-specific field names and no GICS taxonomy.
- `peer_group_id` is required; peer fallback uses eligible full universe when primary peer count <20.
- Per-feature percentile computation requires at least 8 finite eligible observations.
- Current flow basis is TTM only.
- All records in one screen request must share `data_as_of`.
- Fundamental age must be 0..130 calendar days.
- Peer period-end spread >45 days emits `PEER_PERIOD_DRIFT`; spread >92 days blocks peer percentile scoring.
- PRICE requires `market_age_trading_days <= 3`; otherwise PRICE is null.
- Winsorization is P05/P95 with `np.quantile(..., method="linear")`.
- Original values are retained; only scoring copies are winsorized.
- Ties receive average rank.
- Scores are 0..100 or null.
- `research_priority = max(non-null archetype scores)`.
- Research priority is research routing, never BUY/HOLD/SELL.
- No live FMP/Tiingo calls in V0.1.
- No SQLite/Parquet decision in V0.1.
- No broad screen may invoke SEC filing-native acquisition or Qhapaq One.
- Preserve the existing public contract of `qhapaq analyze`.
- Never stage, edit, revert, or normalize `.env.example` or `data/cache/sec/company_tickers.json`.
- Do not make an implementation commit while the pre-existing SEC feature is still an unrelated dirty stack; implementation should happen only in an explicitly suitable branch/worktree.

## Review Focus

1. **Temporal drift:** two valid TTM records with period ends 93 days apart must not silently share a percentile population.
2. **Sparse feature coverage:** a peer group can contain 20 companies while a feature has only 7 finite values; that feature percentile must still be unavailable.
3. **Share-basis mismatch:** recent point-in-time share counts with unequal split-adjustment basis must never create `RECENT_DILUTION`.
4. **Negative economics:** negative FCF, operating losses, and EV <= 0 must remain economically unfavorable/undefined rather than become attractive through inversion.
5. **Determinism:** shuffled record order, JSON key order, and ties must not change scores or serialized canonical output.

---

## File Map

### Create

- `src/qhapaq_finance/diamond/__init__.py` — public Diamond Funnel exports.
- `src/qhapaq_finance/diamond/contracts.py` — immutable canonical input/output contracts and enums.
- `src/qhapaq_finance/diamond/validation.py` — record and dataset invariants, methodology and temporal eligibility.
- `src/qhapaq_finance/diamond/metrics.py` — pure financial derivations and diagnostics.
- `src/qhapaq_finance/diamond/percentiles.py` — peer resolution, linear winsorization, deterministic average-rank percentiles.
- `src/qhapaq_finance/diamond/scoring.py` — QUALITY/GROWTH/CAPITAL/PRICE.
- `src/qhapaq_finance/diamond/archetypes.py` — COMPOUNDER/QUALITY_VALUE/INFLECTION and research priority.
- `src/qhapaq_finance/diamond/engine.py` — end-to-end offline evaluation.
- `src/qhapaq_finance/diamond/serialization.py` — stable JSON/CSV projection.
- `src/qhapaq_finance/diamond/providers/__init__.py`
- `src/qhapaq_finance/diamond/providers/protocol.py` — provider-neutral protocol.
- `src/qhapaq_finance/diamond/providers/local.py` — canonical local JSON adapter only.
- `src/qhapaq_finance/diamond/providers/benchmark.py` — offline provider-feasibility comparison.
- `tests/test_diamond_contracts.py`
- `tests/test_diamond_validation.py`
- `tests/test_diamond_metrics.py`
- `tests/test_diamond_percentiles.py`
- `tests/test_diamond_scoring.py`
- `tests/test_diamond_archetypes.py`
- `tests/test_diamond_engine.py`
- `tests/test_diamond_serialization.py`
- `tests/test_diamond_local_provider.py`
- `tests/test_diamond_provider_benchmark.py`
- `tests/test_diamond_cli.py`
- `tests/fixtures/diamond/minimal-universe.json`
- `tests/fixtures/diamond/provider-reference.json`
- `tests/fixtures/diamond/provider-candidate.json`

### Modify

- `src/qhapaq_finance/cli.py` — add `screen`, `inspect`, `provider-benchmark` dispatch only.
- `docs/superpowers/specs/2026-09-20-diamond-funnel-design.md` — store the approved specification/addendum.
- `docs/superpowers/plans/2026-09-20-diamond-funnel-v0.1.md` — store this plan.

### Explicitly do not modify

- `src/qhapaq_finance/analysis.py`
- `src/qhapaq_finance/accounting.py`
- `src/qhapaq_finance/financial_promotion.py`
- `src/qhapaq_finance/sec_canonical_gate.py`
- `src/qhapaq_finance/sec_filing_plan.py`
- `src/qhapaq_finance/sec_filing_xbrl.py`
- `.env.example`
- `data/cache/sec/company_tickers.json`

---

## Canonical V0.1 Interfaces

```python
# src/qhapaq_finance/diamond/contracts.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping

from qhapaq_finance.string_enum import StringEnum


class Methodology(StringEnum):
    OPERATING_COMPANY = "OPERATING_COMPANY"
    UNSUPPORTED_FINANCIAL = "UNSUPPORTED_FINANCIAL"
    UNSUPPORTED_INSURER = "UNSUPPORTED_INSURER"
    UNSUPPORTED_REIT = "UNSUPPORTED_REIT"
    UNKNOWN = "UNKNOWN"


class FundamentalPeriodType(StringEnum):
    TTM = "TTM"


class FiscalSlot(StringEnum):
    TTM = "TTM"
    FY1 = "FY1"
    FY2 = "FY2"
    FY3 = "FY3"
    FY4 = "FY4"
    FY5 = "FY5"
    LATEST = "LATEST"


class PeriodKind(StringEnum):
    DURATION = "duration"
    INSTANT = "instant"


class UnitKind(StringEnum):
    CURRENCY = "currency"
    SHARES = "shares"
    RATIO = "ratio"


@dataclass(frozen=True, slots=True)
class FundamentalObservation:
    metric_id: str
    fiscal_slot: FiscalSlot
    value: float
    period_start: date | None
    period_end: date
    period_kind: PeriodKind
    unit_kind: UnitKind
    source_provider: str
    source_identity: str | None = None
    share_class_id: str | None = None
    adjustment_basis_id: str | None = None


@dataclass(frozen=True, slots=True)
class FundamentalRecord:
    ticker: str
    security_id: str
    issuer_id: str
    company_name: str
    currency: str
    peer_group_id: str
    sector: str | None
    industry_group: str | None
    methodology: Methodology
    fiscal_year_end: str | None
    data_as_of: date
    fundamental_period_type: FundamentalPeriodType
    fundamental_period_end: date
    market_age_trading_days: int | None
    provider: str
    provider_identity: str | None
    observations: tuple[FundamentalObservation, ...]
```

`FundamentalRecord` is intentionally a normalized observation container rather than 17 provider-shaped optional attributes. Metric access belongs in pure lookup helpers so provider schemas cannot leak into finance logic.

---

### Task 1: Freeze canonical contracts and temporal/peer invariants

**Files:**
- Create: `src/qhapaq_finance/diamond/__init__.py`
- Create: `src/qhapaq_finance/diamond/contracts.py`
- Create: `src/qhapaq_finance/diamond/validation.py`
- Test: `tests/test_diamond_contracts.py`
- Test: `tests/test_diamond_validation.py`

**Interfaces:**
- Produces the canonical types shown above.
- Produces `validate_record(record: FundamentalRecord) -> tuple[str, ...]`.
- Produces `validate_dataset(records: tuple[FundamentalRecord, ...]) -> tuple[str, ...]`.
- Produces `record_eligible_for_scoring(record: FundamentalRecord) -> bool`.

- [ ] **Step 1: Write RED for required peer identity and finite observations**

Create `tests/test_diamond_contracts.py` with a real `FundamentalRecord` fixture helper and tests that assert:

```python
def test_peer_group_id_is_required() -> None:
    with pytest.raises(DiamondContractError, match="PEER_GROUP_ID_REQUIRED"):
        make_record(peer_group_id="   ")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_observation_is_rejected(value: float) -> None:
    with pytest.raises(DiamondContractError, match="OBSERVATION_NOT_FINITE"):
        make_observation(value=value)
```

The production change that makes the first test pass is contract validation in `FundamentalRecord.__post_init__`. The change for the second is finite-value validation in `FundamentalObservation.__post_init__`.

- [ ] **Step 2: Run RED**

```bash
uv run --no-sync pytest -q \
  tests/test_diamond_contracts.py::test_peer_group_id_is_required \
  tests/test_diamond_contracts.py::test_non_finite_observation_is_rejected
```

Expected: collection/import failure because `qhapaq_finance.diamond.contracts` does not yet exist. This is acceptable only for the first contract RED. After the module exists, every subsequent RED must be a behavioral assertion failure, not an import error.

- [ ] **Step 3: Implement only the immutable enums/dataclasses and constructor validation needed by the RED**

Validation must reject:

```text
blank ticker/security_id/issuer_id/company_name/currency/peer_group_id/provider
non-finite observation value
blank metric_id/source_provider
period_start > period_end
share metadata on non-share units
negative market_age_trading_days
fundamental_period_end > data_as_of
duplicate (metric_id, fiscal_slot) observations
```

No derived metrics in this task.

- [ ] **Step 4: Run GREEN**

```bash
uv run --no-sync pytest -q tests/test_diamond_contracts.py
```

Expected: PASS.

- [ ] **Step 5: Write behavioral REDs for temporal and methodology gates**

```python
def test_dataset_requires_one_data_as_of() -> None:
    records = (
        make_record(ticker="AAA", data_as_of=date(2026, 9, 20)),
        make_record(ticker="BBB", data_as_of=date(2026, 9, 19)),
    )
    with pytest.raises(DiamondValidationError, match="DATA_AS_OF_MISMATCH"):
        validate_dataset(records)


def test_fundamental_older_than_130_days_is_not_score_eligible() -> None:
    record = make_record(
        data_as_of=date(2026, 9, 20),
        fundamental_period_end=date(2026, 5, 12),  # 131 days
    )
    assert not record_eligible_for_scoring(record)


@pytest.mark.parametrize(
    "methodology",
    [
        Methodology.UNSUPPORTED_FINANCIAL,
        Methodology.UNSUPPORTED_INSURER,
        Methodology.UNSUPPORTED_REIT,
        Methodology.UNKNOWN,
    ],
)
def test_only_operating_company_is_generic_score_eligible(methodology: Methodology) -> None:
    assert not record_eligible_for_scoring(make_record(methodology=methodology))
```

- [ ] **Step 6: Run RED, implement minimum validation, run GREEN**

```bash
uv run --no-sync pytest -q tests/test_diamond_validation.py
```

- [ ] **Step 7: Run focused static gates**

```bash
uv run --no-sync ruff check \
  src/qhapaq_finance/diamond/contracts.py \
  src/qhapaq_finance/diamond/validation.py \
  tests/test_diamond_contracts.py \
  tests/test_diamond_validation.py

uv run --no-sync mypy --no-incremental \
  src/qhapaq_finance/diamond/contracts.py \
  src/qhapaq_finance/diamond/validation.py
```

Deliverable: immutable provider-neutral contract with explicit cohort, methodology, TTM basis, temporal cutoff, and no finance calculations.

---

### Task 2: Local canonical JSON adapter

**Files:**
- Create: `src/qhapaq_finance/diamond/providers/__init__.py`
- Create: `src/qhapaq_finance/diamond/providers/protocol.py`
- Create: `src/qhapaq_finance/diamond/providers/local.py`
- Create: `tests/test_diamond_local_provider.py`
- Create: `tests/fixtures/diamond/minimal-universe.json`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class SecurityRef:
    ticker: str
    security_id: str
    issuer_id: str


class FundamentalDataProvider(Protocol):
    def universe(self, universe_id: str, as_of: date) -> tuple[SecurityRef, ...]: ...
    def fundamentals(
        self,
        securities: tuple[SecurityRef, ...],
        as_of: date,
        history_years: int = 5,
    ) -> tuple[FundamentalRecord, ...]: ...


class LocalJsonProvider:
    def __init__(self, path: Path) -> None: ...
```

Canonical fixture root:

```json
{
  "schema_version": "diamond-fundamentals-v1",
  "universe_id": "test-operating",
  "data_as_of": "2026-09-20",
  "records": []
}
```

- [ ] **Step 1: RED for schema version and null preservation**

```python
def test_local_provider_rejects_unknown_schema(tmp_path: Path) -> None:
    path = tmp_path / "fundamentals.json"
    path.write_text('{"schema_version":"wrong","records":[]}', encoding="utf-8")
    with pytest.raises(LocalProviderError, match="SCHEMA_VERSION_UNSUPPORTED"):
        LocalJsonProvider(path)


def test_local_provider_preserves_missing_metric_as_missing() -> None:
    provider = LocalJsonProvider(FIXTURE)
    record = provider.fundamentals(
        provider.universe("test-operating", date(2026, 9, 20)),
        date(2026, 9, 20),
    )[0]
    assert observation(record, "marketable_securities", FiscalSlot.LATEST) is None
```

- [ ] **Step 2: RED**

```bash
uv run --no-sync pytest -q tests/test_diamond_local_provider.py
```

- [ ] **Step 3: Implement strict local JSON parsing**

The adapter must:

```text
reject unknown schema_version
reject duplicate tickers/security ids
reject malformed ISO dates
reject bool as numeric
preserve absent metric as absent
construct the canonical dataclasses
never change signs except when fixture already declares canonical positive capex
never infer methodology/peer_group_id
```

- [ ] **Step 4: GREEN and focused gates**

```bash
uv run --no-sync pytest -q tests/test_diamond_local_provider.py
uv run --no-sync ruff check src/qhapaq_finance/diamond/providers tests/test_diamond_local_provider.py
uv run --no-sync mypy --no-incremental src/qhapaq_finance/diamond/providers
```

Deliverable: reproducible offline canonical input, no network.

---

### Task 3: Pure financial metrics and boundary conditions

**Files:**
- Create: `src/qhapaq_finance/diamond/metrics.py`
- Create: `tests/test_diamond_metrics.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class CompressedMetrics:
    revenue_ttm: float | None
    operating_income_ttm: float | None
    operating_margin_ttm: float | None
    operating_cash_flow_ttm: float | None
    capex_ttm: float | None
    fcf_ttm: float | None
    fcf_margin_ttm: float | None
    cash_and_marketable_securities: float | None
    total_debt: float | None
    net_debt: float | None
    diluted_shares: float | None
    share_dilution_3y: float | None
    market_cap: float | None
    enterprise_value: float | None
    normalized_fcf_yield: float | None


@dataclass(frozen=True, slots=True)
class AnalyticalFeatures:
    normalized_fcf: float | None
    normalized_fcf_margin: float | None
    revenue_cagr_3y: float | None
    revenue_cagr_5y: float | None
    fcf_margin_trend: float | None
    operating_margin_trend: float | None
    effective_tax_rate: float | None
    roic_proxy: float | None
    cash_conversion: float | None
    recent_share_change: float | None
    net_debt_to_operating_income: float | None
    margin_dispersion: float | None
    fcf_margin_dispersion: float | None
    negative_fcf_ratio: float | None
    net_cash_indicator: float | None
    ebit_ev_yield: float | None
    peak_ttm_ratio: float | None


@dataclass(frozen=True, slots=True)
class FinancialFeatureSet:
    metrics: CompressedMetrics
    features: AnalyticalFeatures
    diagnostics: tuple[str, ...]


def derive_financial_features(record: FundamentalRecord) -> FinancialFeatureSet: ...
```

- [ ] **Step 1: RED FCF sign and no double working-capital adjustment**

```python
def test_fcf_is_ocf_minus_positive_capex() -> None:
    record = make_financial_record(operating_cash_flow_ttm=120.0, capex_ttm=35.0)
    result = derive_financial_features(record)
    assert result.metrics.fcf_ttm == pytest.approx(85.0)
```

- [ ] **Step 2: RED normalized FCF requires at least 3 observations and uses median**

```python
def test_normalized_fcf_is_median_of_ttm_and_fy1_to_fy3() -> None:
    record = make_financial_record(
        fcf_ttm=200.0,
        fcf_fy1=100.0,
        fcf_fy2=80.0,
        fcf_fy3=60.0,
    )
    assert derive_financial_features(record).features.normalized_fcf == pytest.approx(90.0)


def test_normalized_fcf_requires_three_non_null_observations() -> None:
    record = make_financial_record(fcf_ttm=100.0, fcf_fy1=90.0)
    assert derive_financial_features(record).features.normalized_fcf is None
```

- [ ] **Step 3: RED for FCF-margin trend, not FCF percentage growth**

Use FY margins:

```text
FY1  12%
FY2  10%
FY3   9%
FY4   9%
deltas = 2pp, 1pp, 0pp
median = 1pp = 0.01
```

```python
def test_growth_feature_uses_fcf_margin_trend() -> None:
    result = derive_financial_features(record_with_fcf_margin_history(0.12, 0.10, 0.09, 0.09))
    assert result.features.fcf_margin_trend == pytest.approx(0.01)
```

- [ ] **Step 4: RED recent dilution basis consistency**

```python
def test_recent_share_change_requires_matching_share_basis() -> None:
    record = make_share_record(
        latest=102.5,
        fy1_end=100.0,
        latest_basis="split-v2",
        fy1_basis="split-v1",
    )
    result = derive_financial_features(record)
    assert result.features.recent_share_change is None
    assert "CURRENT_SHARE_SERIES_INCONSISTENT" in result.diagnostics


def test_recent_dilution_diagnostic_starts_at_two_percent() -> None:
    result = derive_financial_features(make_share_record(latest=102.0, fy1_end=100.0))
    assert result.features.recent_share_change == pytest.approx(0.02)
    assert "RECENT_DILUTION" in result.diagnostics
```

- [ ] **Step 5: RED negative/undefined economics**

Pin all boundaries separately:

```text
revenue <= 0 -> revenue-derived ratios null
operating_income <= 0 -> leverage ratio + EBIT/EV yield null + OPERATING_LOSS
normalized FCF <= 0 -> preserve non-positive normalized FCF yield
EV <= 0 -> EBIT/EV yield null
non-positive CAGR endpoint -> CAGR null
invalid effective tax rate -> null
average invested capital <= 0 -> ROIC proxy null
```

- [ ] **Step 6: Implement one formula at a time, alternating RED -> GREEN**

Do not batch all formulas before running tests.

- [ ] **Step 7: Focused GREEN**

```bash
uv run --no-sync pytest -q tests/test_diamond_metrics.py
```

Deliverable: finance logic independent of scoring/provider.

---

### Task 4: Peer resolution, temporal coherence, winsorization, and percentile ranks

**Files:**
- Create: `src/qhapaq_finance/diamond/percentiles.py`
- Create: `tests/test_diamond_percentiles.py`

**Interfaces:**

```python
class Direction(StringEnum):
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"


@dataclass(frozen=True, slots=True)
class PercentilePolicy:
    primary_peer_minimum: int = 20
    feature_observation_minimum: int = 8
    winsor_lower: float = 0.05
    winsor_upper: float = 0.95
    soft_period_spread_days: int = 45
    hard_period_spread_days: int = 92


@dataclass(frozen=True, slots=True)
class PercentileResult:
    percentile: float | None
    original_value: float | None
    scored_value: float | None
    peer_scope: str
    peer_count: int
    diagnostics: tuple[str, ...]


def linear_winsor_bounds(
    values: tuple[float, ...], policy: PercentilePolicy
) -> tuple[float, float]: ...
def empirical_percentile(
    values: tuple[float, ...], target: float, direction: Direction
) -> float: ...
```

- [ ] **Step 1: RED the exact NumPy interpolation**

```python
def test_winsorization_uses_explicit_linear_quantiles_for_eight_values() -> None:
    values = (0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 100.0)
    lower, upper = linear_winsor_bounds(values, PercentilePolicy())
    assert lower == pytest.approx(0.35)
    assert upper == pytest.approx(67.10)
```

This pins `np.quantile(..., method="linear")`; using `nearest`, `midpoint`, or an implicit default must fail.

- [ ] **Step 2: RED average-rank ties**

```python
def test_percentile_ties_receive_average_rank() -> None:
    values = (10.0, 20.0, 20.0, 40.0)
    first = empirical_percentile(values, 20.0, Direction.HIGHER_IS_BETTER)
    assert first == pytest.approx(50.0)
```

Ranks for tied 20s are 2 and 3 -> average rank 2.5 -> `(2.5 - 1) / 3 * 100 = 50`.

- [ ] **Step 3: RED orientation**

```python
def test_lower_is_better_is_exact_inverse() -> None:
    values = (1.0, 2.0, 3.0, 4.0)
    high = empirical_percentile(values, 3.0, Direction.HIGHER_IS_BETTER)
    low = empirical_percentile(values, 3.0, Direction.LOWER_IS_BETTER)
    assert high + low == pytest.approx(100.0)
```

- [ ] **Step 4: RED sparse observations despite large peer**

Construct 20 eligible records where only 7 have the feature. Assert percentile is null and includes `INSUFFICIENT_PEER_OBSERVATIONS`.

- [ ] **Step 5: RED peer fallback**

Construct 19 records in `peer_group_id="A"` plus >=20 eligible universe records. Assert the record's percentile uses `peer_scope="ELIGIBLE_UNIVERSE"`.

Construct 20 records in `"A"`. Assert `peer_scope="A"`.

- [ ] **Step 6: RED time drift**

```text
spread 45 -> allowed, no PEER_PERIOD_DRIFT
spread 46 -> allowed, PEER_PERIOD_DRIFT
spread 92 -> allowed, PEER_PERIOD_DRIFT
spread 93 -> percentile unavailable, PEER_PERIOD_MISALIGNED
```

- [ ] **Step 7: Implement minimum percentile engine and run GREEN**

```bash
uv run --no-sync pytest -q tests/test_diamond_percentiles.py
```

Deliverable: mathematically pinned cross-sectional engine.

---

### Task 5: Deterministic compression scores

**Files:**
- Create: `src/qhapaq_finance/diamond/scoring.py`
- Create: `tests/test_diamond_scoring.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class CategoryScores:
    quality: float | None
    growth: float | None
    capital: float | None
    price: float | None


def score_categories(
    features: FinancialFeatureSet,
    percentiles: Mapping[str, float | None],
    *,
    market_fresh: bool,
) -> CategoryScores: ...
```

Weights are exact:

```text
QUALITY
35% ROIC_PROXY
25% normalized FCF margin
20% cash conversion
10% operating-margin stability
10% FCF stability

GROWTH
45% revenue CAGR 5Y
25% revenue CAGR 3Y
20% FCF-margin trend
10% operating-margin trend

CAPITAL
35% inverse net-debt / operating-income
20% inverse share-dilution 3Y
15% inverse recent-share-change
20% ROIC_PROXY
10% net-cash indicator

PRICE
60% normalized FCF yield
40% EBIT / EV yield
```

- [ ] **Step 1: RED QUALITY minimum coverage and weight renormalization**

Assert:
- 2/5 available -> null.
- 3/5 available but neither ROIC nor cash conversion -> null.
- 3/5 including ROIC -> weighted average over only valid weights, normalized by sum of those weights.

- [ ] **Step 2: RED GROWTH minimum**

Assert revenue CAGR 3Y is mandatory and at least 2 components total are required.

- [ ] **Step 3: RED CAPITAL recent dilution overlay**

Pin a case where all other CAPITAL components are identical and `recent_share_change` percentile differs. The record with worse recent dilution must have the lower CAPITAL score.

When recent-share-change is null, its 15% weight must be removed and remaining valid weights renormalized.

- [ ] **Step 4: RED PRICE freshness and primary FCF-yield requirement**

```python
def test_stale_market_data_nulls_price_only() -> None:
    scores = score_categories(features, percentiles, market_fresh=False)
    assert scores.price is None
    assert scores.quality is not None
```

Also assert PRICE is null if normalized FCF yield percentile is missing even when EBIT/EV exists.

- [ ] **Step 5: Implement minimal weighted scoring and GREEN**

```bash
uv run --no-sync pytest -q tests/test_diamond_scoring.py
```

Deliverable: four transparent, deterministic category scores.

---

### Task 6: Archetypes, research priority, and deterministic diagnostics

**Files:**
- Create: `src/qhapaq_finance/diamond/archetypes.py`
- Create: `tests/test_diamond_archetypes.py`

**Interfaces:**

```python
class Archetype(StringEnum):
    COMPOUNDER = "COMPOUNDER"
    QUALITY_VALUE = "QUALITY_VALUE"
    INFLECTION = "INFLECTION"


@dataclass(frozen=True, slots=True)
class ArchetypeScores:
    compounder: float | None
    quality_value: float | None
    inflection: float | None
    research_priority: float | None
    surfaced_by: Archetype | None


def score_archetypes(
    categories: CategoryScores,
    *,
    margin_trend_percentile: float | None,
) -> ArchetypeScores: ...
```

Exact formulas:

```text
COMPOUNDER    = 0.45 QUALITY + 0.35 GROWTH + 0.20 CAPITAL
QUALITY_VALUE = 0.40 QUALITY + 0.35 PRICE  + 0.25 CAPITAL
INFLECTION    = 0.35 GROWTH + 0.25 QUALITY + 0.20 margin_trend_percentile + 0.20 PRICE
RESEARCH_PRIORITY = max(non-null archetype scores)
```

An archetype is null if any input required by its formula is null.

- [ ] **Step 1: RED exact formulas**

Use simple category values where hand calculation is obvious and assert exact expected scores.

- [ ] **Step 2: RED research priority chooses max**

Assert max of three non-null scores.

- [ ] **Step 3: RED deterministic tie**

If two archetypes tie exactly, tie order is:

```text
COMPOUNDER
QUALITY_VALUE
INFLECTION
```

This is a deterministic serialization tie-break only, not an economic preference.

- [ ] **Step 4: GREEN**

```bash
uv run --no-sync pytest -q tests/test_diamond_archetypes.py
```

Deliverable: research routing separated from investment recommendation.

---

### Task 7: End-to-end Diamond engine and explainability record

**Files:**
- Create: `src/qhapaq_finance/diamond/engine.py`
- Create: `tests/test_diamond_engine.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class DiamondResult:
    schema_version: str
    ticker: str
    data_as_of: date
    peer_scope: str | None
    peer_count: int
    metrics: CompressedMetrics
    scores: CategoryScores
    archetypes: ArchetypeScores
    percentiles: Mapping[str, float | None]
    diagnostics: tuple[str, ...]
    coverage: Mapping[str, str]


def evaluate_universe(
    records: tuple[FundamentalRecord, ...],
    *,
    policy: PercentilePolicy = PercentilePolicy(),
) -> tuple[DiamondResult, ...]: ...
```

- [ ] **Step 1: RED unsupported methodology remains visible but unranked**

JPM-like fixture with `UNSUPPORTED_FINANCIAL`:

```text
result exists
research_priority = null
diagnostic includes UNSUPPORTED_METHODOLOGY
not part of percentile peer population
```

O-like fixture with `UNSUPPORTED_REIT`: same.

- [ ] **Step 2: RED input order does not affect output**

Evaluate a universe and the reversed tuple. Compare canonical per-ticker results byte-for-byte after sorting by ticker.

- [ ] **Step 3: RED cyclic peak diagnostic**

TTM FCF >=1.75x positive normalized FCF emits `CYCLICAL_PEAK_RISK` but does not automatically null research priority.

- [ ] **Step 4: RED current dilution and stale market diagnostics compose**

A record may have `RECENT_DILUTION` and `MARKET_DATA_STALE`; PRICE null must not erase QUALITY/GROWTH/CAPITAL.

- [ ] **Step 5: Implement orchestration and GREEN**

```bash
uv run --no-sync pytest -q tests/test_diamond_engine.py
```

Deliverable: pure offline universe evaluator.

---

### Task 8: Stable JSON and CSV output

**Files:**
- Create: `src/qhapaq_finance/diamond/serialization.py`
- Create: `tests/test_diamond_serialization.py`

**Interfaces:**

```python
def diamond_result_dict(result: DiamondResult) -> dict[str, object]: ...
def canonical_diamond_json(results: tuple[DiamondResult, ...]) -> str: ...
def diamond_csv(results: tuple[DiamondResult, ...]) -> str: ...
```

- [ ] **Step 1: RED null remains JSON null**

No unavailable number may serialize as zero, empty string, NaN, or Infinity.

- [ ] **Step 2: RED deterministic bytes**

Two evaluations with reversed input order must produce identical canonical JSON.

JSON rules:

```python
json.dumps(
    payload,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=False,
    allow_nan=False,
)
```

The outer result order is deterministic by descending non-null research priority, then ticker; unranked records follow ranked records sorted by ticker.

- [ ] **Step 3: RED exactly 15 public compressed metric keys**

Assert the public `metrics` object has exactly the spec's 15 stable keys.

- [ ] **Step 4: RED CSV columns are stable**

Pin an explicit header sequence rather than relying on dataclass or dict iteration.

- [ ] **Step 5: Implement and GREEN**

```bash
uv run --no-sync pytest -q tests/test_diamond_serialization.py
```

Deliverable: machine-stable output contract.

---

### Task 9: Offline provider-feasibility benchmark harness

**Files:**
- Create: `src/qhapaq_finance/diamond/providers/benchmark.py`
- Create: `tests/test_diamond_provider_benchmark.py`
- Create: `tests/fixtures/diamond/provider-reference.json`
- Create: `tests/fixtures/diamond/provider-candidate.json`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class ProviderBenchmarkResult:
    provider: str
    record_count: int
    identity_pass_rate: float
    required_family_coverage: float
    period_identity_pass_rate: float
    sign_semantics_pass_rate: float
    share_basis_pass_rate: float
    canonical_parse_pass_rate: float
    calls_per_ticker: float | None
    batch_size: int | None
    latency_ms: float | None
    estimated_cost_usd: float | None
    diagnostics: tuple[str, ...]


def benchmark_provider_sample(
    *,
    reference: LocalJsonProvider,
    candidate: LocalJsonProvider,
    operational_metadata: Mapping[str, object] | None = None,
) -> ProviderBenchmarkResult: ...
```

This task does **not** call FMP/Tiingo.

- [ ] **Step 1: RED semantic coverage differs from raw field count**

A candidate with many irrelevant fields but missing OCF must score worse required-family coverage than a smaller canonical candidate.

- [ ] **Step 2: RED period mismatch**

Quarterly revenue supplied as TTM must fail period identity even if numeric value is plausible.

- [ ] **Step 3: RED capex sign mismatch**

Negative candidate capex against canonical positive-outflow reference must fail sign semantics.

- [ ] **Step 4: RED split-basis mismatch**

Incompatible share bases must be exposed in benchmark diagnostics, not silently reconciled.

- [ ] **Step 5: Implement and GREEN**

```bash
uv run --no-sync pytest -q tests/test_diamond_provider_benchmark.py
```

Deliverable: empirical adapter decision tool without provider lock-in.

---

### Task 10: CLI product surface without touching `analyze`

**Files:**
- Modify: `src/qhapaq_finance/cli.py`
- Create: `tests/test_diamond_cli.py`

**Interfaces:**

V0.1 local-first commands:

```bash
qhapaq screen --input PATH [--depth 25] [--sector TEXT] [--archetype NAME] [--as-of YYYY-MM-DD] [--format table|json|csv]
qhapaq inspect TICKER --input PATH [--format table|json]
qhapaq provider-benchmark --reference PATH --candidate PATH [--metadata PATH] [--format table|json]
```

`--input` is required in V0.1 because live provider selection is deliberately deferred.

- [ ] **Step 1: RED screen JSON is isolated from `analyze`**

Monkeypatch `AnalysisOrchestrator.analyze` to raise if invoked. Run `cli.main(["screen", "--input", fixture, "--format", "json"])`. Assert valid Diamond JSON and no raised forbidden call.

- [ ] **Step 2: RED inspect is explanatory**

Assert output contains ticker, category scores, winning archetype when available, percentiles, coverage, diagnostics, and provider identity.

- [ ] **Step 3: RED stale PRICE remains explicit**

A stale fixture must show `price=null`/coverage unavailable in JSON and `MARKET_DATA_STALE` in diagnostics.

- [ ] **Step 4: RED existing analyze dispatch is unchanged**

Keep existing analyze tests green:

```bash
uv run --no-sync pytest -q \
  tests/test_analysis.py::test_analyze_cli_defaults_to_human_view \
  tests/test_analysis.py::test_analyze_cli_json_preserves_canonical_machine_artifact
```

- [ ] **Step 5: Add command dispatch before the existing default `_one(arguments)` branch**

The existing CLI dispatch already has explicit `analyze`, `research`, `compare`, `dashboard`, `universe`, `readiness`, `market`, `investigate`, and `reverse-dcf` branches. Add:

```python
elif arguments and arguments[0] == "screen":
    _screen(arguments[1:])
elif arguments and arguments[0] == "inspect":
    _inspect(arguments[1:])
elif arguments and arguments[0] == "provider-benchmark":
    _provider_benchmark(arguments[1:])
```

before the fallback:

```python
elif arguments and not arguments[0].startswith("-"):
    _one(arguments)
```

No change to the `analyze` branch.

- [ ] **Step 6: GREEN**

```bash
uv run --no-sync pytest -q tests/test_diamond_cli.py tests/test_analysis.py
```

Deliverable: usable local-first discovery/inspection surface.

---

### Task 11: Full regression and application safety gate

**Files:**
- No new behavior.
- May update only documentation if observed commands/results differ.

**Interfaces:** repository-wide verification evidence.

- [ ] **Step 1: Verify no protected path is staged or modified by Diamond work**

```bash
git diff --cached --name-only
git status --short -- .env.example data/cache/sec/company_tickers.json
```

Expected: Diamond implementation never stages either protected path. The pre-existing ticker-cache modification may remain visible and must be reported, not changed.

- [ ] **Step 2: Run publication/lock/format/lint/type gates**

```bash
export UV_CACHE_DIR=/tmp/qhapaq-uv-cache

python3 scripts/check_publication.py
uv lock --check
uv run --no-sync ruff format --check .
uv run --no-sync ruff check .
uv run --no-sync mypy --no-incremental src
```

- [ ] **Step 3: Run complete tests**

```bash
uv run --no-sync pytest
```

Every failure must be reported by test name. No completion claim is allowed from a focused-only green suite.

- [ ] **Step 4: Diff hygiene**

```bash
git diff --check -- . \
  ':(exclude).env.example' \
  ':(exclude)data/cache/sec/company_tickers.json'
```

- [ ] **Step 5: Product acceptance**

```bash
qhapaq screen --input tests/fixtures/diamond/minimal-universe.json --format json
qhapaq inspect AAA --input tests/fixtures/diamond/minimal-universe.json --format json
qhapaq provider-benchmark \
  --reference tests/fixtures/diamond/provider-reference.json \
  --candidate tests/fixtures/diamond/provider-candidate.json \
  --format json
```

Acceptance assertions:

```text
no network request
no SEC acquisition
canonical JSON contains null rather than fabricated zeros
unsupported methodology stays unranked
peer scope + count exposed
temporal diagnostics exposed
all category/archetype math deterministic
same input bytes/semantics => same output bytes
qhapaq analyze existing regressions still pass
```

- [ ] **Step 6: Do not commit automatically**

Because the current preflight contains an unrelated uncommitted SEC feature stack, the implementation runner stops before commit/stage integration. After that feature is deliberately closed and the Diamond work is reviewed, the human partner chooses commit/PR strategy.

---

## Execution Packaging

After this plan is approved, implementation should be delivered as a generated, self-checking bundle rather than a pasted sequence of ad-hoc edits.

The bundle should contain:

```text
diamond-funnel-v0.1/
├── apply.sh
├── manifest.json
├── files/
│   ├── src/qhapaq_finance/diamond/...
│   ├── tests/test_diamond_*.py
│   └── tests/fixtures/diamond/...
└── verify.sh
```

`apply.sh` must:

```text
1. confirm repository root
2. print branch/HEAD/status
3. refuse to overwrite pre-existing Diamond files unless their hash matches the bundle's expected pre-state
4. never touch protected paths
5. copy only Diamond files plus the narrowly-scoped CLI patch
6. stop before git add/commit
```

`verify.sh` must run the complete Task 11 gate set and write an auditable summary under `/tmp`.

The CLI patch must be context-checked. If local `cli.py` has diverged so the expected dispatch anchor is absent, the runner stops without partial modification.

---

## Self-Review

### Spec coverage

- Provider neutrality: Tasks 1–2, 9.
- 15 compressed metrics: Tasks 3, 8.
- FCF normalization/cyclicality: Tasks 3, 7.
- Relative scoring / peer fallback: Task 4.
- Linear winsorization method: Task 4.
- QUALITY/GROWTH/CAPITAL/PRICE exact weights: Task 5.
- Multiple archetypes and max priority: Task 6.
- Unsupported financial/insurance/REIT methodology: Tasks 1, 7.
- Current dilution overlay and split consistency: Tasks 1, 3, 9.
- Temporal granularity/drift: Tasks 1, 4.
- Market staleness: Tasks 1, 5, 7.
- Explainability/output contract: Tasks 7–8.
- CLI boundaries: Task 10.
- No live provider / no storage lock-in: Tasks 2, 9.
- Full regression: Task 11.

### Placeholder scan

No TODO/TBD/“similar to above” implementation gaps remain in the plan. Each task defines concrete interfaces, owning tests, RED command, behavior to implement, and GREEN command.

### Type consistency

`FundamentalRecord` -> `FinancialFeatureSet` -> percentiles -> `CategoryScores` -> `ArchetypeScores` -> `DiamondResult` is the single forward dependency chain. Provider code produces only `FundamentalRecord`; it does not import scoring modules.

### Review-focus tests

All five review-focus risks have explicit owning tests in Tasks 3, 4, 7, and 8.
