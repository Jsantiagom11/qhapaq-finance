# Diamond Funnel Debt Zero v0.4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the known Diamond Funnel technical debt by making SEC evidence amendment-aware, caching issuer-level canonical fundamentals, withholding unsafe market-cap derivations, and replacing `repr()` dataset hashing with a versioned canonical JSON identity contract.

**Architecture:** Keep the existing S&P 500 → SEC → market → Diamond engine flow, but split SEC handling into a lightweight amendment-aware evidence store and an immutable `CanonicalIssuerSnapshot` cache. Assemble `FundamentalRecord` only after applying current universe metadata and safe market evidence, then hash the assembled dataset through a canonical JSON wire contract before scoring.

**Tech Stack:** Python 3.11+, stdlib `dataclasses`, `Decimal`, `hashlib`, `json`, `pathlib`, existing `SecClient`, existing `DiamondCache`, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-09-22-diamond-funnel-debt-zero-v0.4-design.md`

## Global Constraints

- Do not change Diamond scoring weights, archetype formulas, percentile math, ranking rules, or stale-market thresholds.
- Do not run `AnalysisOrchestrator` across the universe.
- Missing evidence remains missing. No forward fill and no invented zero values.
- No time-based grace rule may convert unverified share counts into trusted market capitalization.
- Capex remains a positive canonical outflow.
- Financials, insurers, and REITs remain visible but unranked under their existing methodologies.
- `qhapaq analyze TICKER` remains unchanged.
- FMP remains optional enrichment and is not required for the broad S&P 500 screen.
- Preserve `.env.example`.
- Preserve `data/cache/sec/company_tickers.json`.
- Preserve the existing stash.
- Do not cache final rankings or the Top N as the performance solution.
- Default SEC soft TTL is 6 hours when `as_of` is within the last 2 calendar days and 7 days for older historical `as_of` values.
- Warm replay acceptance on the existing user machine is `provider_requests=0`, `cache_misses=0`, and acquisition time `<= 10` seconds.

## File Structure

- Create `src/qhapaq_finance/diamond/canonical_json.py`: one canonical scalar/JSON byte contract used by SEC evidence revision and dataset identity.
- Modify `src/qhapaq_finance/sec_client.py`: additive conditional-request support while preserving every existing caller's behavior.
- Create `src/qhapaq_finance/diamond/providers/sec_evidence.py`: SEC manifest/blob store, TTL policy, legacy cache migration, point-in-time fact filtering, semantic evidence revision.
- Create `src/qhapaq_finance/diamond/providers/sec_canonical.py`: immutable issuer snapshot contract, JSON codec, canonical cache identity, SEC accounting canonicalizer.
- Refactor `src/qhapaq_finance/diamond/providers/sec.py`: orchestration only; load issuer snapshots, combine universe metadata, apply market overlay, emit `FundamentalRecord`.
- Extend `src/qhapaq_finance/diamond/providers/market.py`: split-coverage contract and safe market-cap derivation boundary.
- Create `src/qhapaq_finance/diamond/providers/yahoo_splits.py`: cached Yahoo chart split-coverage implementation.
- Modify `src/qhapaq_finance/diamond/contracts.py` and `src/qhapaq_finance/diamond/engine.py`: carry provider/evidence diagnostics into final Diamond diagnostics without altering scoring.
- Modify `src/qhapaq_finance/diamond/providers/sp500.py`: one validator shared by live and cached universe rows.
- Create `src/qhapaq_finance/diamond/dataset_identity.py`: canonical `FundamentalRecord` dataset projection and SHA-256.
- Modify `src/qhapaq_finance/diamond/funnel.py`: call the canonical identity function instead of hashing `repr(records)`.
- Modify `src/qhapaq_finance/diamond/cli.py`: construct new SEC evidence/canonical/split caches under `data/cache/diamond/` while retaining existing CLI flags.

## Review Focus

1. A split event effective on the same date as the SEC share observation must be treated as basis-ambiguous; market cap stays missing rather than guessing pre/post-split basis. Task 5 pins this with `test_same_day_split_basis_is_not_assumed_safe`.
2. A stale SEC manifest with no `ETag` or `Last-Modified` must perform an unconditional GET, not a false `304` path and not silent stale reuse. Task 3 pins this with `test_stale_manifest_without_validators_refetches_unconditionally`.
3. A legacy v0.3 SEC cache entry whose `data_as_of` differs from the requested point-in-time run must not seed the v0.4 manifest. Task 3 pins this with `test_legacy_cache_wrong_as_of_is_not_migrated`.
4. A canonical snapshot whose issuer matches but whose `evidence_revision_sha256` differs from the current manifest must never be returned. Task 4 pins this with `test_canonical_cache_revision_mismatch_is_rejected`.
5. Two securities with distinct tickers but the same CIK must share one accounting canonicalization while retaining distinct security metadata and market overlays. Task 4 pins this with `test_two_share_classes_reuse_one_issuer_snapshot`.

---

### Task 1: Canonical JSON and numeric wire primitives

**Files:**
- Create: `src/qhapaq_finance/diamond/canonical_json.py`
- Create: `tests/test_diamond_canonical_json.py`

**Interfaces:**
- Consumes: Python `int | float | Decimal`, JSON-compatible nested objects.
- Produces: `normalize_decimal(value: int | float | Decimal) -> str`, `canonical_json_bytes(payload: object) -> bytes`, `sha256_canonical_json(payload: object) -> str`.
- Later tasks use these functions for SEC `evidence_revision_sha256`, canonical snapshot identities, and final dataset identity.

- [ ] **Step 1: Write failing tests for canonical decimal normalization**

```python
from decimal import Decimal

import pytest

from qhapaq_finance.diamond.canonical_json import (
    CanonicalJsonError,
    canonical_json_bytes,
    normalize_decimal,
    sha256_canonical_json,
)


def test_decimal_lexical_variants_share_one_canonical_value() -> None:
    assert normalize_decimal(10) == "10"
    assert normalize_decimal(10.0) == "10"
    assert normalize_decimal(Decimal("10.00")) == "10"
    assert normalize_decimal(Decimal("1E+3")) == "1000"


