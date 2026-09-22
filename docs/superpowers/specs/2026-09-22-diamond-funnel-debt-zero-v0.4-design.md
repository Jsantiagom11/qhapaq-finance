# Diamond Funnel Debt Zero v0.4

Status: Proposed — pending human review.

## Objective

Remove the known technical debt in the live SEC-first Diamond Funnel without changing Diamond scoring semantics or turning correctness gaps into heuristics.

The target user flow remains:

```text
qhapaq funnel --universe sp500 --depth 10
```

A warm replay of the same evidence snapshot must use zero network requests and complete acquisition in seconds rather than re-parsing every SEC `companyfacts` payload.

## Current problems

The v0.3 SEC-first funnel is functionally live, but five structural debts remain:

1. SEC `companyfacts` cache hits still deserialize, checksum, filter, promote, and rebuild issuer fundamentals on every replay.
2. The current SEC form filter accepts `10-K` and `10-Q` but not `10-K/A` or `10-Q/A`, so amendments are not represented explicitly.
3. Market capitalization may be derived from a current price and an older SEC share count without evidence that no stock split occurred between the two observation dates.
4. `dataset_identity` hashes `repr(records)`, which is deterministic only accidentally and is not a versioned wire contract.
5. S&P 500 data loaded from cache is not validated through exactly the same semantic validator as live-parsed membership.

## Invariants

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

## Architecture

```text
S&P 500 membership
    -> SecurityRef + issuer metadata
    -> SEC evidence manifest / immutable raw blob
    -> CanonicalIssuerSnapshot cache
    -> per-security market overlay
    -> FundamentalRecord
    -> existing Diamond engine
    -> Top N
```

The core change is to separate issuer-level accounting canonicalization from security-level market enrichment.

## 1. SEC evidence store and amendment-aware invalidation

### 1.1 Raw evidence layout

SEC `companyfacts` must no longer require parsing a large monolithic cache document merely to discover whether canonical data can be reused.

Introduce an SEC-specific evidence store with a lightweight manifest and immutable content-addressed blob.

Conceptual layout:

```text
data/cache/diamond/sec/
  index/<request-hash>.json
  blobs/<payload-sha256>.json
```

The manifest contains at least:

- cache schema version
- CIK
- request identity
- `retrieved_at`
- `data_as_of`
- raw `payload_sha256`
- semantic `evidence_revision_sha256`
- latest in-scope filing date
- latest in-scope accession number
- HTTP `ETag` when supplied
- HTTP `Last-Modified` when supplied
- blob identity/path

The blob contains the raw SEC response and is checksum verified when consumed.

A warm canonical-cache replay reads the small manifest first. It must not deserialize or checksum the raw blob unless the canonical snapshot is absent, invalid, or the SEC evidence must be revalidated.

### 1.2 Forms and point-in-time semantics

Accepted SEC forms for accounting evidence become:

- `10-K`
- `10-K/A`
- `10-Q`
- `10-Q/A`

Only facts whose filing date and period end are `<= as_of` are in scope.

An amendment filed after `as_of` must not change a historical point-in-time run. An amendment filed on or before `as_of` is eligible evidence.

For the same metric, unit, and economic period, the most recent in-scope filing/accession may supersede earlier evidence only when the result is unambiguous under the existing promotion rules. Conflicting values in the same winning evidence rank fail closed; they are never averaged or selected arbitrarily.

`latest_in_scope_accession` is traceability metadata, not the sole invalidation key.

### 1.3 Semantic evidence revision

After SEC facts are filtered to the point-in-time evidence set, build a deterministic semantic representation and hash it as `evidence_revision_sha256`.

This hash is stronger than accession alone because it changes when any in-scope fact that can affect canonicalization changes, even if remote metadata is rewritten without a new accession.

The canonical issuer cache is keyed by this semantic evidence revision, not only by retrieval time.

### 1.4 Active revalidation policy

