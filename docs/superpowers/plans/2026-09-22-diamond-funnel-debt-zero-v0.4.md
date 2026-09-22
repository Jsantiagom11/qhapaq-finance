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

- Create `src/qhapaq_finance/diamond/canonical_json.py`: canonical decimal and JSON byte contract shared by evidence revision and dataset identity.
- Modify `src/qhapaq_finance/sec_client.py`: additive conditional-request support; old callers remain behaviorally identical.
- Create `src/qhapaq_finance/diamond/providers/sec_evidence.py`: SEC manifest/blob store, point-in-time fact filtering, semantic evidence revision, TTL/revalidation, legacy migration.
- Create `src/qhapaq_finance/diamond/providers/sec_canonical.py`: immutable issuer snapshot, codec, cache identity, accounting canonicalizer.
- Refactor `src/qhapaq_finance/diamond/providers/sec.py`: orchestration only; issuer snapshot reuse, universe metadata, market overlay, final records.
- Extend `src/qhapaq_finance/diamond/providers/market.py`: split-coverage contract and fail-closed market-cap decision.
- Create `src/qhapaq_finance/diamond/providers/yahoo_splits.py`: cached Yahoo chart split-coverage provider.
- Modify `src/qhapaq_finance/diamond/contracts.py` and `src/qhapaq_finance/diamond/engine.py`: evidence diagnostics carried into final results without changing scores.
- Modify `src/qhapaq_finance/diamond/providers/sp500.py`: one semantic validator for live and cached membership.
- Create `src/qhapaq_finance/diamond/dataset_identity.py`: canonical `FundamentalRecord` dataset projection and SHA-256.
- Modify `src/qhapaq_finance/diamond/funnel.py`: use canonical dataset identity instead of `repr(records)`.
- Modify `src/qhapaq_finance/diamond/cli.py`: wire the new evidence/canonical/split stores while preserving the CLI surface.

## Review Focus

1. A split effective on the same date as the SEC share observation is basis-ambiguous; market cap must remain missing. Task 6 pins this with `test_same_day_split_basis_is_not_assumed_safe`.
2. A stale SEC manifest with no `ETag` or `Last-Modified` must perform an unconditional GET, not silently reuse stale evidence. Task 3 pins this with `test_stale_manifest_without_validators_refetches_unconditionally`.
3. A legacy v0.3 SEC cache entry with the wrong `data_as_of` must not seed a v0.4 manifest. Task 3 pins this with `test_legacy_cache_wrong_as_of_is_not_migrated`.
4. A canonical snapshot whose internal evidence revision disagrees with its requested identity must fail closed. Task 5 pins this with `test_canonical_cache_revision_mismatch_fails_closed`.
5. Two securities with distinct tickers but one CIK must share one accounting canonicalization while retaining distinct security metadata. Task 5 pins this with `test_two_share_classes_reuse_one_issuer_snapshot`.

---

### Task 1: Canonical JSON and numeric wire primitives

**Files:**
- Create: `src/qhapaq_finance/diamond/canonical_json.py`
- Create: `tests/test_diamond_canonical_json.py`

**Interfaces:**
- Produces `CanonicalJsonError`, `normalize_decimal`, `canonical_json_bytes`, `sha256_canonical_json`.
- Tasks 3, 5, and 8 consume this exact contract.

- [ ] **Step 1: Write the failing canonical-number tests**

Create `tests/test_diamond_canonical_json.py`:

```python
from decimal import Decimal

import pytest

from qhapaq_finance.diamond.canonical_json import (
    CanonicalJsonError,
    canonical_json_bytes,
    normalize_decimal,
    sha256_canonical_json,
)


def test_decimal_lexical_variants_share_one_value() -> None:
    assert normalize_decimal(10) == "10"
    assert normalize_decimal(10.0) == "10"
    assert normalize_decimal(Decimal("10.00")) == "10"
    assert normalize_decimal(Decimal("1E+3")) == "1000"


def test_negative_zero_normalizes_to_zero() -> None:
    assert normalize_decimal(-0.0) == "0"
    assert normalize_decimal(Decimal("-0.000")) == "0"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_values_fail_closed(value: float) -> None:
    with pytest.raises(CanonicalJsonError, match="CANONICAL_NUMBER_NOT_FINITE"):
        normalize_decimal(value)


def test_canonical_json_is_key_order_independent() -> None:
    left = {"b": "2", "a": ["1", None]}
    right = {"a": ["1", None], "b": "2"}
    assert canonical_json_bytes(left) == canonical_json_bytes(right)
    assert sha256_canonical_json(left) == sha256_canonical_json(right)
```

- [ ] **Step 2: Run the test and verify RED**

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q tests/test_diamond_canonical_json.py
```

Expected: import failure because the module does not exist.

- [ ] **Step 3: Implement the exact canonical primitive contract**

Create `src/qhapaq_finance/diamond/canonical_json.py`:

```python
from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal


class CanonicalJsonError(ValueError):
    """Canonical wire data cannot be represented safely."""


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
    rendered = format(number, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def canonical_json_bytes(payload: object) -> bytes:
    try:
        rendered = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise CanonicalJsonError("CANONICAL_JSON_INVALID") from exc
    return rendered.encode("utf-8")


def sha256_canonical_json(payload: object) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
```

- [ ] **Step 4: Verify GREEN and lint**

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

### Task 2: Add conditional SEC requests without changing existing client behavior

**Files:**
- Modify: `src/qhapaq_finance/sec_client.py` around `SecClient.get`
- Modify: `tests/test_sec_client.py`

**Interfaces:**
- Existing `SecClient.get(url)` and `get_json(url)` remain valid.
- New signature: `get(url, *, request_headers: Mapping[str, str] | None = None, accepted_statuses: frozenset[int] = frozenset()) -> SecResponse`.

- [ ] **Step 1: Add failing conditional-request tests**

Append:

```python
def test_get_merges_conditional_headers_and_accepts_explicit_304() -> None:
    transport = FakeTransport([SecResponse(304, {"ETag": '"abc"'}, b"")])
    client = SecClient(config(), transport=transport)

    response = client.get(
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
        request_headers={"If-None-Match": '"abc"'},
        accepted_statuses=frozenset({304}),
    )

    assert response.status_code == 304
    sent_headers = transport.calls[0][1]
    assert sent_headers["User-Agent"] == config().headers["User-Agent"]
    assert sent_headers["If-None-Match"] == '"abc"'


def test_unaccepted_304_remains_an_http_error() -> None:
    transport = FakeTransport([SecResponse(304, {}, b"")])
    client = SecClient(config(), transport=transport)

    with pytest.raises(SecHttpError, match="HTTP 304"):
        client.get("https://www.sec.gov/data.json")
```

- [ ] **Step 2: Run the tests and verify RED**

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q \
  tests/test_sec_client.py::test_get_merges_conditional_headers_and_accepts_explicit_304 \
  tests/test_sec_client.py::test_unaccepted_304_remains_an_http_error
```

Expected: first test fails because the keyword arguments are unsupported.

- [ ] **Step 3: Implement additive request headers and accepted statuses**

Replace the `get` signature/body while retaining the existing retry loop. The request section must be:

```python
def get(
    self,
    url: str,
    *,
    request_headers: Mapping[str, str] | None = None,
    accepted_statuses: frozenset[int] = frozenset(),
) -> SecResponse:
    headers = dict(self.config.headers)
    if request_headers is not None:
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

Leave `get_json` unchanged so all old consumers retain the old success/error behavior.

- [ ] **Step 4: Run the full SEC client module tests**

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q tests/test_sec_client.py
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync ruff check src/qhapaq_finance/sec_client.py tests/test_sec_client.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/qhapaq_finance/sec_client.py tests/test_sec_client.py
git commit -m "feat: support conditional SEC requests"
```

---

### Task 3: Implement SEC manifest/blob storage, amendment filtering, TTL, and legacy migration

**Files:**
- Create: `src/qhapaq_finance/diamond/providers/sec_evidence.py`
- Create: `tests/test_diamond_sec_evidence.py`
- Reuse: `src/qhapaq_finance/diamond/cache.py`

**Interfaces:**
- Produces `SecEvidenceError`, `SecEvidenceManifest`, `ResolvedSecEvidence`, `filtered_companyfacts`, `evidence_revision`, and `SecEvidenceStore`.
- `ResolvedSecEvidence.facts` is populated only when a raw payload was fetched/migrated in this call; a warm fresh-manifest hit returns `facts=None`.

- [ ] **Step 1: Write the minimal amendment fixture and failing point-in-time tests**

Create this helper in `tests/test_diamond_sec_evidence.py`:

```python
def revenue_payload(*, amendment_filed: str, amendment_value: float) -> dict[str, object]:
    return {
        "cik": 320193,
        "entityName": "Apple Inc.",
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "label": "Revenue",
                    "units": {
                        "USD": [
                            {
                                "start": "2026-01-01",
                                "end": "2026-06-30",
                                "val": 100.0,
                                "accn": "0000320193-26-000001",
                                "fy": 2026,
                                "fp": "Q2",
                                "form": "10-Q",
                                "filed": "2026-08-01",
                            },
                            {
                                "start": "2026-01-01",
                                "end": "2026-06-30",
                                "val": amendment_value,
                                "accn": "0000320193-26-000002",
                                "fy": 2026,
                                "fp": "Q2",
                                "form": "10-Q/A",
                                "filed": amendment_filed,
                            },
                        ]
                    },
                }
            }
        },
    }
```

Add:

```python
def test_in_scope_amendment_changes_semantic_revision() -> None:
    payload = revenue_payload(amendment_filed="2026-08-15", amendment_value=110.0)
    all_facts = filtered_companyfacts(payload, source_identity="payload-a", as_of=date(2026, 9, 22))
    original_only = tuple(item for item in all_facts if item.filing_form == "10-Q")
    assert {item.filing_form for item in all_facts} == {"10-Q", "10-Q/A"}
    assert evidence_revision(all_facts) != evidence_revision(original_only)


def test_amendment_after_as_of_is_not_historical_evidence() -> None:
    payload = revenue_payload(amendment_filed="2026-10-01", amendment_value=110.0)
    facts = filtered_companyfacts(payload, source_identity="payload-a", as_of=date(2026, 9, 22))
    assert [item.filing_form for item in facts] == ["10-Q"]
```

- [ ] **Step 2: Run and verify RED**

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q \
  tests/test_diamond_sec_evidence.py::test_in_scope_amendment_changes_semantic_revision \
  tests/test_diamond_sec_evidence.py::test_amendment_after_as_of_is_not_historical_evidence
```

Expected: import failure.

- [ ] **Step 3: Implement filtering, manifest contracts, and revision hashing**

Public contracts:

```python
SEC_EVIDENCE_SCHEMA_VERSION = "diamond-sec-evidence-v1"
RECENT_AS_OF_DAYS = 2
RECENT_TTL = timedelta(hours=6)
HISTORICAL_TTL = timedelta(days=7)


class SecEvidenceError(RuntimeError):
    """SEC evidence cannot be trusted or refreshed."""


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

`filtered_companyfacts` must call existing `extract_company_facts` and retain only forms in `{"10-K", "10-K/A", "10-Q", "10-Q/A"}`, `filing_date <= as_of`, `end <= as_of`, consolidated, dimensionless facts.

`evidence_revision` must hash sorted fact dictionaries containing taxonomy, concept, unit, normalized numeric value, period kind/start/end, fiscal year/period, original filing form, filing date, accession, consolidated flag, and dimensions.

- [ ] **Step 4: Add a complete fake SEC HTTP boundary and freshness tests**

In the same test module define:

```python
class FakeSecHttpClient:
    def __init__(self, responses: list[SecResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, str], frozenset[int]]] = []

    def get(
        self,
        url: str,
        *,
        request_headers: Mapping[str, str] | None = None,
        accepted_statuses: frozenset[int] = frozenset(),
    ) -> SecResponse:
        self.calls.append((url, dict(request_headers or {}), accepted_statuses))
        return self.responses.pop(0)
```

Add tests with these exact assertions:

```python
def test_fresh_manifest_performs_zero_sec_requests(tmp_path: Path) -> None:
    now = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
    client = FakeSecHttpClient(
        [
            SecResponse(
                200,
                {"ETag": '"v1"'},
                json.dumps(
                    revenue_payload(amendment_filed="2026-08-15", amendment_value=110.0)
                ).encode(),
            )
        ]
    )
    store = SecEvidenceStore(
        root=tmp_path / "sec", client=client, legacy_cache=None, now=lambda: now
    )
    first = store.resolve("0000320193", date(2026, 9, 22))
    replay = SecEvidenceStore(
        root=tmp_path / "sec", client=None, legacy_cache=None, now=lambda: now + timedelta(hours=1)
    )
    second = replay.resolve("0000320193", date(2026, 9, 22))
    assert first.manifest.evidence_revision_sha256 == second.manifest.evidence_revision_sha256
    assert second.facts is None
    assert replay.provider_requests == 0
    assert replay.cache_hits == 1
    assert replay.cache_misses == 0


def test_stale_manifest_with_etag_304_preserves_revision(tmp_path: Path) -> None:
    base = datetime(2026, 9, 22, 0, tzinfo=timezone.utc)
    payload = revenue_payload(amendment_filed="2026-08-15", amendment_value=110.0)
    seed_client = FakeSecHttpClient(
        [SecResponse(200, {"ETag": '"v1"'}, json.dumps(payload).encode())]
    )
    SecEvidenceStore(
        root=tmp_path / "sec", client=seed_client, legacy_cache=None, now=lambda: base
    ).resolve("0000320193", date(2026, 9, 22))
    revalidate_client = FakeSecHttpClient([SecResponse(304, {"ETag": '"v1"'}, b"")])
    store = SecEvidenceStore(
        root=tmp_path / "sec",
        client=revalidate_client,
        legacy_cache=None,
        now=lambda: base + timedelta(hours=7),
    )
    resolved = store.resolve("0000320193", date(2026, 9, 22))
    assert revalidate_client.calls[0][1] == {"If-None-Match": '"v1"'}
    assert resolved.facts is None
    assert store.provider_requests == 1


def test_stale_manifest_without_validators_refetches_unconditionally(tmp_path: Path) -> None:
    base = datetime(2026, 9, 22, 0, tzinfo=timezone.utc)
    first_payload = revenue_payload(amendment_filed="2026-08-15", amendment_value=110.0)
    second_payload = revenue_payload(amendment_filed="2026-08-20", amendment_value=111.0)
    seed = FakeSecHttpClient([SecResponse(200, {}, json.dumps(first_payload).encode())])
    first = SecEvidenceStore(
        root=tmp_path / "sec", client=seed, legacy_cache=None, now=lambda: base
    ).resolve("0000320193", date(2026, 9, 22))
    refresh = FakeSecHttpClient([SecResponse(200, {}, json.dumps(second_payload).encode())])
    second = SecEvidenceStore(
        root=tmp_path / "sec",
        client=refresh,
        legacy_cache=None,
        now=lambda: base + timedelta(hours=7),
    ).resolve("0000320193", date(2026, 9, 22))
    assert refresh.calls[0][1] == {}
    assert first.manifest.evidence_revision_sha256 != second.manifest.evidence_revision_sha256
```

Also add typed-failure tests for wrong CIK and malformed blob checksum by tampering the stored blob after the first resolve and asserting `SecEvidenceError` contains `SEC_BLOB_CHECKSUM_MISMATCH`.

- [ ] **Step 5: Add the legacy wrong-`as_of` migration regression**

Seed the existing cache format exactly:

```python
def test_legacy_cache_wrong_as_of_is_not_migrated(tmp_path: Path) -> None:
    identity = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"
    legacy = DiamondCache(tmp_path / "sec")
    legacy.store(
        identity,
        provider="sec-companyfacts",
        data_as_of=date(2026, 9, 21),
        payload=revenue_payload(amendment_filed="2026-08-15", amendment_value=110.0),
    )
    replacement = revenue_payload(amendment_filed="2026-08-20", amendment_value=111.0)
    client = FakeSecHttpClient([SecResponse(200, {}, json.dumps(replacement).encode())])
    store = SecEvidenceStore(
        root=tmp_path / "sec",
        client=client,
        legacy_cache=legacy,
        now=lambda: datetime(2026, 9, 22, 12, tzinfo=timezone.utc),
    )
    resolved = store.resolve("0000320193", date(2026, 9, 22))
    assert len(client.calls) == 1
    assert resolved.manifest.data_as_of == date(2026, 9, 22)
```

- [ ] **Step 6: Implement the manifest/blob store**

Use paths:

```text
<root>/index/<sha256(request_identity)>.json
<root>/blobs/<payload_sha256>.json
```

`SecEvidenceStore` must expose integer `provider_requests`, `cache_hits`, `cache_misses` counters. Manifest and blob writes use temp files in their destination directory, `flush`, `os.fsync`, and `os.replace`.

Freshness:

```python
def _ttl(as_of: date, today: date) -> timedelta:
    return RECENT_TTL if (today - as_of).days <= RECENT_AS_OF_DAYS else HISTORICAL_TTL
```

When stale, send `If-None-Match` if `etag` exists, otherwise `If-Modified-Since` if `last_modified` exists, otherwise no conditional header. Accept 304 only for the revalidation path. A failed required fetch/revalidation raises `SecEvidenceError("SEC_REVALIDATION_FAILED")`.

Legacy migration may occur only when the legacy entry provider is `sec-companyfacts`, the cached CIK matches, and `cached.data_as_of == as_of`; otherwise fetch from SEC.

- [ ] **Step 7: Verify Task 3**

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q tests/test_diamond_sec_evidence.py
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync ruff check src/qhapaq_finance/diamond/providers/sec_evidence.py tests/test_diamond_sec_evidence.py
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/qhapaq_finance/diamond/providers/sec_evidence.py tests/test_diamond_sec_evidence.py
git commit -m "feat: add amendment-aware SEC evidence store"
```

---

### Task 4: Define the canonical issuer snapshot and cache codec

**Files:**
- Create: `src/qhapaq_finance/diamond/providers/sec_canonical.py`
- Create: `tests/test_diamond_sec_canonical.py`

**Interfaces:**
- Produces `CANONICAL_SCHEMA_VERSION`, `SEC_CANONICALIZER_VERSION`, `CanonicalIssuerSnapshot`, `CanonicalIssuerCache`.
- Task 5 adds the accounting builder and consumes this cache contract.

- [ ] **Step 1: Write a concrete snapshot fixture and failing round-trip/version tests**

Create:

```python
def sample_snapshot(
    *, revision: str = "rev-a", version: str = "sec-canonicalizer-v2"
) -> CanonicalIssuerSnapshot:
    return CanonicalIssuerSnapshot(
        schema_version="diamond-canonical-issuer-v1",
        canonicalizer_version=version,
        issuer_id="sec-cik:0000320193",
        cik="0000320193",
        as_of=date(2026, 9, 22),
        history_years=5,
        evidence_revision_sha256=revision,
        fundamental_period_type=FundamentalPeriodType.TTM,
        fundamental_period_end=date(2026, 6, 30),
        fiscal_year_end="12-31",
        observations=(
            FundamentalObservation(
                metric_id="revenue",
                fiscal_slot=FiscalSlot.TTM,
                value=110.0,
                period_start=date(2025, 7, 1),
                period_end=date(2026, 6, 30),
                period_kind=PeriodKind.DURATION,
                unit_kind=UnitKind.CURRENCY,
                source_provider="sec",
                source_identity="sec-evidence:rev-a",
            ),
        ),
    )
```

Tests:

```python
def test_canonical_cache_round_trips_snapshot(tmp_path: Path) -> None:
    cache = CanonicalIssuerCache(DiamondCache(tmp_path / "canonical"))
    expected = sample_snapshot()
    cache.store(expected)
    actual = cache.load(
        issuer_id=expected.issuer_id,
        as_of=expected.as_of,
        history_years=expected.history_years,
        evidence_revision_sha256=expected.evidence_revision_sha256,
    )
    assert actual == expected
    assert cache.cache_hits == 1


def test_canonicalizer_version_change_is_a_cache_miss(tmp_path: Path) -> None:
    cache = CanonicalIssuerCache(DiamondCache(tmp_path / "canonical"))
    cache.store(sample_snapshot(version="sec-canonicalizer-v1"))
    assert (
        cache.load(
            issuer_id="sec-cik:0000320193",
            as_of=date(2026, 9, 22),
            history_years=5,
            evidence_revision_sha256="rev-a",
        )
        is None
    )
```

- [ ] **Step 2: Run and verify RED**

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q tests/test_diamond_sec_canonical.py
```

Expected: import failure.

- [ ] **Step 3: Implement the snapshot dataclass, explicit JSON codec, and identity**

Use:

```python
CANONICAL_SCHEMA_VERSION = "diamond-canonical-issuer-v1"
SEC_CANONICALIZER_VERSION = "sec-canonicalizer-v2"
```

Identity payload:

```python
{
    "schema_version": CANONICAL_SCHEMA_VERSION,
    "canonicalizer_version": SEC_CANONICALIZER_VERSION,
    "issuer_id": issuer_id,
    "as_of": as_of.isoformat(),
    "history_years": history_years,
    "evidence_revision_sha256": evidence_revision_sha256,
}
```

Prefix its SHA with `sec-canonical:` and store through `DiamondCache`. Encode/decode every observation field explicitly; no pickle, `repr`, or dataclass `str` identity.

- [ ] **Step 4: Add fail-closed internal mismatch test**

After storing a valid snapshot, locate the underlying `DiamondCache` file from its request identity, change only `payload.evidence_revision_sha256` to `rev-b`, recompute the outer DiamondCache checksum so the generic cache remains structurally valid, then load with requested revision `rev-a`:

```python
def test_canonical_cache_revision_mismatch_fails_closed(tmp_path: Path) -> None:
    raw = DiamondCache(tmp_path / "canonical")
    cache = CanonicalIssuerCache(raw)
    snapshot = sample_snapshot(revision="rev-a")
    cache.store(snapshot)
    request_identity = cache.request_identity(
        issuer_id=snapshot.issuer_id,
        as_of=snapshot.as_of,
        history_years=5,
        evidence_revision_sha256="rev-a",
    )
    cached = raw.load(request_identity)
    assert cached is not None
    payload = dict(cached.payload)
    payload["evidence_revision_sha256"] = "rev-b"
    raw.store(request_identity, provider=cache.PROVIDER, data_as_of=snapshot.as_of, payload=payload)
    with pytest.raises(SecCanonicalError, match="CANONICAL_CACHE_REVISION_MISMATCH"):
        cache.load(
            issuer_id=snapshot.issuer_id,
            as_of=snapshot.as_of,
            history_years=5,
            evidence_revision_sha256="rev-a",
        )
```

- [ ] **Step 5: Verify Task 4 and commit**

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q tests/test_diamond_sec_canonical.py
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync ruff check src/qhapaq_finance/diamond/providers/sec_canonical.py tests/test_diamond_sec_canonical.py
git add src/qhapaq_finance/diamond/providers/sec_canonical.py tests/test_diamond_sec_canonical.py
git commit -m "feat: add canonical SEC issuer cache"
```

---

### Task 5: Move SEC accounting canonicalization behind the issuer cache and reuse by CIK

**Files:**
- Modify: `src/qhapaq_finance/diamond/providers/sec_canonical.py`
- Refactor: `src/qhapaq_finance/diamond/providers/sec.py`
- Modify: `tests/test_diamond_sec_canonical.py`
- Modify: `tests/test_diamond_sec_provider.py`

**Interfaces:**
- Produces `canonicalize_issuer(*, issuer_id, cik, as_of, history_years, evidence_revision_sha256, facts) -> CanonicalIssuerSnapshot | None`.
- `SecFirstProvider` constructor consumes `SecEvidenceStore` and `CanonicalIssuerCache`; market behavior remains as v0.3 until Task 6.

- [ ] **Step 1: Add failing Diamond-only amendment canonicalization tests using the existing `_companyfacts()` fixture**

In `tests/test_diamond_sec_provider.py`, append an amendment to the existing revenue units and assert the newest in-scope amendment wins without changing shared promotion code:

```python
def test_sec_canonicalizer_uses_in_scope_10q_amendment(tmp_path: Path) -> None:
    payload = _companyfacts()
    facts = cast(dict[str, object], payload["facts"])
    gaap = cast(dict[str, object], facts["us-gaap"])
    revenue = cast(dict[str, object], gaap["RevenueFromContractWithCustomerExcludingAssessedTax"])
    units = cast(dict[str, list[dict[str, object]]], revenue["units"])
    units["USD"].append(
        _duration(
            60.0,
            start="2026-01-01",
            end="2026-06-30",
            filed="2026-08-15",
            fiscal_year=2026,
            fiscal_period="Q2",
            form="10-Q/A",
        )
    )
    provider = make_sec_first_provider(tmp_path=tmp_path, payload=payload, market_provider=None)
    record = provider.fundamentals(
        provider.universe("sp500", date(2026, 9, 22)), date(2026, 9, 22)
    )[0]
    assert value(record, "revenue", FiscalSlot.TTM) == pytest.approx(120.0)
```

Also add a `10-K/A` annual-slot case where an FY amendment filed before `as_of` changes FY1, and a same-rank conflicting amendment case that raises `SecCanonicalError` rather than picking one arbitrarily.

- [ ] **Step 2: Run amendment canonicalization tests and verify RED**

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q \
  tests/test_diamond_sec_provider.py -k 'amendment or conflicting'
```

Expected: amendment cases fail because v0.3 canonicalization admits only base forms downstream.

- [ ] **Step 3: Move accounting-only helpers from `sec.py` into `sec_canonical.py`**

Move the current TTM, annual, instant, latest-balance, and promoted-instant logic. Keep methodology, sector/GICS, quotes, market age, and final security assembly out of the snapshot.

Before using `MultiPeriodFinancialPromoter`, normalize only the promotion copy:

```python
def _promotion_form(form: str) -> str:
    if form == "10-K/A":
        return "10-K"
    if form == "10-Q/A":
        return "10-Q"
    return form


promotion_facts = tuple(
    replace(item, filing_form=_promotion_form(item.filing_form)) for item in facts
)
```

Annual selection itself must accept `{"10-K", "10-K/A"}` and rank by `(filing_date, accession)`. Original forms/accessions remain in Task 3 evidence revision; no global change to `financial_promotion.py` is permitted in this task.

Accounting observation source identity is `sec-evidence:<evidence_revision_sha256>`. Capex retains `abs(raw_value)` canonical outflow semantics.

- [ ] **Step 4: Add the warm-canonical-hit proof**

Instrument the evidence store with a `load_facts_calls` counter and run the provider twice. The second provider instance gets the same manifest/canonical roots:

```python
def test_warm_canonical_hit_does_not_load_raw_sec_blob(tmp_path: Path) -> None:
    first = build_provider_with_instrumented_store(tmp_path, allow_network=True)
    securities = first.universe("sp500", date(2026, 9, 22))
    first.fundamentals(securities, date(2026, 9, 22))
    replay = build_provider_with_instrumented_store(tmp_path, allow_network=False)
    replay.fundamentals(securities, date(2026, 9, 22))
    assert replay.evidence_store.load_facts_calls == 0
    assert replay.canonical_cache.cache_hits == 1
```

The helper may wrap `SecEvidenceStore.load_facts` rather than changing production solely for observability.

- [ ] **Step 5: Add the shared-CIK review-focus test**

Define a fake universe returning two securities with one issuer:

```python
class TwoClassUniverse(FakeUniverse):
    def universe(self, universe_id: str, as_of: date) -> tuple[SecurityRef, ...]:
        assert universe_id == "sp500"
        return (
            SecurityRef("AAA", "sp500:AAA", "sec-cik:0000320193"),
            SecurityRef("AAB", "sp500:AAB", "sec-cik:0000320193"),
        )

    def metadata(self, ticker: str) -> Sp500Company:
        return Sp500Company(
            ticker=ticker,
            cik="0000320193",
            company_name=f"Issuer {ticker}",
            sector="Information Technology",
            industry_group="Technology Hardware",
        )
```

Test:

```python
def test_two_share_classes_reuse_one_issuer_snapshot(tmp_path: Path) -> None:
    provider, canonicalizer_counter = build_counted_two_class_provider(tmp_path)
    securities = provider.universe("sp500", date(2026, 9, 22))
    records = provider.fundamentals(securities, date(2026, 9, 22))
    assert [item.ticker for item in records] == ["AAA", "AAB"]
    assert {item.issuer_id for item in records} == {"sec-cik:0000320193"}
    assert canonicalizer_counter.calls == 1
```

- [ ] **Step 6: Refactor `SecFirstProvider` around evidence manifest + canonical cache**

Constructor:

```python
def __init__(
    self,
    *,
    universe_provider: UniverseMetadataProvider,
    evidence_store: SecEvidenceStore,
    canonical_cache: CanonicalIssuerCache,
    market_provider: BatchMarketProvider | None,
    split_provider: SplitAdjustmentProvider | None = None,
    refresh: bool = False,
) -> None:
```

Per unique CIK:

1. `resolved = evidence_store.resolve(cik, as_of, refresh=refresh)`.
2. Try `canonical_cache.load` using resolved manifest revision.
3. On hit, do not call `load_facts`.
4. On miss, use `resolved.facts` if present; otherwise call `evidence_store.load_facts(resolved)` once.
5. Canonicalize/store once and reuse for all securities sharing that CIK.

Provider counters must aggregate universe, evidence store, canonical cache, market provider, and split provider counters. `provider_requests` counts only external provider requests; canonical-cache misses are cache misses but never provider requests.

- [ ] **Step 7: Prove metadata does not invalidate accounting snapshot**

Run once with `FakeUniverse(sector="Information Technology")`, then replay from the same evidence/canonical roots with a fake universe whose sector is `Industrials`. Assert the replay canonical cache hits and the final record sector changes to `Industrials` without a canonical rebuild.

- [ ] **Step 8: Verify Task 5 and commit**

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q tests/test_diamond_sec_canonical.py tests/test_diamond_sec_provider.py
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync mypy --no-incremental src/qhapaq_finance/diamond/providers

git add \
  src/qhapaq_finance/diamond/providers/sec_canonical.py \
  src/qhapaq_finance/diamond/providers/sec.py \
  tests/test_diamond_sec_canonical.py \
  tests/test_diamond_sec_provider.py
git commit -m "feat: reuse canonical SEC issuer snapshots"
```

---

### Task 6: Make market-cap derivation split-safe and preserve null-aware ranking

**Files:**
- Modify: `src/qhapaq_finance/diamond/contracts.py`
- Modify: `src/qhapaq_finance/diamond/engine.py`
- Modify: `src/qhapaq_finance/diamond/providers/market.py`
- Create: `src/qhapaq_finance/diamond/providers/yahoo_splits.py`
- Modify: `src/qhapaq_finance/diamond/providers/sec.py`
- Modify: `tests/test_diamond_engine.py`
- Create: `tests/test_diamond_market_cap.py`
- Create: `tests/test_diamond_yahoo_splits.py`

**Interfaces:**
- Adds `FundamentalRecord.evidence_diagnostics: tuple[str, ...] = ()`.
- Produces `SplitCoverage`, `SplitAdjustmentProvider`, `MarketCapDecision`, `derive_safe_market_cap`, `YahooSplitAdjustmentProvider`.

- [ ] **Step 1: Write and fail the diagnostic-propagation test**

Add to `tests/test_diamond_engine.py` using its existing valid-record helper:

```python
def test_evidence_diagnostic_reaches_result() -> None:
    record = replace(
        valid_operating_record("AAA"),
        evidence_diagnostics=("MARKET_CAP_SPLIT_UNVERIFIED",),
    )
    result = evaluate_universe((record,))[0]
    assert "MARKET_CAP_SPLIT_UNVERIFIED" in result.diagnostics
```

Run it and expect constructor failure because the field does not exist.

Then add the field at the end of `FundamentalRecord`, validate each item with `_text`, and seed engine diagnostics with `set(record.evidence_diagnostics)` before existing validation/feature diagnostics.

- [ ] **Step 2: Write complete safe-market-cap decision tests**

Create `tests/test_diamond_market_cap.py`:

```python
from datetime import date

import pytest

from qhapaq_finance.diamond.providers.market import (
    MarketQuote,
    SplitCoverage,
    derive_safe_market_cap,
)


def quote(*, market_cap: float | None = None, observed_on: date = date(2026, 9, 21)) -> MarketQuote:
    return MarketQuote("AAA", 10.0, observed_on, "USD", market_cap, "market-test", "quote-sha")


def test_direct_provider_market_cap_is_accepted() -> None:
    decision = derive_safe_market_cap(
        quote=quote(market_cap=250.0),
        shares=17.0,
        shares_observed_on=date(2026, 6, 30),
        split_coverage=None,
    )
    assert decision.market_cap == pytest.approx(250.0)
    assert decision.diagnostic is None


def test_same_date_price_and_shares_can_derive_market_cap() -> None:
    decision = derive_safe_market_cap(
        quote=quote(observed_on=date(2026, 9, 21)),
        shares=17.0,
        shares_observed_on=date(2026, 9, 21),
        split_coverage=None,
    )
    assert decision.market_cap == pytest.approx(170.0)
    assert decision.diagnostic is None


def test_split_covered_interval_adjusts_shares() -> None:
    coverage = SplitCoverage(
        ticker="AAA",
        start_date=date(2026, 6, 30),
        end_date=date(2026, 9, 21),
        cumulative_factor=4.0,
        source_provider="yahoo-finance",
        source_identity="split-sha",
        event_dates=(date(2026, 8, 15),),
    )
    decision = derive_safe_market_cap(
        quote=quote(),
        shares=17.0,
        shares_observed_on=date(2026, 6, 30),
        split_coverage=coverage,
    )
    assert decision.market_cap == pytest.approx(680.0)
    assert decision.diagnostic is None


def test_unverified_interval_withholds_market_cap() -> None:
    decision = derive_safe_market_cap(
        quote=quote(),
        shares=17.0,
        shares_observed_on=date(2026, 6, 30),
        split_coverage=None,
    )
    assert decision.market_cap is None
    assert decision.diagnostic == "MARKET_CAP_SPLIT_UNVERIFIED"


def test_same_day_split_basis_is_not_assumed_safe() -> None:
    coverage = SplitCoverage(
        ticker="AAA",
        start_date=date(2026, 6, 30),
        end_date=date(2026, 9, 21),
        cumulative_factor=4.0,
        source_provider="yahoo-finance",
        source_identity="split-sha",
        event_dates=(date(2026, 6, 30),),
    )
    decision = derive_safe_market_cap(
        quote=quote(),
        shares=17.0,
        shares_observed_on=date(2026, 6, 30),
        split_coverage=coverage,
    )
    assert decision.market_cap is None
    assert decision.diagnostic == "MARKET_CAP_SPLIT_UNVERIFIED"
```

Add one more test where `shares_observed_on > quote.observed_on` expects `MARKET_CAP_TEMPORAL_MISMATCH`.

- [ ] **Step 3: Verify RED, then implement the market contracts**

Run `tests/test_diamond_market_cap.py`; expect import failure.

Implement in `providers/market.py`:

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


class SplitAdjustmentProvider(Protocol):
    provider_requests: int
    cache_hits: int
    cache_misses: int

    def coverage(
        self, ticker: str, start_date: date, end_date: date, as_of: date
    ) -> SplitCoverage | None:
        raise NotImplementedError
```

`derive_safe_market_cap` follows this exact precedence: direct provider market cap; missing shares; shares after quote; same-date shares; complete matching split coverage; otherwise `MARKET_CAP_SPLIT_UNVERIFIED`. No age-based branch is permitted.

- [ ] **Step 4: Write Yahoo split parser/cache tests with concrete payloads**

Create `tests/test_diamond_yahoo_splits.py` with a fake client returning:

```python
NO_SPLIT = {
    "chart": {
        "result": [{"meta": {"currency": "USD"}, "timestamp": [1789948800]}],
        "error": None,
    }
}

ONE_SPLIT = {
    "chart": {
        "result": [
            {
                "meta": {"currency": "USD"},
                "timestamp": [1789948800],
                "events": {
                    "splits": {
                        "1787356800": {
                            "date": 1787356800,
                            "numerator": 4.0,
                            "denominator": 1.0,
                            "splitRatio": "4:1",
                        }
                    }
                },
            }
        ],
        "error": None,
    }
}
```

Assert a valid no-event response returns factor `1.0`, one split returns `4.0`, two valid split events multiply, a malformed/zero denominator raises `YahooSplitProviderError`, and a second provider with `client=None` returns identical coverage from `DiamondCache` with `provider_requests == 0`.

- [ ] **Step 5: Implement `YahooSplitAdjustmentProvider`**

Use `YahooClient` and cache one exact interval URL:

```text
https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1=<start-utc>&period2=<day-after-end-utc>&interval=1d&events=splits
```

`period2` is exclusive. Parse split event timestamps as UTC dates, multiply `numerator / denominator` for events inside `[start_date, end_date]`, preserve sorted event dates, and return factor-1 coverage when the chart request succeeded with no split events. A split on `start_date` remains represented in `event_dates`; `derive_safe_market_cap` is responsible for rejecting the basis ambiguity.

- [ ] **Step 6: Wire safe market cap into `SecFirstProvider`**

Extract both latest share value and its observation `period_end` from the canonical snapshot. Request split coverage only when all are true: quote exists; direct market cap is absent; shares exist; share date precedes quote date. A split-provider failure is optional market evidence: treat coverage as missing, keep the security, emit `MARKET_CAP_SPLIT_UNVERIFIED`.

Only add a `market_cap` observation when `MarketCapDecision.market_cap` is not `None`. Append the decision diagnostic to `FundamentalRecord.evidence_diagnostics` otherwise.

- [ ] **Step 7: Prove null-aware scoring without changing scoring code**

In `tests/test_diamond_engine.py`, use the existing multi-record fixtures to create an operating company with all Compounder-required fundamentals but no market cap. Assert:

```python
candidate = next(item for item in evaluate_universe(records) if item.ticker == "AAA")
assert candidate.scores.price is None
assert candidate.archetypes.compounder is not None
assert candidate.archetypes.research_priority is not None
```

If the existing fixture lacks enough peers/features, expand only the fixture data; do not edit `scoring.py` or `archetypes.py`.

- [ ] **Step 8: Verify Task 6 and commit**

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q \
  tests/test_diamond_engine.py \
  tests/test_diamond_market_cap.py \
  tests/test_diamond_yahoo_splits.py \
  tests/test_diamond_sec_provider.py
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync mypy --no-incremental src/qhapaq_finance/diamond

git add \
  src/qhapaq_finance/diamond/contracts.py \
  src/qhapaq_finance/diamond/engine.py \
  src/qhapaq_finance/diamond/providers/market.py \
  src/qhapaq_finance/diamond/providers/yahoo_splits.py \
  src/qhapaq_finance/diamond/providers/sec.py \
  tests/test_diamond_engine.py \
  tests/test_diamond_market_cap.py \
  tests/test_diamond_yahoo_splits.py \
  tests/test_diamond_sec_provider.py
git commit -m "fix: make Diamond market cap split-safe"
```

---

### Task 7: Enforce S&P 500 validation parity for live and cached membership

**Files:**
- Modify: `src/qhapaq_finance/diamond/providers/sp500.py`
- Modify: `tests/test_diamond_sp500_provider.py`

**Interfaces:**
- Produces one `_validate_companies` path used by both live HTML parsing and cached payload decoding.
- Duplicate tickers fail; repeated CIKs remain valid.

- [ ] **Step 1: Add one parameterized malformed-cache test and repeated-CIK test**

Seed the existing universe cache with payload rows directly:

```python
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ticker", "BAD TICKER"),
        ("cik", "not-a-cik"),
        ("company_name", ""),
        ("sector", ""),
        ("industry_group", ""),
    ],
)
def test_cached_membership_uses_live_validation(tmp_path: Path, field: str, value: str) -> None:
    cache = DiamondCache(tmp_path / "universe")
    row = {
        "ticker": "AAA",
        "cik": "0000320193",
        "company_name": "Issuer A",
        "sector": "Industrials",
        "industry_group": "Machinery",
    }
    row[field] = value
    cache.store(
        Sp500UniverseProvider.SOURCE_URL,
        provider=Sp500UniverseProvider.PROVIDER,
        data_as_of=date(2026, 9, 22),
        payload=[row],
    )
    provider = Sp500UniverseProvider(client=None, cache=cache)
    with pytest.raises(Sp500ProviderError, match="SP500_CONSTITUENT_ROW_INVALID"):
        provider.universe("sp500", date(2026, 9, 22))