def test_negative_zero_normalizes_to_zero() -> None:
    assert normalize_decimal(-0.0) == "0"
    assert normalize_decimal(Decimal("-0.000")) == "0"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_numbers_fail_closed(value: float) -> None:
    with pytest.raises(CanonicalJsonError, match="CANONICAL_NUMBER_NOT_FINITE"):
        normalize_decimal(value)


def test_canonical_json_bytes_are_key_order_independent() -> None:
    left = {"b": "2", "a": ["1", None]}
    right = {"a": ["1", None], "b": "2"}
    assert canonical_json_bytes(left) == canonical_json_bytes(right)
    assert sha256_canonical_json(left) == sha256_canonical_json(right)
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q tests/test_diamond_canonical_json.py
```

Expected: collection/import failure because `qhapaq_finance.diamond.canonical_json` does not exist.

- [ ] **Step 3: Implement the canonical wire primitives**

Create `src/qhapaq_finance/diamond/canonical_json.py` with this public contract:

```python
from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal, InvalidOperation


class CanonicalJsonError(ValueError):
    pass


def normalize_decimal(value: int | float | Decimal) -> str:
    if isinstance(value, bool):
        raise CanonicalJsonError("CANONICAL_NUMBER_INVALID")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalJsonError("CANONICAL_NUMBER_NOT_FINITE")
        number = Decimal(repr(value))
    elif isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, Decimal):
        number = value
    else:
        raise CanonicalJsonError("CANONICAL_NUMBER_INVALID")
    if not number.is_finite():
        raise CanonicalJsonError("CANONICAL_NUMBER_NOT_FINITE")
    if number == 0:
        return "0"
    try:
        rendered = format(number, "f")
    except InvalidOperation as exc:
        raise CanonicalJsonError("CANONICAL_NUMBER_INVALID") from exc
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def canonical_json_bytes(payload: object) -> bytes:
    try:
        text = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise CanonicalJsonError("CANONICAL_JSON_INVALID") from exc
    return text.encode("utf-8")


def sha256_canonical_json(payload: object) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
```

- [ ] **Step 4: Run focused tests and static checks**

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q tests/test_diamond_canonical_json.py
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync ruff check src/qhapaq_finance/diamond/canonical_json.py tests/test_diamond_canonical_json.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/qhapaq_finance/diamond/canonical_json.py tests/test_diamond_canonical_json.py
git commit -m "feat: add canonical Diamond JSON primitives"
```

---

### Task 2: Add conditional SEC requests without changing existing client semantics

**Files:**
- Modify: `src/qhapaq_finance/sec_client.py` around `SecClient.get`
- Modify: `tests/test_sec_client.py`

**Interfaces:**
- Consumes: existing `SecClient.get(url)` callers unchanged.
- Produces: `SecClient.get(url, *, request_headers: Mapping[str, str] | None = None, accepted_statuses: frozenset[int] = frozenset()) -> SecResponse`.
- Task 3 consumes this to send `If-None-Match` / `If-Modified-Since` and accept HTTP 304 as a valid revalidation response.

- [ ] **Step 1: Write failing tests for conditional headers and accepted 304**

Append tests equivalent to:

```python
def test_get_merges_conditional_headers_without_losing_sec_identity() -> None:
    transport = FakeTransport([SecResponse(304, {"ETag": '"abc"'}, b"")])
    client = SecClient(config(), transport=transport)

    response = client.get(
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
        request_headers={"If-None-Match": '"abc"'},
        accepted_statuses=frozenset({304}),
    )

    assert response.status_code == 304
    sent = transport.calls[0][1]
    assert sent["User-Agent"] == config().headers["User-Agent"]
    assert sent["If-None-Match"] == '"abc"'


def test_unaccepted_304_still_fails_closed() -> None:
    transport = FakeTransport([SecResponse(304, {}, b"")])
    client = SecClient(config(), transport=transport)

    with pytest.raises(SecHttpError, match="HTTP 304"):
        client.get("https://www.sec.gov/data.json")
```

- [ ] **Step 2: Run the two tests and verify RED**

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q \
  tests/test_sec_client.py::test_get_merges_conditional_headers_without_losing_sec_identity \
  tests/test_sec_client.py::test_unaccepted_304_still_fails_closed
```

Expected: first test fails because `SecClient.get` does not accept `request_headers` / `accepted_statuses`.

- [ ] **Step 3: Implement the additive request API**

Change `SecClient.get` so the request headers are built once per attempt:

```python
def get(
    self,
    url: str,
    *,
    request_headers: Mapping[str, str] | None = None,
    accepted_statuses: frozenset[int] = frozenset(),
) -> SecResponse:
    headers = dict(self.config.headers)
    if request_headers:
        headers.update(request_headers)
    for attempt in range(self.max_retries + 1):
        try:
            with self._rate_limiter.request_slot():
                response = self._transport(
                    url,
                    headers,
                    self.connect_timeout,
                    self.read_timeout,
                )
        except OSError:
            if attempt == self.max_retries:
                raise
            self._sleep(self._backoff_delay(attempt))
            continue

        if 200 <= response.status_code < 300 or response.status_code in accepted_statuses:
            return response
        if not self._is_retryable(response.status_code) or attempt == self.max_retries:
            raise SecHttpError(response.status_code, url, response.content)
        self._sleep(self._retry_delay(response.headers, attempt))
    raise AssertionError("unreachable")
```

Do not change `get_json`; its current call to `self.get(url).json()` preserves all existing behavior.

- [ ] **Step 4: Run the complete SEC client tests**

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q tests/test_sec_client.py
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync ruff check src/qhapaq_finance/sec_client.py tests/test_sec_client.py
```

Expected: PASS, including the pre-existing retry/rate-limit tests.

- [ ] **Step 5: Commit**

```bash
git add src/qhapaq_finance/sec_client.py tests/test_sec_client.py
git commit -m "feat: support conditional SEC requests"
```

---

### Task 3: Build the amendment-aware SEC evidence manifest/blob store

**Files:**
- Create: `src/qhapaq_finance/diamond/providers/sec_evidence.py`
- Create: `tests/test_diamond_sec_evidence.py`
- Read/reuse: `src/qhapaq_finance/diamond/cache.py`
- Read/reuse: `src/qhapaq_finance/financial_canonicalization.py`

