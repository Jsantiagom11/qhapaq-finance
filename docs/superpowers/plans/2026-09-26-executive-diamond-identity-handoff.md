# Executive Diamond Authoritative Identity Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve Diamond's authoritative `SecurityRef` through Executive deep analysis so real Diamond candidates do not need an independent ticker-to-CIK resolution before analysis.

**Architecture:** `evaluate_universe()` carries the exact input `SecurityRef` as internal provenance on `DiamondResult`. Production `run_shortlist()` composes those Top-N identities with the existing refreshable `CompanyResolver` and injects the composed resolver into `AnalysisOrchestrator`. Independently, `DeepAnalysisOrchestrator` preserves the first existing blocked lifecycle-stage reason instead of discarding it.

**Tech Stack:** Python 3.12, asyncio, dataclasses, Protocol typing, pytest, Ruff, mypy, uv.

**Spec:** `docs/superpowers/specs/2026-09-24-executive-diamond-identity-handoff-design.md`

## Global Constraints

- Use `uv run --no-sync`.
- Strict RED -> GREEN -> regression -> static checks -> commit.
- Never modify production before proving the owning RED.
- Preserve `.env.example`.
- Preserve `data/cache/sec/company_tickers.json`.
- Preserve the existing Git stash.
- Do not stage runtime caches.
- Diamond ranking, scoring and ordering remain unchanged.
- `dataset_identity` remains unchanged.
- `provider_identity` remains evidence identity only.
- No static ticker allowlist.
- No Dataset Snapshot implementation in this patch.
- Existing `qhapaq analyze TICKER` semantics remain unchanged.
- Existing custom Executive analyzers remain supported.
- Executive never reranks or reclassifies Diamond.
- Public `diamond-funnel-v1` JSON/CSV remains unchanged.

## Review Focus

1. Malformed or missing Diamond identity must not fabricate a CIK.
2. Non-`sec-first` candidates must use normal fallback resolution.
3. Fallback resolver must remain refreshable.
4. `source_security` must remain absent from public Diamond JSON/CSV.
5. Blocked reason selection must follow acquisition -> evidence -> research -> valuation -> publishing.

---

### Task 1: Preserve Diamond source identity

**Files:**
- Modify: `src/qhapaq_finance/diamond/engine.py`
- Modify: `tests/test_diamond_engine.py`
- Modify: `tests/test_diamond_serialization.py`

**Interfaces:**
- Produces: `DiamondResult.source_security: SecurityRef | None = None`
- `evaluate_universe()` copies `ticker`, `security_id`, and `issuer_id` directly from the source `FundamentalRecord`.

- [ ] **Step 1: Write RED identity test**

Add:

`test_evaluate_universe_preserves_exact_source_security`

It must compare `result.source_security` with:

    SecurityRef(
        ticker=record.ticker,
        security_id=record.security_id,
        issuer_id=record.issuer_id,
    )

- [ ] **Step 2: Prove RED**

Run:

    UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest \
      tests/test_diamond_engine.py::test_evaluate_universe_preserves_exact_source_security -q

Expected: FAIL because current `DiamondResult` has no `source_security`.

- [ ] **Step 3: Implement minimal GREEN**

Append to `DiamondResult`:

    source_security: SecurityRef | None = None

Populate it inside `evaluate_universe()` directly from the source record.

Do not derive identity from `provider_identity`.

- [ ] **Step 4: Prove GREEN**

Run the RED test again.

Expected: PASS.

- [ ] **Step 5: Freeze serialization compatibility**

Add:

`test_source_security_is_not_part_of_public_diamond_serialization`

Assert that `source_security` exists internally but does not appear in:
- `diamond_result_dict()`
- canonical Diamond JSON
- CSV header

- [ ] **Step 6: Regression**

Run:

    UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q \
      tests/test_diamond_engine.py \
      tests/test_diamond_serialization.py \
      tests/test_diamond_dataset_identity.py

Expected: PASS.

- [ ] **Step 7: Static checks**

Run Ruff and mypy on modified Diamond files.

- [ ] **Step 8: Commit**

Commit:

    feat: preserve Diamond source security

---

### Task 2: Reuse Diamond identity in Executive

**Files:**
- Create: `src/qhapaq_finance/executive/identity_resolver.py`
- Create: `tests/executive/test_identity_resolver.py`
- Modify: `src/qhapaq_finance/executive/shortlist.py`
- Modify: `tests/executive/test_shortlist.py`

**Interfaces:**

Create:

    class DiamondIdentityResolver:
        def __init__(
            self,
            candidates: Sequence[DiamondResult],
            fallback: RefreshableSymbolResolver,
        ) -> None: ...

        def resolve(self, ticker: str) -> ResolvedCompany | None: ...

        def refresh(self, client: SecClient) -> int: ...

An authoritative hit requires:

- `candidate.provider == "sec-first"`
- `source_security is not None`
- source ticker exactly matches candidate ticker
- `issuer_id` has exact form `sec-cik:<digits>`

Return:

    ResolvedCompany(
        ticker=candidate.ticker,
        company_name=candidate.company_name,
        cik=<exact sec-cik suffix>,
        exchange=None,
        provenance=CompanyProvenance(
            source_url="diamond://sec-first/security-ref",
            fetched_at=None,
            raw_sha256=None,
            raw_byte_size=None,
        ),
    )

Otherwise delegate to the fallback resolver.

`refresh(client)` delegates unchanged to the fallback resolver.

- [ ] **Step 1: Write resolver RED tests**