def test_distinct_tickers_may_share_one_cik(tmp_path: Path) -> None:
    cache = DiamondCache(tmp_path / "universe")
    rows = [
        {
            "ticker": "AAA",
            "cik": "320193",
            "company_name": "Issuer A",
            "sector": "Industrials",
            "industry_group": "Machinery",
        },
        {
            "ticker": "AAB",
            "cik": "320193",
            "company_name": "Issuer A Class B",
            "sector": "Industrials",
            "industry_group": "Machinery",
        },
    ]
    cache.store(
        Sp500UniverseProvider.SOURCE_URL,
        provider=Sp500UniverseProvider.PROVIDER,
        data_as_of=date(2026, 9, 22),
        payload=rows,
    )
    securities = Sp500UniverseProvider(client=None, cache=cache).universe(
        "sp500", date(2026, 9, 22)
    )
    assert [item.ticker for item in securities] == ["AAA", "AAB"]
    assert {item.issuer_id for item in securities} == {"sec-cik:0000320193"}
```

Also seed two identical tickers and assert `SP500_DUPLICATE_TICKER`.

- [ ] **Step 2: Run and verify RED**

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q tests/test_diamond_sp500_provider.py
```

Expected: at least one malformed cached-row case fails against current cache decoding.

- [ ] **Step 3: Implement one company validator**