**Interfaces:**
- Consumes: Task 1 `normalize_decimal` / `sha256_canonical_json`, Task 2 conditional `SecClient.get` API, legacy `DiamondCache` entries.
- Produces:
  - `SecEvidenceManifest`
  - `ResolvedSecEvidence`
  - `SecEvidenceStore.resolve(cik: str, as_of: date, *, refresh: bool = False) -> ResolvedSecEvidence`
  - `SecEvidenceStore.load_facts(resolved: ResolvedSecEvidence) -> tuple[RawFact, ...]`
  - `evidence_revision(facts: tuple[RawFact, ...]) -> str`
- Task 4 uses manifest revision without opening the raw blob when a canonical snapshot already exists.

- [ ] **Step 1: Write failing point-in-time amendment/revision tests**

Create fixtures containing the same economic period in an original `10-Q` and a later `10-Q/A`, then assert:

```python
def test_in_scope_amendment_changes_semantic_revision(tmp_path: Path) -> None:
    payload = companyfacts_with_original_and_amendment(
        amendment_filed="2026-08-15",
        original_value=100.0,
        amended_value=110.0,
    )
    facts = filtered_companyfacts(
        payload,
        source_identity="payload-a",
        as_of=date(2026, 9, 22),
    )
    original_only = tuple(f for f in facts if f.filing_form != "10-Q/A")
    assert evidence_revision(facts) != evidence_revision(original_only)


def test_amendment_after_as_of_does_not_change_historical_revision() -> None:
    payload = companyfacts_with_original_and_amendment(
        amendment_filed="2026-10-01",
        original_value=100.0,
        amended_value=110.0,
    )
    facts = filtered_companyfacts(
        payload,
        source_identity="payload-a",
        as_of=date(2026, 9, 22),
    )
    assert {fact.filing_form for fact in facts} == {"10-Q"}
```

`filtered_companyfacts` must admit `10-K`, `10-K/A`, `10-Q`, `10-Q/A`, require `filing_date <= as_of`, `end <= as_of`, consolidated facts, and empty dimensions.

- [ ] **Step 2: Run amendment tests and verify RED**

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q \
  tests/test_diamond_sec_evidence.py::test_in_scope_amendment_changes_semantic_revision \
  tests/test_diamond_sec_evidence.py::test_amendment_after_as_of_does_not_change_historical_revision
```

Expected: import/definition failure for the new evidence module.

- [ ] **Step 3: Implement `SecEvidenceManifest`, filtering, and semantic revision**

Use immutable contracts:

```python
SEC_EVIDENCE_SCHEMA_VERSION = "diamond-sec-evidence-v1"
RECENT_AS_OF_DAYS = 2
RECENT_TTL = timedelta(hours=6)
HISTORICAL_TTL = timedelta(days=7)

@dataclass(frozen=True, slots=True)
class SecEvidenceManifest:
    schema_version: str
    cik: str
    request_identity: str
    retrieved_at: datetime
    data_as_of: date
    payload_sha256: str
    evidence_revision_sha256: str
    latest_in_scope_filing_date: date | None
    latest_in_scope_accession: str | None
    etag: str | None
    last_modified: str | None
    blob_name: str

@dataclass(frozen=True, slots=True)
class ResolvedSecEvidence:
    manifest: SecEvidenceManifest
    facts: tuple[RawFact, ...] | None
```

The semantic revision payload must sort facts by a stable tuple and encode each fact with original filing form/accession plus normalized value, for example:

```python
def _revision_row(fact: RawFact) -> dict[str, object]:
    return {
        "taxonomy": fact.taxonomy,
        "concept": fact.concept,
        "unit": fact.unit,
        "value": normalize_decimal(fact.value),
        "period_kind": fact.period_kind.value,
        "start": fact.start.isoformat() if fact.start else None,
        "end": fact.end.isoformat(),
        "fiscal_year": fact.fiscal_year,
        "fiscal_period": fact.fiscal_period,
        "filing_form": fact.filing_form,
        "filing_date": fact.filing_date.isoformat(),
        "accession": fact.accession,
        "consolidated": fact.consolidated,
        "dimensions": list(fact.dimensions),
    }
```

- [ ] **Step 4: Write failing manifest freshness/revalidation tests**

Use an injected wall clock and fake SEC HTTP client. Cover all of these named cases:

```python
def test_fresh_manifest_performs_zero_sec_requests(tmp_path: Path) -> None: ...
def test_stale_manifest_with_etag_304_preserves_revision(tmp_path: Path) -> None: ...
def test_stale_manifest_changed_200_replaces_revision(tmp_path: Path) -> None: ...
def test_failed_required_revalidation_is_typed_failure(tmp_path: Path) -> None: ...
def test_stale_manifest_without_validators_refetches_unconditionally(tmp_path: Path) -> None: ...
def test_legacy_cache_wrong_as_of_is_not_migrated(tmp_path: Path) -> None: ...
def test_wrong_cik_fails_closed(tmp_path: Path) -> None: ...
def test_corrupt_blob_fails_closed(tmp_path: Path) -> None: ...
```

For the no-validator review-focus case, assert the second request has neither conditional header and receives a new 200 payload.

For legacy migration, seed `DiamondCache(tmp_path / "sec")` using the existing companyfacts request identity with a different `data_as_of`, call `resolve`, and assert the fake HTTP client is used rather than the legacy payload.

- [ ] **Step 5: Run manifest tests and verify RED**

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q tests/test_diamond_sec_evidence.py
```

Expected: freshness/revalidation tests fail because the store is not implemented.

- [ ] **Step 6: Implement atomic manifest/blob persistence, conditional revalidation, and legacy migration**

`SecEvidenceStore` constructor:

```python
class SecEvidenceStore:
    def __init__(
        self,
        *,
        root: Path,
        client: SecClient | None,
        legacy_cache: DiamondCache | None,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None: ...
```

Required filesystem identities:

```text
index/<sha256(request_identity)>.json
blobs/<payload_sha256>.json
```

Required behavior in `resolve`:

```python
manifest = self._load_manifest(cik, as_of)
if manifest is not None and not refresh and self._fresh(manifest, as_of):
    self.cache_hits += 1
    return ResolvedSecEvidence(manifest, None)

if manifest is None:
    migrated = self._migrate_legacy(cik, as_of)
    if migrated is not None and not refresh and self._fresh(migrated.manifest, as_of):
        self.cache_hits += 1
        return migrated

if self._client is None:
    raise SecEvidenceError("SEC_REVALIDATION_REQUIRED")

response = self._revalidate_or_fetch(manifest, refresh=refresh)
if response.status_code == 304:
    refreshed = replace(manifest, retrieved_at=self._now())
    self._write_manifest(refreshed)
    return ResolvedSecEvidence(refreshed, None)

payload = response.json()
facts = filtered_companyfacts(payload, source_identity=payload_sha, as_of=as_of)
new_manifest = self._store_payload_and_manifest(...)
return ResolvedSecEvidence(new_manifest, facts)
```

Use temp-file + `os.replace` writes for both manifests and blobs, checksum the blob before returning it from `load_facts`, and reject wrong schema/provider/CIK/checksum with typed `SecEvidenceError` codes.

- [ ] **Step 7: Run Task 3 tests and static checks**

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q tests/test_diamond_sec_evidence.py
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync ruff check \
  src/qhapaq_finance/diamond/providers/sec_evidence.py tests/test_diamond_sec_evidence.py
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/qhapaq_finance/diamond/providers/sec_evidence.py tests/test_diamond_sec_evidence.py
git commit -m "feat: add amendment-aware SEC evidence store"
```

---

### Task 4: Cache canonical issuer snapshots and refactor SEC-first assembly

**Files:**
- Create: `src/qhapaq_finance/diamond/providers/sec_canonical.py`
- Modify: `src/qhapaq_finance/diamond/providers/sec.py`
- Modify: `tests/test_diamond_sec_provider.py`
- Create: `tests/test_diamond_sec_canonical.py`

**Interfaces:**
- Consumes: `ResolvedSecEvidence`, `SecEvidenceStore.load_facts`, existing `FundamentalObservation` contracts and promotion primitives.
- Produces:
  - `CANONICAL_SCHEMA_VERSION = "diamond-canonical-issuer-v1"`
  - `SEC_CANONICALIZER_VERSION = "sec-canonicalizer-v2"`
  - `CanonicalIssuerSnapshot`
  - `CanonicalIssuerCache.load(...) -> CanonicalIssuerSnapshot | None`
  - `CanonicalIssuerCache.store(snapshot) -> None`
  - `canonicalize_issuer(...) -> CanonicalIssuerSnapshot | None`
- `SecFirstProvider` becomes orchestration over one snapshot per unique CIK.

- [ ] **Step 1: Write failing canonical snapshot cache tests**

Define the snapshot contract in tests with fields matching the spec:

```python
@dataclass(frozen=True, slots=True)
class CanonicalIssuerSnapshot:
    schema_version: str
    canonicalizer_version: str
    issuer_id: str
    cik: str
    as_of: date
    history_years: int
    evidence_revision_sha256: str
    fundamental_period_type: FundamentalPeriodType
    fundamental_period_end: date
    fiscal_year_end: str | None
    observations: tuple[FundamentalObservation, ...]
```

Test:

```python
def test_canonical_cache_round_trips_snapshot(tmp_path: Path) -> None: ...
def test_canonicalizer_version_change_is_a_cache_miss(tmp_path: Path) -> None: ...
def test_canonical_cache_revision_mismatch_is_rejected(tmp_path: Path) -> None: ...
def test_warm_canonical_hit_does_not_load_raw_blob(tmp_path: Path) -> None: ...
```

For the revision-mismatch review-focus test, write a valid cache document for revision A, request revision B, and assert it is not returned; if the identity points at a document whose internal revision is B-inconsistent, assert `SecCanonicalError("CANONICAL_CACHE_REVISION_MISMATCH")`.

- [ ] **Step 2: Run snapshot tests and verify RED**

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q tests/test_diamond_sec_canonical.py
```

Expected: import failure for `sec_canonical`.

- [ ] **Step 3: Implement snapshot codec and identity**

Canonical request identity must be generated from this exact semantic payload:

```python
identity_payload = {
    "schema_version": CANONICAL_SCHEMA_VERSION,
    "canonicalizer_version": SEC_CANONICALIZER_VERSION,
    "issuer_id": issuer_id,
    "as_of": as_of.isoformat(),
    "history_years": history_years,
    "evidence_revision_sha256": evidence_revision_sha256,
}
request_identity = "sec-canonical:" + sha256_canonical_json(identity_payload)
```

Store snapshots under `data/cache/diamond/canonical/` through `DiamondCache`. Serialize observations explicitly; do not use `repr` or pickle.

- [ ] **Step 4: Write failing amendment-aware canonicalization tests**

Add cases proving Diamond-only normalization admits amendments without changing shared `financial_promotion.py` behavior:

```python
def test_canonicalizer_accepts_10q_amendment_as_latest_in_scope_value() -> None: ...
def test_canonicalizer_accepts_10k_amendment_for_annual_slot() -> None: ...
def test_conflicting_values_in_same_winning_amendment_rank_fail_closed() -> None: ...
```

Before invoking `MultiPeriodFinancialPromoter`, create promotion-only copies of facts:

```python
def _promotion_form(form: str) -> str:
    return {"10-K/A": "10-K", "10-Q/A": "10-Q"}.get(form, form)

promotion_facts = tuple(
    replace(fact, filing_form=_promotion_form(fact.filing_form)) for fact in facts
)
```

Keep original amendment form/accession in the semantic revision and source manifest; only the promotion input receives normalized base form.

- [ ] **Step 5: Implement `canonicalize_issuer` by moving accounting-only logic out of `SecFirstProvider._build_record`**

Move the current SEC-derived portions of `_build_record` into `sec_canonical.py`:

- `_annual_fact`
- `_annual_ends`
- `_instant_fact`
- `_latest_balance_end`
- `_latest_instant_fact`
- `_promoted_instants`
- TTM promotion and capex positive-outflow normalization

Do not move sector methodology or market-cap logic into this module.

Accounting observation `source_identity` must use the semantic evidence identity, for example:

```python
source_identity = f"sec-evidence:{evidence_revision_sha256}"
```

- [ ] **Step 6: Write failing provider reuse/metadata independence tests**

Extend `tests/test_diamond_sec_provider.py` with:

```python
def test_first_build_canonicalizes_once_and_replay_reuses_snapshot(tmp_path: Path) -> None: ...
def test_two_share_classes_reuse_one_issuer_snapshot(tmp_path: Path) -> None: ...
def test_sector_metadata_change_does_not_invalidate_accounting_snapshot(tmp_path: Path) -> None: ...
```