A passive cache cannot detect a remote SEC amendment without network activity. v0.4 therefore guarantees bounded staleness rather than impossible instantaneous invalidation.

Default soft TTL:

- `as_of` within the last 2 calendar days: 6 hours
- older historical `as_of`: 7 days

Within TTL, warm replay performs zero SEC network requests.

When the manifest is stale:

1. use conditional HTTP revalidation with `ETag` and/or `Last-Modified` when available;
2. on `304 Not Modified`, update freshness metadata and keep the existing evidence revision and canonical snapshot;
3. on `200`, validate issuer identity, store the new immutable blob, recompute the in-scope semantic evidence revision, and rebuild canonical data only when that revision changed;
4. if revalidation is required but cannot be completed, fail closed with a typed SEC revalidation error rather than silently treating stale evidence as current.

`--refresh` bypasses TTL and forces an unconditional SEC fetch/revalidation.

The TTL values are operational constants covered by tests and may be made configurable later; v0.4 does not add a new configuration subsystem.

## 2. Canonical issuer cache

### 2.1 Cache the expensive accounting result, not the final ranking

Introduce an internal immutable `CanonicalIssuerSnapshot` representing issuer-level SEC-derived fundamentals.

It contains:

- canonical cache schema version
- canonicalizer version
- issuer ID / CIK
- `as_of`
- `history_years`
- `evidence_revision_sha256`
- fundamental period type/end
- fiscal-year-end metadata derived from SEC evidence
- canonical issuer-level observations

It must not contain:

- ticker-specific market price
- derived security-level market capitalization
- `market_age_trading_days`
- S&P 500 sector/GICS classification
- final scores, percentiles, archetypes, or rankings

This prevents stale market data or universe metadata from being frozen into the SEC canonical cache and allows multiple securities sharing one issuer CIK to reuse the same accounting snapshot.

### 2.2 Cache identity

The canonical request identity includes at least:

```text
canonical_schema_version
canonicalizer_version
issuer_id
as_of
history_years
evidence_revision_sha256
```

Any change to the semantic SEC evidence or canonicalization contract produces a different identity automatically.

`--refresh` rebuilds the canonical snapshot after raw SEC evidence is refreshed.

### 2.3 Final FundamentalRecord assembly

For each `SecurityRef`:

1. load/rebuild its issuer's `CanonicalIssuerSnapshot` once per unique CIK;
2. combine it with current universe metadata;
3. apply the current security-level market quote and only safe market-derived observations;
4. build the existing `FundamentalRecord` passed to the Diamond engine.

Repeated CIKs are allowed because multiple share classes can belong to the same issuer. Duplicate security tickers remain invalid.

## 3. Market-cap safety and null semantics

### 3.1 No grace window

There is no rule such as “shares reported less than 30 days ago are assumed safe.” Time proximity is not evidence that no split occurred.

A derived market capitalization is permitted only when one of these is true:

1. the market provider supplies a direct market-cap observation with a trusted source identity; or
2. SEC shares and price have the same observation date; or
3. explicit split-adjustment evidence covers the entire interval from the SEC share observation date through the price observation date.

For case 3:

```text
adjusted_shares = reported_shares * cumulative_split_factor
market_cap = adjusted_shares * price
```

The split factor and coverage interval must be evidence-backed and cached. If complete split evidence is unavailable, `market_cap = None`.

A share observation later than the quote date is not used to derive market capitalization.

### 3.2 Missing market cap must not become silent exclusion

The existing Diamond score model already supports missing category inputs. v0.4 preserves that behavior:

- missing market cap can make normalized FCF yield / price category unavailable;
- `QUALITY_VALUE` and `INFLECTION` may therefore be unavailable;
- `COMPOUNDER` remains eligible when quality, growth, and capital satisfy their existing requirements;
- the security remains present in the evaluated universe unless another existing methodology rule makes it unrankable.