Implement `_validate_company(company, index)` that strips/uppercases ticker, requires `_TICKER.fullmatch`, digit-only CIK length <=10, and non-empty company/sector/industry; return a normalized `Sp500Company` with zero-padded CIK. Apply it to both live parser rows and `_companies_from_payload`, then run one duplicate-ticker pass after normalization. Do not reject duplicate CIK.

- [ ] **Step 4: Verify and commit**

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q tests/test_diamond_sp500_provider.py
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync ruff check src/qhapaq_finance/diamond/providers/sp500.py tests/test_diamond_sp500_provider.py
git add src/qhapaq_finance/diamond/providers/sp500.py tests/test_diamond_sp500_provider.py
git commit -m "fix: validate cached S&P 500 membership"
```

---

### Task 8: Replace `repr(records)` with versioned canonical dataset identity

**Files:**
- Create: `src/qhapaq_finance/diamond/dataset_identity.py`
- Modify: `src/qhapaq_finance/diamond/funnel.py`
- Create: `tests/test_diamond_dataset_identity.py`
- Modify: `tests/test_diamond_live_funnel_slice.py`

**Interfaces:**
- Produces `DATASET_SCHEMA_VERSION`, `DATASET_CANONICALIZER_VERSION`, `fundamental_dataset_payload`, `dataset_identity`.

- [ ] **Step 1: Write a concrete identity fixture and invariance tests**

Use the existing Diamond record helper to construct two records, then `dataclasses.replace` their observation order. Assert:

```python
def test_record_order_does_not_change_identity() -> None:
    first = valid_record("AAA")
    second = valid_record("BBB")
    assert dataset_identity((first, second)) == dataset_identity((second, first))