For `test_two_share_classes_reuse_one_issuer_snapshot`, make the fake universe return two `SecurityRef` values with distinct tickers/security IDs and the same `sec-cik:...`, instrument the canonicalizer with a call counter, and assert exactly one canonicalization plus two final records with distinct tickers.

- [ ] **Step 7: Refactor `SecFirstProvider` to resolve manifest → snapshot → final record**

Constructor becomes:

```python
class SecFirstProvider:
    def __init__(
        self,
        *,
        universe_provider: UniverseMetadataProvider,
        evidence_store: SecEvidenceStore,
        canonical_cache: CanonicalIssuerCache,
        market_provider: BatchMarketProvider | None,
        split_provider: SplitAdjustmentProvider | None = None,
        refresh: bool = False,
    ) -> None: ...
```

Do not add market data to `CanonicalIssuerSnapshot`. In `fundamentals`, resolve one manifest/snapshot per unique CIK, then assemble each security with current `Sp500Company` metadata.

- [ ] **Step 8: Run canonical/provider tests**

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q \
  tests/test_diamond_sec_canonical.py tests/test_diamond_sec_provider.py
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync mypy --no-incremental src/qhapaq_finance/diamond/providers
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add \
  src/qhapaq_finance/diamond/providers/sec_canonical.py \
  src/qhapaq_finance/diamond/providers/sec.py \
  tests/test_diamond_sec_canonical.py \
  tests/test_diamond_sec_provider.py
git commit -m "feat: cache canonical SEC issuer snapshots"
```

---

### Task 5: Make market-cap derivation split-safe and expose missing-evidence diagnostics

**Files:**
- Modify: `src/qhapaq_finance/diamond/contracts.py`
- Modify: `src/qhapaq_finance/diamond/engine.py`
- Modify: `src/qhapaq_finance/diamond/providers/market.py`
- Create: `src/qhapaq_finance/diamond/providers/yahoo_splits.py`
- Modify: `src/qhapaq_finance/diamond/providers/sec.py`
- Modify: `tests/test_diamond_contracts.py`
- Modify: `tests/test_diamond_engine.py`
- Create: `tests/test_diamond_market_cap.py`
- Create: `tests/test_diamond_yahoo_splits.py`

**Interfaces:**
- Produces `SplitCoverage`, `SplitAdjustmentProvider`, `derive_safe_market_cap(...)`, and `FundamentalRecord.evidence_diagnostics: tuple[str, ...] = ()`.
- `SecFirstProvider` consumes split coverage only when direct market cap is absent and SEC share date differs from quote date.

- [ ] **Step 1: Write failing null-diagnostic propagation test**

Add a backward-compatible field at the end of `FundamentalRecord` and pin engine propagation:

```python
def test_evidence_diagnostics_are_preserved_in_diamond_result() -> None:
    record = make_record(evidence_diagnostics=("MARKET_CAP_SPLIT_UNVERIFIED",))
    result = evaluate_universe((record,))[0]
    assert "MARKET_CAP_SPLIT_UNVERIFIED" in result.diagnostics
```

- [ ] **Step 2: Verify RED, then implement diagnostic propagation**

Run:

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q \
  tests/test_diamond_engine.py::test_evidence_diagnostics_are_preserved_in_diamond_result
```

Expected: FAIL because the record has no `evidence_diagnostics` field.

Implement:

```python
@dataclass(frozen=True, slots=True)
class FundamentalRecord:
    ...
    observations: tuple[FundamentalObservation, ...]
    evidence_diagnostics: tuple[str, ...] = ()
```

Validate each diagnostic as non-empty text, and in `evaluate_universe` add:

```python
diagnostics = set(record.evidence_diagnostics)
diagnostics.update(validate_record(record))
```

- [ ] **Step 3: Write failing safe-market-cap unit tests**

Create `tests/test_diamond_market_cap.py` with the required cases:

```python
def test_direct_provider_market_cap_is_accepted() -> None: ...
def test_same_date_price_and_shares_can_derive_market_cap() -> None: ...
def test_split_covered_interval_adjusts_shares_before_market_cap() -> None: ...
def test_unverified_interval_withholds_market_cap() -> None: ...
def test_share_observation_after_quote_is_never_used() -> None: ...
def test_same_day_split_basis_is_not_assumed_safe() -> None: ...
```

Use this contract:

```python
@dataclass(frozen=True, slots=True)
class SplitCoverage:
    ticker: str
    start_date: date
    end_date: date
    cumulative_factor: float
    source_provider: str
    source_identity: str
    event_dates: tuple[date, ...] = ()

@dataclass(frozen=True, slots=True)
class MarketCapDecision:
    market_cap: float | None
    diagnostic: str | None
```

`derive_safe_market_cap` signature:

```python
def derive_safe_market_cap(
    *,
    quote: MarketQuote,
    shares: float | None,
    shares_observed_on: date | None,
    split_coverage: SplitCoverage | None,
) -> MarketCapDecision: ...
```

- [ ] **Step 4: Run market-cap tests and verify RED**

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q tests/test_diamond_market_cap.py
```

Expected: import/definition failure.

- [ ] **Step 5: Implement the fail-closed market-cap decision**

Required order:

```python
if quote.market_cap is not None:
    return MarketCapDecision(quote.market_cap, None)
if shares is None or shares_observed_on is None:
    return MarketCapDecision(None, "MARKET_CAP_SHARES_MISSING")
if shares_observed_on > quote.observed_on:
    return MarketCapDecision(None, "MARKET_CAP_TEMPORAL_MISMATCH")
if shares_observed_on == quote.observed_on:
    return MarketCapDecision(quote.price * shares, None)
if split_coverage is None:
    return MarketCapDecision(None, "MARKET_CAP_SPLIT_UNVERIFIED")
if split_coverage.start_date != shares_observed_on or split_coverage.end_date != quote.observed_on:
    return MarketCapDecision(None, "MARKET_CAP_SPLIT_UNVERIFIED")
if shares_observed_on in split_coverage.event_dates:
    return MarketCapDecision(None, "MARKET_CAP_SPLIT_UNVERIFIED")
