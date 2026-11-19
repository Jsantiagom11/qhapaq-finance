# Diamond Funnel Live S&P 500 v0.2 Implementation Plan

**Spec:** `docs/superpowers/specs/2026-09-21-diamond-funnel-live-sp500-v0.2-design.md`

**Goal:** Implement:

    qhapaq funnel --universe sp500 --depth 10

using a real structured provider, canonical Diamond records, the existing
Diamond engine, deterministic cache/replay, and explicit downstream
`qhapaq analyze TICKER`.

## Constraints

- Preserve `.env.example`.
- Preserve `data/cache/sec/company_tickers.json`.
- Preserve the existing stash.
- Do not change Diamond scoring semantics.
- Do not change `qhapaq analyze` semantics.
- Do not bulk-run SEC analysis for the S&P 500.
- Never persist or log `FMP_API_KEY`.
- Provider absence stays null; never fabricate zeroes.
- Canonical capex remains a positive outflow.
- All network behavior must be testable without network access.
- Every production change follows RED -> GREEN -> REFACTOR.

## Tasks

### Task 1 — FMP HTTP boundary
Create:
- `src/qhapaq_finance/diamond/providers/fmp_http.py`
- `tests/test_diamond_fmp_http.py`

Prove:
- successful JSON decoding
- API key excluded from URL/loggable identity
- 401/403 fail immediately
- 429 honors Retry-After
- transient 5xx retries
- malformed JSON fails closed
- API key never leaks in exceptions

### Task 2 — Diamond FMP cache
Create:
- `src/qhapaq_finance/diamond/cache.py`
- `tests/test_diamond_cache.py`

Prove deterministic request identity, canonical serialization, checksums,
atomic writes, corruption detection, replay, and secret exclusion.

### Task 3 — FMP provider mapping
Create:
- `src/qhapaq_finance/diamond/providers/fmp.py`
- provider fixtures
- `tests/test_diamond_fmp_provider.py`

Map provider data into the existing `SecurityRef`, `FundamentalRecord`,
`FundamentalObservation`, fiscal slots, period kinds, units and methodology.

### Task 4 — Acquisition/cache policy
Add cache-first acquisition, refresh behavior, resumability and typed
provider/auth failures.

### Task 5 — Funnel orchestration
Create:
- `src/qhapaq_finance/diamond/funnel.py`
- `tests/test_diamond_funnel.py`

Connect provider -> canonical records -> existing evaluate_universe ->
ranked top-N without importing or calling AnalysisOrchestrator.

### Task 6 — CLI
Add:

    qhapaq funnel --universe sp500 --depth 10

with table/json/csv and `--refresh`.

### Task 7 — Regression
Run Ruff, mypy, pytest, Diamond v0.1 acceptance and protected-path checks.

### Task 8 — Live acceptance
When FMP authentication works:

    qhapaq funnel --universe sp500 --depth 10
    qhapaq funnel --universe sp500 --depth 10
    qhapaq analyze <REAL_SURFACED_TICKER> --json

Prove deterministic cache replay and preserve the real typed analyze result.