def test_observation_order_does_not_change_identity() -> None:
    record = valid_record("AAA")
    reversed_record = replace(record, observations=tuple(reversed(record.observations)))
    assert dataset_identity((record,)) == dataset_identity((reversed_record,))


def test_one_observation_change_changes_identity() -> None:
    record = valid_record("AAA")
    first = record.observations[0]
    changed = replace(
        record, observations=(replace(first, value=first.value + 1.0), *record.observations[1:])
    )
    assert dataset_identity((record,)) != dataset_identity((changed,))
```

Also test `normalize_decimal` through the dataset projection for `10.0` and `-0.0`; since `FundamentalObservation` rejects non-finite values, assert Task 1's canonical primitive rejects NaN/Inf rather than bypassing the contract.

- [ ] **Step 2: Run and verify RED**

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q tests/test_diamond_dataset_identity.py
```

Expected: import failure.

- [ ] **Step 3: Implement the canonical dataset projection**

Constants:

```python
DATASET_SCHEMA_VERSION = "diamond-fundamental-dataset-v2"
DATASET_CANONICALIZER_VERSION = "fundamental-record-canonicalizer-v1"
```

Sort records by `(ticker, security_id, issuer_id)`. Sort observations by metric, fiscal slot, start/end, period kind, unit, source provider/identity, share class, adjustment basis, then normalized value. Encode dates as ISO strings, enums by `.value`, missing data as `None`, numeric fields as `normalize_decimal`, and include `evidence_diagnostics` sorted as strings.