return MarketCapDecision(quote.price * shares * split_coverage.cumulative_factor, None)
```

There is deliberately no age/grace threshold.

- [ ] **Step 6: Write failing Yahoo split-coverage cache/parser tests**

Create `tests/test_diamond_yahoo_splits.py` covering:

```python
def test_yahoo_split_provider_returns_factor_one_for_verified_no_split_interval(tmp_path: Path) -> None: ...
def test_yahoo_split_provider_multiplies_all_splits_in_interval(tmp_path: Path) -> None: ...
def test_yahoo_split_provider_replays_from_cache_without_network(tmp_path: Path) -> None: ...
def test_yahoo_split_provider_rejects_event_on_coverage_start_as_ambiguous(tmp_path: Path) -> None: ...
def test_yahoo_split_provider_rejects_malformed_split_ratio(tmp_path: Path) -> None: ...
```

Use Yahoo chart endpoint identity:

```text
https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1=<utc-start>&period2=<utc-end-exclusive>&interval=1d&events=splits
```

An empty but structurally valid `events.splits` result is explicit factor-1 coverage for the requested interval.

- [ ] **Step 7: Implement `YahooSplitAdjustmentProvider`**

Constructor:

```python
class YahooSplitAdjustmentProvider:
    def __init__(
        self,
        *,
        client: YahooJsonClient | None,
        cache: DiamondCache,
        refresh: bool = False,
    ) -> None: ...

    def coverage(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
        as_of: date,
    ) -> SplitCoverage | None: ...
```

Use the existing `_yahoo_symbol` convention and `YahooClient`. Cache each requested interval using the complete chart URL as request identity. Validate all event dates are inside `(start_date, end_date]`; return `None` if an event occurs exactly on `start_date`, because SEC share basis on that effective date is ambiguous.

- [ ] **Step 8: Wire safe market cap into `SecFirstProvider` and keep missing market evidence non-fatal**

For each security record:

1. read the latest shares value and its own `period_end` from canonical observations;
2. if the quote has direct market cap or shares/quote dates match, call `derive_safe_market_cap` without split network work;
3. otherwise request split coverage for exactly the shares→quote interval;
4. on `MarketProviderError`, continue with `SplitCoverage=None`;
5. append the returned diagnostic to `evidence_diagnostics` when market cap is withheld;
6. add `market_cap` observation only when the decision contains a value.

- [ ] **Step 9: Prove the null cascade remains mathematically supported**

Add a provider/engine regression test where market cap is withheld but quality/growth/capital remain complete:

```python
def test_missing_market_cap_does_not_remove_compounder_candidate() -> None:
    record = complete_compounder_record_without_market_cap()
    result = evaluate_universe((record, peer_record_a(), peer_record_b(), peer_record_c()))
    candidate = next(item for item in result if item.ticker == record.ticker)
    assert candidate.scores.price is None
    assert candidate.archetypes.compounder is not None
    assert candidate.archetypes.research_priority is not None
```

Do not change scoring code to make this test pass; fixture completeness must satisfy the existing Compounder contract.

- [ ] **Step 10: Run Task 5 tests and static checks**

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q \
  tests/test_diamond_contracts.py \
  tests/test_diamond_engine.py \
  tests/test_diamond_market_cap.py \
  tests/test_diamond_yahoo_splits.py \
  tests/test_diamond_sec_provider.py
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync mypy --no-incremental src/qhapaq_finance/diamond
```

Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add \
  src/qhapaq_finance/diamond/contracts.py \
  src/qhapaq_finance/diamond/engine.py \
  src/qhapaq_finance/diamond/providers/market.py \
  src/qhapaq_finance/diamond/providers/yahoo_splits.py \
  src/qhapaq_finance/diamond/providers/sec.py \
  tests/test_diamond_contracts.py \
  tests/test_diamond_engine.py \
  tests/test_diamond_market_cap.py \
  tests/test_diamond_yahoo_splits.py \
  tests/test_diamond_sec_provider.py
git commit -m "fix: make Diamond market cap split-safe"
```

---

### Task 6: Enforce S&P 500 live/cache validation parity

**Files:**
- Modify: `src/qhapaq_finance/diamond/providers/sp500.py`
- Modify: `tests/test_diamond_sp500_provider.py`

**Interfaces:**
- Produces one `_validate_companies(rows: Iterable[Sp500Company]) -> tuple[Sp500Company, ...]` path used by both HTML parsing and cache payload decoding.
- Repeated CIKs remain valid; duplicate tickers remain invalid.

- [ ] **Step 1: Write failing cache parity tests**

Add:

```python
def test_cached_invalid_ticker_fails_closed(tmp_path: Path) -> None: ...
def test_cached_invalid_cik_fails_closed(tmp_path: Path) -> None: ...
def test_cached_empty_metadata_fails_closed(tmp_path: Path) -> None: ...
def test_cached_duplicate_ticker_fails_closed(tmp_path: Path) -> None: ...
def test_distinct_tickers_may_share_one_cik(tmp_path: Path) -> None: ...
```

For each malformed case, seed the universe `DiamondCache` directly and call `Sp500UniverseProvider(client=None, cache=cache).universe(...)`.

- [ ] **Step 2: Run parity tests and verify RED**

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q tests/test_diamond_sp500_provider.py
```

Expected: at least the malformed cached-row cases fail because `_companies_from_payload` currently trusts converted strings more than live parsing.

- [ ] **Step 3: Implement one validator and call it from both sources**

Normalize and validate each `Sp500Company` through one function:

```python
def _validate_company(company: Sp500Company, *, index: int) -> Sp500Company:
    ticker = company.ticker.strip().upper()
    cik_raw = company.cik.strip()
    company_name = company.company_name.strip()
    sector = company.sector.strip()
    industry_group = company.industry_group.strip()
    if (
        not _TICKER.fullmatch(ticker)
        or not cik_raw.isdigit()
        or len(cik_raw) > 10
        or not company_name
        or not sector
        or not industry_group
    ):
        raise Sp500ProviderError(f"SP500_CONSTITUENT_ROW_INVALID:{index}")
    return Sp500Company(
        ticker=ticker,
        cik=cik_raw.zfill(10),
        company_name=company_name,
        sector=sector,
        industry_group=industry_group,
    )
```

Then enforce duplicate ticker only after normalization. Never create a `seen_cik` rejection set.

