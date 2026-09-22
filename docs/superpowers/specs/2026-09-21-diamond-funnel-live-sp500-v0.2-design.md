# Diamond Funnel Live S&P 500 v0.2 Design

**Status:** Approved
**Product:** Qhapaq Finance
**Parent baseline:** Diamond Funnel v0.1 @ 1143f92

## 1. Goal

Make the real research funnel work end to end:

    real S&P 500 universe
            ↓
    structured low-cost fundamentals
            ↓
    canonical Diamond FundamentalRecord
            ↓
    existing Diamond engine
            ↓
    top-N research shortlist
            ↓
    explicit qhapaq analyze TICKER
            ↓
    existing SEC / Qhapaq One pipeline

Primary acceptance command:

    qhapaq funnel --universe sp500 --depth 10

The funnel is research routing, not an investment recommendation.

## 2. Non-goals

v0.2 does not:

- redesign Diamond metrics, percentiles, scores, or archetypes
- change qhapaq analyze semantics
- run SEC acquisition across the entire S&P 500
- add BUY/HOLD/SELL
- add target prices
- make the deep-analysis pipeline implicit
- mutate the SEC ticker cache
- refactor unrelated Qhapaq components

## 3. Existing contracts remain authoritative

Reuse:

    FundamentalDataProvider.universe(...)
    FundamentalDataProvider.fundamentals(...)

Reuse unchanged:

    FundamentalRecord
    FundamentalObservation
    FiscalSlot
    Methodology
    evaluate_universe(...)

The live provider adapts external data to the existing contracts.
The contracts are not weakened to fit the provider.

## 4. Provider

First production provider: Financial Modeling Prep (FMP).

Authentication:

    FMP_API_KEY

Secrets must never be:

- logged
- serialized
- written to cache
- committed
- included in sanitized request identities

The FMP adapter owns only:

1. universe acquisition
2. provider HTTP interaction
3. provider response validation
4. provider → canonical mapping

It does not own Diamond scoring.

## 5. Universe

`sp500` membership is obtained from the provider.

Each member becomes a SecurityRef with:

- canonical ticker
- stable provider-derived security identity
- issuer identity

Provider punctuation differences such as class-share symbols are normalized
inside the provider boundary.

The SEC company ticker cache is not used or modified for this translation.

## 6. Fundamental mapping

The provider must supply, when available:

Duration observations:

- revenue
- operating_income
- operating_cash_flow
- capital_expenditures
- pretax_income
- income_tax_expense
- diluted_shares

Instant observations:

- cash_and_equivalents
- marketable_securities
- total_debt
- total_equity
- shares_outstanding_latest
- shares_outstanding_fy1_end
- market_cap
- enterprise_value_provider

Fiscal slots:

- TTM
- FY1
- FY2
- FY3
- FY4
- FY5
- LATEST

Provider absence remains absence.

No forward filling.
No invented zeroes.
No annual/quarter mixing.
No duplicate metric/slot combinations.

Canonical capex is a positive outflow regardless of provider sign.

Share observations must carry compatible share/basis metadata when required
by Diamond dilution logic.

## 7. Methodology

Only records safely identified as operating companies participate in
normal ranking.

Financial institutions, insurers, REITs, and uncertain classifications
remain visible but unranked according to existing Diamond behavior.

Classification must be deterministic from provider metadata.

## 8. HTTP boundary

Create a Diamond-specific HTTP client rather than coupling FMP to SecClient.

Required behavior:

- injectable transport for tests
- connect/read timeout
- bounded retry count
- retry 429 and transient 5xx
- honor Retry-After when present
- exponential backoff otherwise
- 401/403 fail explicitly
- malformed JSON fails closed
- schema drift fails closed
- API key never appears in raised messages

Do not retry deterministic 4xx failures.

## 9. Cache and replay

Use a new cache namespace:

    data/cache/diamond/fmp/

The cache must not overlap SEC caches.

Cache artifacts contain:

- provider
- endpoint/request identity with secrets removed
- retrieved_at
- data_as_of
- response checksum
- raw response body or equivalent immutable evidence
- normalized canonical artifact checksum
- schema version

Writes are atomic.

Corrupt cache entries fail closed.