The hashed root document is:

```python
{
    "schema_version": DATASET_SCHEMA_VERSION,
    "canonicalizer_version": DATASET_CANONICALIZER_VERSION,
    "records": record_payloads,
}
```

Hash `canonical_json_bytes(root)` with SHA-256.

- [ ] **Step 4: Replace the old funnel hash and add a provider-order regression**

Delete the local `_dataset_identity` based on `repr(records)` from `funnel.py` and import `dataset_identity` from the new module.

In `tests/test_diamond_live_funnel_slice.py`, run `run_funnel` against two fake providers containing the same records in opposite order and assert equal `metadata.dataset_identity` and equal ranked ticker order.

- [ ] **Step 5: Verify and commit**

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q tests/test_diamond_dataset_identity.py tests/test_diamond_live_funnel_slice.py
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync ruff check src/qhapaq_finance/diamond/dataset_identity.py src/qhapaq_finance/diamond/funnel.py tests/test_diamond_dataset_identity.py tests/test_diamond_live_funnel_slice.py
git add src/qhapaq_finance/diamond/dataset_identity.py src/qhapaq_finance/diamond/funnel.py tests/test_diamond_dataset_identity.py tests/test_diamond_live_funnel_slice.py
git commit -m "fix: canonicalize Diamond dataset identity"
```

---

### Task 9: Wire production composition, migrate caches, and prove Debt Zero acceptance

**Files:**
- Modify: `src/qhapaq_finance/diamond/cli.py`
- Modify: `tests/test_diamond_cli.py`
- Modify: `tests/test_diamond_live_funnel_slice.py`

**Interfaces:**
- Preserves literal user command `qhapaq funnel --universe sp500 --depth 10`.
- New runtime roots under `data/cache/diamond/`: `sec/index`, `sec/blobs`, `canonical`, `market`, `splits`, `universe`.

- [ ] **Step 1: Add CLI composition tests**

Monkeypatch constructors and assert the production factory passes these exact roots and refresh values:

```python
def test_production_funnel_wires_debt_zero_cache_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Path] = {}
    monkeypatch.setattr(
        diamond_cli,
        "SecEvidenceStore",
        lambda *, root, client, legacy_cache, now=None: capture_store(
            seen, "sec", root, client, legacy_cache
        ),
    )
    monkeypatch.setattr(
        diamond_cli, "CanonicalIssuerCache", lambda cache: capture_cache(seen, "canonical", cache)
    )
    monkeypatch.setattr(
        diamond_cli,
        "YahooSplitAdjustmentProvider",
        lambda *, client, cache, refresh: capture_split(seen, cache, refresh),
    )
    diamond_cli._production_funnel_provider(tmp_path, refresh=False)
    assert seen["sec"] == tmp_path / "sec"
    assert seen["canonical"] == tmp_path / "canonical"
    assert seen["splits"] == tmp_path / "splits"