- [ ] **Step 4: Run provider tests**

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q tests/test_diamond_sp500_provider.py
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync ruff check \
  src/qhapaq_finance/diamond/providers/sp500.py tests/test_diamond_sp500_provider.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/qhapaq_finance/diamond/providers/sp500.py tests/test_diamond_sp500_provider.py
git commit -m "fix: validate cached S&P 500 membership"
```

---

### Task 7: Replace `repr(records)` with canonical dataset identity

**Files:**
- Create: `src/qhapaq_finance/diamond/dataset_identity.py`
- Modify: `src/qhapaq_finance/diamond/funnel.py`
- Create: `tests/test_diamond_dataset_identity.py`
- Modify: `tests/test_diamond_live_funnel_slice.py`

**Interfaces:**
- Consumes: Task 1 canonical wire primitives and final Task 5 `FundamentalRecord` shape.
- Produces `DATASET_SCHEMA_VERSION`, `DATASET_CANONICALIZER_VERSION`, `fundamental_dataset_payload(records)`, `dataset_identity(records)`.

- [ ] **Step 1: Write failing identity invariance/change tests**

Create tests for every spec case:

```python
def test_record_order_does_not_change_dataset_identity() -> None: ...
def test_observation_order_does_not_change_dataset_identity() -> None: ...
def test_numeric_lexical_equivalence_is_canonical() -> None: ...
def test_negative_zero_and_zero_share_identity() -> None: ...
def test_non_finite_identity_input_fails_closed() -> None: ...
def test_real_observation_change_changes_identity() -> None: ...
def test_dataset_schema_or_canonicalizer_version_changes_identity() -> None: ...
```

Because `FundamentalObservation` already rejects non-finite values, test non-finite handling directly against the dataset projection numeric helper or a deliberately constructed wire payload before dataclass validation.

- [ ] **Step 2: Run identity tests and verify RED**

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q tests/test_diamond_dataset_identity.py
```

Expected: import failure.

- [ ] **Step 3: Implement deterministic record/observation projection**

Use constants:

```python
DATASET_SCHEMA_VERSION = "diamond-fundamental-dataset-v2"
DATASET_CANONICALIZER_VERSION = "fundamental-record-canonicalizer-v1"
```

Observation sort key must include:

```python
(
    item.metric_id,
    item.fiscal_slot.value,
    item.period_start.isoformat() if item.period_start else "",
    item.period_end.isoformat(),
    item.period_kind.value,
    item.unit_kind.value,
    item.source_provider,
    item.source_identity or "",
    item.share_class_id or "",
    item.adjustment_basis_id or "",
    normalize_decimal(item.value),
)
```

Record ordering must be `(ticker, security_id, issuer_id)`. Include every field that can affect evaluation or evidence interpretation, including `evidence_diagnostics`, but exclude runtime counters/timings.

- [ ] **Step 4: Replace funnel identity implementation**

Delete:

```python
hashlib.sha256(repr(records).encode("utf-8")).hexdigest()
```

and import/call:

```python
from .dataset_identity import dataset_identity
...
dataset_identity=dataset_identity(records),
```

- [ ] **Step 5: Add funnel regression proving deterministic identity through different provider ordering**

In `tests/test_diamond_live_funnel_slice.py`, have two fake providers return the same records in opposite order and assert equal metadata identity and equal ranked tickers.

- [ ] **Step 6: Run identity/funnel tests**

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q \
  tests/test_diamond_dataset_identity.py tests/test_diamond_live_funnel_slice.py
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync ruff check \
  src/qhapaq_finance/diamond/dataset_identity.py \
  src/qhapaq_finance/diamond/funnel.py \
  tests/test_diamond_dataset_identity.py \
  tests/test_diamond_live_funnel_slice.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add \
  src/qhapaq_finance/diamond/dataset_identity.py \
  src/qhapaq_finance/diamond/funnel.py \
  tests/test_diamond_dataset_identity.py \
  tests/test_diamond_live_funnel_slice.py
git commit -m "fix: canonicalize Diamond dataset identity"
```

---

### Task 8: Wire production caches, migrate v0.3 evidence, and prove Debt Zero acceptance

**Files:**
- Modify: `src/qhapaq_finance/diamond/cli.py`
- Modify: `tests/test_diamond_cli.py`
- Modify: `tests/test_diamond_live_funnel_slice.py`
- Modify only if necessary for exception surface: `src/qhapaq_finance/cli.py`

**Interfaces:**
- Consumes all previous tasks.
- Produces the unchanged user command `qhapaq funnel --universe sp500 --depth 10` with new internal cache roots:
  - `data/cache/diamond/sec/index/`
  - `data/cache/diamond/sec/blobs/`
  - `data/cache/diamond/canonical/`
  - `data/cache/diamond/market/`
  - `data/cache/diamond/splits/`
  - `data/cache/diamond/universe/`

- [ ] **Step 1: Write failing CLI construction tests**

Pin provider construction without inspecting private fields more than necessary. Use monkeypatch factories and assert:

```python
def test_production_funnel_uses_sec_evidence_canonical_and_split_caches(tmp_path: Path) -> None: ...
def test_refresh_reaches_evidence_canonical_market_and_split_layers(tmp_path: Path) -> None: ...
def test_funnel_does_not_construct_analysis_orchestrator(monkeypatch: pytest.MonkeyPatch) -> None: ...
def test_funnel_does_not_require_fmp_key(monkeypatch: pytest.MonkeyPatch) -> None: ...
```

- [ ] **Step 2: Run CLI tests and verify RED**

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q tests/test_diamond_cli.py
```

Expected: new cache-construction tests fail against the v0.3 factory.

- [ ] **Step 3: Wire production provider composition**

`_production_funnel_provider` must conceptually construct:

```python
sec_client = SecClient(sec_config)
evidence_store = SecEvidenceStore(
    root=cache_root / "sec",
    client=sec_client,
    legacy_cache=DiamondCache(cache_root / "sec"),
)
canonical_cache = CanonicalIssuerCache(DiamondCache(cache_root / "canonical"))
market_provider = YahooBatchMarketProvider(
    client=YahooClient(),
    cache=DiamondCache(cache_root / "market"),
    refresh=refresh,
)
split_provider = YahooSplitAdjustmentProvider(
    client=YahooClient(),
    cache=DiamondCache(cache_root / "splits"),
    refresh=refresh,
)
return SecFirstProvider(
    universe_provider=universe_provider,
    evidence_store=evidence_store,
    canonical_cache=canonical_cache,
    market_provider=market_provider,
    split_provider=split_provider,
    refresh=refresh,
)
```