Default behavior:

- use valid fresh cache
- fetch when required data is absent/expired

Explicit:

    --refresh

forces provider refresh.

A cached replay must not require FMP credentials if all required artifacts
already exist and validate.

## 10. Funnel service

Add a small orchestration boundary under Diamond that:

1. resolves provider
2. obtains universe
3. obtains/canonicalizes fundamentals
4. invokes existing evaluate_universe
5. ranks existing DiamondResult values
6. returns top N plus run metadata

It must not import or call AnalysisOrchestrator.

Run metadata includes:

- universe_count
- canonical_records
- ranked_records
- unranked_records
- provider_requests
- cache_hits
- cache_misses
- acquisition_seconds
- evaluation_seconds
- dataset checksum / identity

## 11. CLI

Add:

    qhapaq funnel --universe sp500 --depth 10

Optional:

    --refresh
    --format table|json|csv

Default table exposes:

- ticker
- company
- research_priority
- surfaced_by
- quality
- growth
- capital
- price
- peer_scope
- diagnostics

Stable JSON stdout contains product results and deterministic dataset/run
identity.

Operational progress/statistics go to stderr or structured metadata and do
not corrupt JSON stdout.

`qhapaq screen`, `inspect`, and `provider-benchmark` remain unchanged.

## 12. Explicit downstream handoff

The funnel stops after shortlist creation.

Deep research stays explicit:

    qhapaq analyze TICKER

One ticker surfaced by the live funnel must be accepted by the existing
generic analyze path and reach its real typed result:

- COMPLETED
- EVIDENCE_REQUIRED
- BLOCKED

No result is fabricated to satisfy acceptance.

## 13. Failure semantics

Provider-wide failures that stop the run:

- authentication failure
- provider plan/access failure when no semantically equivalent endpoint exists
- malformed provider schema
- corrupt cache
- inconsistent universe identity
- canonical ambiguity that invalidates the dataset

Per-company incomplete evidence may produce an unranked company with an
explicit diagnostic when existing Diamond contracts safely allow it.

## 14. Current FMP authentication state

As of the design session, the configured FMP credential returns HTTP 401
for both query-string and header authentication.

Therefore live acceptance is currently externally blocked.

This does not block:

- provider implementation
- deterministic provider tests
- canonical mapping tests
- cache/replay tests
- CLI integration tests

Completion must not be claimed until a valid provider credential permits
a real live run.

## 15. Tests

All provider tests are network-free.

Coverage must prove at minimum:

- S&P 500 universe mapping
- symbol normalization
- annual fiscal-slot mapping
- TTM mapping
- capex sign normalization
- OCF semantics
- diluted-share basis
- cash / marketable securities handling
- debt and equity mapping
- market-cap handling
- null preservation
- duplicate/conflicting period rejection
- stale-data behavior
- 401/403 behavior
- 429 Retry-After behavior
- transient 5xx retries
- malformed JSON
- provider schema drift
- cache hit
- cache corruption
- deterministic replay
- funnel CLI does not invoke AnalysisOrchestrator
- depth behavior
- stable JSON
- v0.1 screen compatibility
- inspect compatibility
- benchmark compatibility
- analyze regression

## 16. Protected scope

Must remain unchanged:

    .env.example
    data/cache/sec/company_tickers.json

Must preserve:

    stash@{0}: local: preserve company_tickers before Diamond Funnel v0.1

Normally do not modify:

    analysis.py
    accounting.py
    financial_promotion.py
    sec_canonical_gate.py
    sec_filing_plan.py
    sec_filing_xbrl.py

## 17. Definition of done

v0.2 is complete only when:

1. no manually prepared Diamond fixture is required
2. S&P 500 membership is real provider data
3. provider fundamentals become existing canonical Diamond records
4. existing Diamond engine evaluates them
5. `qhapaq funnel --universe sp500 --depth 10` returns real companies
6. broad screening does not invoke deep SEC analysis
7. cache replay is deterministic
8. one surfaced ticker passes into existing `qhapaq analyze`
9. existing Diamond v0.1 regression remains green
10. full repository regression remains green
11. protected files remain unchanged
12. live provider acceptance is actually demonstrated