Add an explicit diagnostic such as `MARKET_CAP_SPLIT_UNVERIFIED` when a price exists but market capitalization is withheld because split compatibility cannot be established.

No scoring weight or minimum-present threshold changes to compensate for missing market evidence.

## 4. Canonical dataset identity

### 4.1 Replace `repr(records)`

`dataset_identity` becomes SHA-256 over a versioned canonical JSON representation of the fully assembled `FundamentalRecord` dataset after safe market overlay and before scoring.

Canonical dataset ordering:

- records sorted by `(ticker, security_id, issuer_id)`;
- observations sorted by stable semantic keys including metric, fiscal slot, period, provider/source identity, share class, and adjustment basis;
- dictionaries sorted by key;
- dates encoded as ISO-8601 strings;
- enums encoded by stable string value;
- missing values encoded as JSON `null`.

### 4.2 Numeric representation

Raw IEEE-754 JSON floats are not part of the hash contract.

Every finite numeric value in the canonical wire representation is encoded as a normalized decimal string.

Normalization contract:

1. integers and decimals are converted to `Decimal` without loss;
2. existing in-memory floats are converted with `Decimal(repr(value))` so their exact Python value is captured deterministically;
3. exponent notation is expanded to fixed-point form;
4. insignificant trailing fractional zeros are removed;
5. `-0` normalizes to `0`;
6. `NaN`, positive infinity, and negative infinity are rejected;
7. no quantization or rounding is applied merely to stabilize a hash.

Therefore semantically equivalent lexical inputs such as `10`, `10.0`, and `10.00` serialize to the same canonical string `"10"`.

If arithmetic/canonicalization logic intentionally changes, `canonicalizer_version` must change. That is an intentional dataset identity boundary rather than hidden hash drift.

### 4.3 JSON byte contract

The canonical JSON bytes use:

```text
sort_keys=True
separators=(",", ":")
ensure_ascii=False
allow_nan=False
UTF-8
```

The dataset schema version is included in the hashed document.

## 5. S&P 500 cache validation parity

Live-parsed and cache-loaded constituent rows must pass one shared semantic validator.

It validates at least:

- canonical ticker format
- numeric CIK with maximum length 10 and zero-padding to 10 digits
- non-empty company name
- non-empty sector
- non-empty industry group
- unique ticker/security identity

A repeated CIK is allowed when distinct securities/share classes map to the same issuer.

Malformed cached membership fails closed with a typed S&P 500 cache/schema error.

## 6. Failure semantics

- Corrupt manifest, checksum mismatch, wrong provider, wrong CIK, unsupported schema, or ambiguous winning SEC facts fail closed.
- Required stale SEC evidence that cannot be revalidated fails closed; it is not silently treated as fresh.
- Optional market acquisition may remain missing under the existing broad-screen behavior, but missing market evidence is explicit in diagnostics.
- No exception path may silently drop a security from the universe because a derived market cap is unavailable.

## 7. Migration and compatibility

- Existing SEC cache files are preserved.
- v0.4 may read the v0.3 monolithic SEC cache once to seed the new manifest/blob and canonical snapshot when the existing entry is valid and fresh enough.
- Migration must not force ~503 network fetches solely because the cache layout changed.
- The first canonical build may still perform the expensive SEC parse once; subsequent warm replays must not.
- Existing universe and Yahoo caches remain usable where their schemas are still valid.
- New canonical/cache artifacts remain under ignored `data/cache/diamond/` paths.
- No cache artifact is committed.

## 8. Required tests

### SEC invalidation and amendments

- `10-K/A` and `10-Q/A` are accepted as point-in-time evidence.
- amendment after `as_of` does not alter a historical snapshot.
- in-scope amendment changes `evidence_revision_sha256` when relevant evidence changes.
- fresh manifest performs zero SEC network requests.
- stale manifest + `304` preserves evidence revision and canonical cache.
- stale manifest + changed `200` invalidates only affected issuer canonical data.
- failed required revalidation raises the typed failure.
- wrong CIK and corrupt blob fail closed.