The evidence store itself owns TTL/refresh semantics. Existing v0.3 SEC cache files at the SEC root remain untouched and are available to its legacy migration path.

- [ ] **Step 4: Run the complete automated gate before live acceptance**

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync ruff format --check .
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync ruff check .
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync mypy --no-incremental src
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q
git diff --check
```

Expected: all PASS. If any command fails, stop live acceptance and fix through a RED→GREEN cycle in the owning task.

- [ ] **Step 5: Prove protected paths and stash before live work**

```bash
test -z "$(git status --short -- .env.example data/cache/sec/company_tickers.json)"
git rev-parse --verify stash@{0}
git stash list | head -n 3
```

Expected: protected-path status empty and the pre-existing stash still present.

- [ ] **Step 6: Run the literal command once to seed/migrate v0.4 caches**

Run exactly from the user's normal shell environment, not through `uv run`:

```bash
/usr/bin/time -f 'wall_seconds=%e' \
  qhapaq funnel --universe sp500 --depth 10 \
  --as-of 2026-09-22 --format json \
  >/tmp/qhapaq-debt-zero-live.json \
  2>/tmp/qhapaq-debt-zero-live.err
```

Read `/tmp/qhapaq-debt-zero-live.err` and assert the JSON contains at least 10 results. This first v0.4 run may pay one-time canonicalization and split-evidence acquisition costs.

- [ ] **Step 7: Run the literal command again and prove warm replay performance**

```bash
/usr/bin/time -f 'wall_seconds=%e' \
  qhapaq funnel --universe sp500 --depth 10 \
  --as-of 2026-09-22 --format json \
  >/tmp/qhapaq-debt-zero-replay.json \
  2>/tmp/qhapaq-debt-zero-replay.err
```

Extract and assert:

```python
import json
from pathlib import Path

live = json.loads(Path("/tmp/qhapaq-debt-zero-live.json").read_text())
replay = json.loads(Path("/tmp/qhapaq-debt-zero-replay.json").read_text())
assert replay["metadata"]["provider_requests"] == 0
assert replay["metadata"]["cache_misses"] == 0
assert replay["metadata"]["acquisition_seconds"] <= 10.0
assert live["metadata"]["dataset_identity"] == replay["metadata"]["dataset_identity"]
assert [row["ticker"] for row in live["results"]] == [
    row["ticker"] for row in replay["results"]
]
```

If the TTL causes revalidation because the chosen `as_of` is historical and the manifest is already older than seven days, repeat acceptance with a fresh current `as_of` snapshot and document both facts. Do not weaken the TTL or counters to make the assertion pass.

- [ ] **Step 8: Prove amendment invalidation on a controlled fixture rather than mutating production cache**

Run the focused test that simulates stale manifest + changed SEC 200 response:

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q \
  tests/test_diamond_sec_evidence.py::test_stale_manifest_changed_200_replaces_revision \
  tests/test_diamond_sec_canonical.py::test_canonical_cache_revision_mismatch_is_rejected
```

Expected: PASS and only the affected issuer revision changes in the fixture.

- [ ] **Step 9: Smoke-test `qhapaq analyze` contract is untouched**

Use an already-supported ticker/corpus from the repository and run the existing analyze smoke test rather than changing its implementation. At minimum run the test module that owns `qhapaq analyze TICKER`; if the repository has a deterministic local ticker fixture, also run that CLI command and record its typed state.

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q tests/test_cli.py
```

If the analyze CLI tests are split across another existing module, run that module too; do not edit analyze production code for v0.4.

- [ ] **Step 10: Re-run the final repository gate after live acceptance**

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync ruff format --check .
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync ruff check .
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync mypy --no-incremental src
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q
git diff --check
test -z "$(git status --short -- .env.example data/cache/sec/company_tickers.json)"
git rev-parse --verify stash@{0}
```

Expected: all PASS; protected paths unchanged; stash present.

- [ ] **Step 11: Commit production wiring and acceptance tests**

```bash
git add \
  src/qhapaq_finance/diamond/cli.py \
  tests/test_diamond_cli.py \
  tests/test_diamond_live_funnel_slice.py

git diff --cached --check
git commit -m "feat: complete Diamond Funnel Debt Zero v0.4"
```

Do not stage `data/cache/diamond/`, `.env.example`, `data/cache/sec/company_tickers.json`, or any other runtime cache artifact.

---

## Self-Review Record

### Spec coverage

- SEC manifest/blob store, bounded TTL, conditional 304, changed 200, wrong-CIK/corrupt-cache failure, and legacy migration: Task 3.
- `10-K/A` / `10-Q/A`, point-in-time cutoff, ambiguity semantics, canonical issuer cache, version invalidation, repeated-CIK reuse: Tasks 3–4.
- Unsafe market-cap removal, explicit split coverage, no grace threshold, null-aware Compounder behavior: Task 5.
- Live/cache S&P validation parity with repeated CIK allowed: Task 6.
- Canonical numeric JSON and deterministic dataset identity: Tasks 1 and 7.
- Literal CLI, warm replay `<= 10s`, zero requests/misses, full gates, protected files, stash, and analyze non-regression: Task 8.

### Type consistency

- Task 3 produces `ResolvedSecEvidence` consumed by Task 4.
- Task 4 produces `CanonicalIssuerSnapshot` and `CanonicalIssuerCache` consumed by `SecFirstProvider` and Task 8 wiring.
- Task 5 produces `SplitCoverage` / `SplitAdjustmentProvider` consumed by `SecFirstProvider` and the Yahoo split provider.
- Task 5 extends `FundamentalRecord` before Task 7 freezes the final dataset wire projection.
- Task 1 canonical primitives are available before both SEC evidence revision (Task 3) and dataset identity (Task 7).

### Review-focus coverage

All five Review Focus cases have explicit tests in their owning tasks: same-day split ambiguity (Task 5), stale manifest without validators (Task 3), wrong-`as_of` legacy migration (Task 3), canonical revision mismatch (Task 4), and shared-CIK multi-security reuse (Task 4).