```

Keep the pre-existing tests that prove no FMP key and no `AnalysisOrchestrator` are required.

- [ ] **Step 2: Run CLI tests and verify RED**

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q tests/test_diamond_cli.py
```

Expected: new composition test fails because v0.3 factory still constructs `SecFirstProvider` with raw `sec_cache`.

- [ ] **Step 3: Wire the production provider**

Construct one `SecClient`, then:

```python
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
```

Pass these into `SecFirstProvider`. The evidence store receives `refresh` at `resolve` time, so `--refresh` forces an unconditional SEC fetch and canonical rebuild; market and split providers keep their existing refresh constructor behavior.

- [ ] **Step 4: Run all automated gates before any live acceptance**

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync ruff format --check .
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync ruff check .
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync mypy --no-incremental src
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q
git diff --check
```

Expected: all PASS.

- [ ] **Step 5: Prove protected paths and stash before live work**

```bash
test -z "$(git status --short -- .env.example data/cache/sec/company_tickers.json)"
git rev-parse --verify stash@{0}
git stash list | head -n 3
```

Expected: protected status empty and existing stash present.

- [ ] **Step 6: Run the literal command once to seed/migrate v0.4 caches**

```bash
/usr/bin/time -f 'wall_seconds=%e' \
  qhapaq funnel --universe sp500 --depth 10 \
  --as-of 2026-09-22 --format json \
  >/tmp/qhapaq-debt-zero-live.json \
  2>/tmp/qhapaq-debt-zero-live.err