### Canonical issuer cache

- first build canonicalizes once.
- warm replay does not load/parse the raw SEC blob when a valid canonical snapshot exists.
- two securities sharing a CIK reuse one issuer snapshot.
- market/universe metadata changes do not invalidate the accounting snapshot.
- canonicalizer-version change invalidates canonical cache.

### Market-cap safety

- direct provider market cap is accepted.
- same-date shares and price may derive market cap.
- split-covered interval derives adjusted market cap correctly.
- unverified interval yields `market_cap=None` and `MARKET_CAP_SPLIT_UNVERIFIED`.
- no 30-day or similar grace heuristic exists.
- missing market cap does not remove the security; Compounder eligibility remains governed by existing quality/growth/capital requirements.

### Dataset identity

- record ordering does not affect identity.
- observation ordering does not affect identity.
- `10`, `10.0`, and `10.00` canonicalize to the same numeric representation.
- `-0.0` and `0` canonicalize identically.
- NaN/Inf are rejected.
- one real observation change changes the identity.
- schema/canonicalizer-version changes change identity intentionally.

### Universe cache

- cached and live rows pass the same validator.
- malformed cached ticker/CIK/metadata fails closed.
- duplicate ticker fails closed.
- distinct tickers sharing one CIK remain valid.

## 9. Acceptance criteria

All of the following must be proven before v0.4 is complete:

1. Literal command works in the user's normal shell environment:

   ```text
   qhapaq funnel --universe sp500 --depth 10
   ```

2. A live/current run returns a real S&P 500 shortlist with at least 10 rankable securities when evidence permits.
3. A warm replay of the same evidence snapshot performs `provider_requests=0` and `cache_misses=0`.
4. On the existing user machine and warmed caches, funnel acquisition is <= 10 seconds, compared with the current ~241-second replay baseline.
5. Warm replay preserves the same dataset identity and Top N when no evidence changed.
6. An in-scope SEC amendment is detected after the revalidation window and invalidates only affected issuer canonical data.
7. Unsafe market-cap derivation is removed; no grace heuristic is introduced.
8. Missing market cap remains explicit and does not crash the engine or silently remove the security.
9. Dataset identity is produced from the canonical JSON contract, never `repr()`.
10. `qhapaq analyze TICKER` behavior remains unchanged.
11. Ruff format/check pass.
12. mypy passes.
13. Diamond-focused tests pass.
14. full `pytest -q` passes.
15. `git diff --check` passes.
16. `.env.example` and `data/cache/sec/company_tickers.json` remain untouched.
17. the pre-existing stash remains preserved.

## 10. Explicit decisions for the three structural failure vectors

### SEC amendments

Do not rely exclusively on `--refresh` and do not key invalidation only by accession number. Use bounded automatic SEC revalidation plus raw payload checksum, a semantic in-scope evidence revision hash, and latest filing/accession metadata. `--refresh` remains the explicit force mechanism.

### Market-cap null cascade

Do not add a time-based grace threshold. Missing market cap is a supported evidence state. Preserve existing null-aware scoring semantics, expose a diagnostic, and allow non-price archetypes such as Compounder to rank a company when their existing inputs are complete.

### Dataset identity precision

Do not hash raw floating-point JSON or Python `repr(records)`. Hash versioned canonical JSON whose numeric fields are normalized decimal strings. Use `Decimal` at the serialization boundary, reject non-finite values, and include schema/canonicalizer versions in the identity contract.

## Non-goals

- Redesigning Diamond scoring.
- Adding buy/hold/sell labels or price targets.
- Caching Top N or completed score output as the primary optimization.
- Replacing SEC as the broad fundamental source.
- Making FMP paid endpoints mandatory.
- Building a generalized distributed cache or database.
- Optimizing `qhapaq analyze TICKER`.