Test:
- authoritative identity beats fallback
- non-sec-first falls back
- missing source identity falls back
- ticker mismatch falls back
- malformed CIK falls back
- refresh delegates

- [ ] **Step 2: Prove RED**

Run:

    UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q \
      tests/executive/test_identity_resolver.py

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement resolver**

Implement only the behavior specified above.

No static ticker list.

No cache mutation.

- [ ] **Step 4: Prove GREEN**

Run resolver tests again.

Expected: PASS.

- [ ] **Step 5: Prove real AnalysisOrchestrator identity boundary**

Add a test using real `AnalysisOrchestrator` with the new resolver and a fallback that cannot resolve the candidate.

Make the `sec_client_factory` raise if invoked.

Assert that the resulting analysis identity contains the exact supplied CIK.

The test does not require final `COMPLETED` status.

- [ ] **Step 6: Write production wiring RED**

Add:

`test_run_shortlist_injects_diamond_identity_into_default_analysis`

Prove that production:

    run_shortlist
      -> DeepAnalysisOrchestrator
      -> AnalysisOrchestrator
      -> DiamondIdentityResolver

- [ ] **Step 7: Prove RED**

Run only that test.

Expected: FAIL because current production `run_shortlist()` still uses the default independent resolver.

- [ ] **Step 8: Wire production path**

Inside `run_shortlist()`:

1. run Diamond funnel
2. construct existing `CompanyResolver(repository_root)`
3. wrap it in `DiamondIdentityResolver`
4. create `AnalysisOrchestrator(repository_root, resolver=resolver)`
5. create `DeepAnalysisOrchestrator(analyzer=analyzer)`
6. call existing `build_shortlist_from_funnel()`

Do not alter standalone `qhapaq analyze`.

- [ ] **Step 9: Regression**

Run:

    UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q \
      tests/executive/test_identity_resolver.py \
      tests/executive/test_shortlist.py \
      tests/executive/test_shortlist_e2e.py

Expected: PASS.

- [ ] **Step 10: Static checks**

Run Ruff and mypy on Task 2 files.

- [ ] **Step 11: Commit**

Commit:

    feat: reuse Diamond identity in Executive

---

### Task 3: Preserve terminal reasons

**Files:**
- Modify: `src/qhapaq_finance/executive/deep_analysis.py`
- Modify: `tests/executive/test_deep_analysis.py`

**Interfaces:**

Add internal helper:

    def _first_blocked_reason(result: AnalysisResult) -> str | None: ...

Exact lifecycle order:

1. acquisition
2. evidence
3. research
4. valuation
5. publishing

Only stages whose state is `BLOCKED` and whose reason is non-empty qualify.

Do not invent reason text.

- [ ] **Step 1: Write RED tests**

Add:
- `test_terminal_blocked_analysis_preserves_stage_reason`
- `test_first_non_empty_blocked_stage_reason_wins`
- `test_terminal_analysis_without_blocked_reason_keeps_none`

- [ ] **Step 2: Prove RED**

Run the first test.

Expected: FAIL because the current normal-result path writes `reason=None`.

- [ ] **Step 3: Implement reason extraction**

Extract the first existing blocked reason in lifecycle order.

Do not alter exception semantics or concurrency.

- [ ] **Step 4: Prove GREEN**

Run all new reason tests.

Expected: PASS.

- [ ] **Step 5: Regression**

Run:

    UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q \
      tests/executive/test_deep_analysis.py

Expected: PASS.

- [ ] **Step 6: Static checks**

Run Ruff and mypy on Task 3 files.

- [ ] **Step 7: Commit**

Commit:

    fix: preserve Executive analysis block reasons

---

### Task 4: Full acceptance

**Files:**
- No production modification expected.

- [ ] **Step 1: Focused regression**

Run:

    UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q \
      tests/test_diamond_engine.py \
      tests/test_diamond_serialization.py \
      tests/test_diamond_dataset_identity.py \
      tests/test_company_resolver.py \
      tests/executive

Expected: PASS.

- [ ] **Step 2: Full repository regression**

Run:

    UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q

Expected: PASS.

- [ ] **Step 3: Static checks**

Run:

    UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync ruff check .

    UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync mypy src

Expected: PASS.

- [ ] **Step 4: Frozen Diamond replay**

For `2026-09-22`, prove unchanged:

    dataset_identity=46677793154fc2a7888361aa613d9c61db124b5f5b1eb414a4b3ad471a05c2a2
    Top-5=MO,UBER,CRH,BKNG,RMD
    provider_requests=0
    cache_misses=0

- [ ] **Step 5: Executive frozen replay**

Run actual async production `run_shortlist()` with:

    universe_id="sp500"
    as_of=date(2026, 9, 22)
    depth=5

Acceptance requires:

- exact Top-5 order remains MO, UBER, CRH, BKNG, RMD
- none blocks because of `authoritative company resolution could not complete`
- at least one candidate demonstrably crosses the former identity-resolution boundary
- later BLOCKED/EVIDENCE_REQUIRED states expose actual existing reason
- all five do not need to reach COMPLETED

- [ ] **Step 6: Protected state**

Confirm:
- `.env.example` untouched
- `data/cache/sec/company_tickers.json` untouched
- historical stash preserved
- no Dataset Snapshot production implementation
- worktree clean

- [ ] **Step 7: Final report**

Report:

    PROVEN
    UNPROVEN
    REGRESSIONS
    FROZEN REPLAY
    IDENTITY BOUNDARY
    TERMINAL REASONS
    PROTECTED PATHS
    FINAL HEAD

A zero exit code alone is not semantic acceptance.