```

Read stderr and JSON. Assert `len(payload["results"]) == 10`. The first v0.4 run may pay one-time legacy SEC parsing, canonical snapshot creation, and split-evidence acquisition.

- [ ] **Step 7: Run the literal command again and prove warm replay acceptance**

```bash
/usr/bin/time -f 'wall_seconds=%e' \
  qhapaq funnel --universe sp500 --depth 10 \
  --as-of 2026-09-22 --format json \
  >/tmp/qhapaq-debt-zero-replay.json \
  2>/tmp/qhapaq-debt-zero-replay.err
```

Then:

```bash
python3 - <<'PY'
import json
from pathlib import Path

live = json.loads(Path('/tmp/qhapaq-debt-zero-live.json').read_text(encoding='utf-8'))
replay = json.loads(Path('/tmp/qhapaq-debt-zero-replay.json').read_text(encoding='utf-8'))
assert replay['metadata']['provider_requests'] == 0
assert replay['metadata']['cache_misses'] == 0
assert replay['metadata']['acquisition_seconds'] <= 10.0
assert live['metadata']['dataset_identity'] == replay['metadata']['dataset_identity']
assert [row['ticker'] for row in live['results']] == [row['ticker'] for row in replay['results']]
print('DEBT_ZERO_REPLAY=PASS')
print('acquisition_seconds=', replay['metadata']['acquisition_seconds'])
PY
```

Do not weaken the TTL, cache counters, or 10-second criterion to obtain PASS.

- [ ] **Step 8: Prove amendment invalidation with deterministic tests, not production-cache mutation**

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q \
  tests/test_diamond_sec_evidence.py::test_stale_manifest_without_validators_refetches_unconditionally \
  tests/test_diamond_sec_canonical.py::test_canonical_cache_revision_mismatch_fails_closed
```

Also run the stale-manifest + 304 and stale-manifest + changed-200 cases from Task 3. Expected: PASS.

- [ ] **Step 9: Prove `qhapaq analyze` remains unchanged**

Run existing analyze/CLI tests without editing analyze production code:

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q tests/test_cli.py
```

If repository collection shows analyze-specific tests in another existing `tests/test_*cli*.py` module, include that module in the same command; record exact module names in the execution ledger.

- [ ] **Step 10: Run final repository verification after live acceptance**

```bash
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync ruff format --check .
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync ruff check .
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync mypy --no-incremental src
UV_CACHE_DIR=/tmp/qhapaq-uv-cache uv run --no-sync pytest -q
git diff --check
test -z "$(git status --short -- .env.example data/cache/sec/company_tickers.json)"
git rev-parse --verify stash@{0}
```

Expected: all PASS; protected files untouched; stash preserved.

- [ ] **Step 11: Commit the production wiring**

```bash
git add src/qhapaq_finance/diamond/cli.py tests/test_diamond_cli.py tests/test_diamond_live_funnel_slice.py
git diff --cached --check
git commit -m "feat: complete Diamond Funnel Debt Zero v0.4"
```

Never stage `data/cache/diamond/`, `.env.example`, `data/cache/sec/company_tickers.json`, or any runtime cache artifact.

---

## Self-Review Record

### Spec coverage

- SEC manifest/blob store, bounded TTL, 304/200 revalidation, wrong-CIK/checksum failure, and legacy migration: Task 3.
- Amendment point-in-time semantics, canonical issuer cache, version/revision invalidation, no raw blob load on warm hit, shared-CIK reuse: Tasks 4–5.
- Market-cap split safety, direct/same-date/covered derivation, no grace window, explicit diagnostics, null-aware Compounder behavior: Task 6.
- S&P live/cache validation parity and repeated CIK allowance: Task 7.
- Canonical decimal JSON and deterministic dataset identity: Tasks 1 and 8.
- Literal CLI, warm replay `<= 10s`, zero requests/misses, full regression, protected files, stash, and analyze non-regression: Task 9.

### Type consistency

- Task 3 `ResolvedSecEvidence` feeds Task 5 canonicalization.
- Task 4 `CanonicalIssuerCache` is consumed by Task 5 and wired in Task 9.
- Task 6 `SplitAdjustmentProvider` is accepted by the Task 5 `SecFirstProvider` constructor and wired in Task 9.
- Task 6 finalizes the `FundamentalRecord` shape before Task 8 freezes dataset serialization.
- Task 1 numeric/JSON primitives are available before Task 3 evidence revision and Task 8 dataset identity.

### Placeholder scan

Every code step specifies executable signatures, assertions, commands, or exact behavior. Test-only helper names introduced in Tasks 5 and 9 are required to be implemented in the same test module as small capture/counter wrappers; they do not alter production contracts.

### Review-focus coverage

All five Review Focus items are tied to an explicit named regression test in the owning task: same-day split ambiguity (Task 6), stale SEC manifest without validators (Task 3), wrong-`as_of` legacy cache (Task 3), canonical revision mismatch (Task 4), and shared-CIK multi-security reuse (Task 5).
