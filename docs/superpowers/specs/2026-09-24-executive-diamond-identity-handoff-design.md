# Executive ↔ Diamond Authoritative Identity Handoff

Status: Approved design.

## Problem

Diamond Funnel successfully ranks the real S&P 500 snapshot, but
Executive Shortlist loses the authoritative issuer identity before
Deep Analysis.

The real 2026-09-22 Top-5 is:

1. MO
2. UBER
3. CRH
4. BKNG
5. RMD

Diamond acquired those companies through SEC-first evidence and its
input FundamentalRecord already contains:

- ticker
- security_id
- issuer_id
- company_name
- provider identity

For SEC-first records, issuer_id is `sec-cik:<CIK>`.

However DiamondResult currently preserves ticker/company/provider
evidence identity but discards the input SecurityRef identity.

Executive then calls:

    AnalysisOrchestrator.analyze(candidate.ticker)

AnalysisOrchestrator therefore performs a second independent
CompanyResolver lookup.

The local company reference is intentionally small and does not
contain any of the real Top-5. All five return None. Analysis then
attempts an authoritative refresh and an offline replay becomes
BLOCKED before evidence or valuation.

This is an identity handoff defect, not a ranking or valuation defect.

## Ruling

Preserve the exact provider-neutral SecurityRef used to construct each
Diamond result and reuse that authoritative identity when Executive
invokes Deep Analysis.

Do not regenerate, guess, or infer CIK from provider_identity.

## Invariants

- Diamond ranking and scoring do not change.
- Diamond ordering does not change.
- dataset_identity does not change.
- provider_identity remains evidence identity only.
- SEC evidence hashes are never interpreted as issuer identity.
- No static ticker allowlist.
- No mutation or replacement of data/cache/sec/company_tickers.json.
- No network request is introduced by the identity handoff.
- Existing qhapaq analyze TICKER behavior remains unchanged.
- Existing injected custom analyzers used by Executive tests remain
  supported.
- Missing or malformed identity remains fail-closed.
- Executive never reclassifies or reranks Diamond results.

## DiamondResult identity

DiamondResult gains an internal optional source SecurityRef.

Conceptually:

    source_security: SecurityRef | None = None

evaluate_universe MUST populate it from the exact FundamentalRecord:

    ticker      = record.ticker
    security_id = record.security_id
    issuer_id   = record.issuer_id

No identity field is recalculated.

Legacy direct DiamondResult constructors may omit source_security so
existing isolated tests and fixtures remain compatible.

## Public Diamond serialization

This change does not alter the existing diamond-funnel-v1 serialized
JSON/CSV surface.

source_security is an internal orchestration/provenance handoff in this
version.

A future schema version may expose it explicitly, but this bug fix does
not silently extend diamond-funnel-v1.

## Executive resolver

Production run_shortlist constructs an identity-aware resolver for the
Diamond Top-N before invoking Deep Analysis.

For a candidate with:

    provider == "sec-first"
    source_security.issuer_id == "sec-cik:<CIK>"

the resolver returns a ResolvedCompany using:

- candidate ticker
- candidate company_name
- exact CIK from issuer_id
- no invented exchange
- explicit Diamond/SEC provenance

The evidence hash in provider_identity MUST NOT be inserted into a
company-reference checksum field because those identities represent
different semantic objects.

For an authoritative identity supplied directly by Diamond, the
ResolvedCompany provenance is semantic handoff provenance, not a claim
that the identity was re-read from the local company-reference cache.

Use:

    CompanyProvenance(
        source_url="diamond://sec-first/security-ref",
        fetched_at=None,
        raw_sha256=None,
        raw_byte_size=None,
    )

The synthetic URI identifies the handoff boundary. It MUST NOT be replaced
with the SEC company-tickers URL unless that file was actually the source
used for that resolution, and provider_identity MUST NOT be copied into
raw_sha256.

## Fallback

The identity-aware resolver is composed with the existing
CompanyResolver.

Resolution order:

1. exact Diamond Top-N authoritative identity
2. existing CompanyResolver behavior

Therefore:

- production Diamond candidates avoid redundant resolution;
- ordinary qhapaq analyze TICKER semantics stay unchanged;
- legacy candidates without source_security keep current behavior.

The composed resolver MUST satisfy RefreshableSymbolResolver, not only
SymbolResolver.

Its behavior is:

    resolve(ticker):
        1. return exact authoritative Diamond identity when present;
        2. otherwise delegate to the existing CompanyResolver.

    refresh(client):
        delegate unchanged to the existing CompanyResolver.

This is required because AnalysisOrchestrator gates its one authoritative
refresh through RefreshableSymbolResolver. The composition must preserve
that existing fallback behavior rather than accidentally converting a
refreshable resolver into a resolve-only resolver.

## Deep Analysis contract

DeepAnalysisOrchestrator continues to call:

    analyzer.analyze(candidate.ticker)

It does not acquire SEC identity itself and does not need a new public
analyzer protocol.

The AnalysisOrchestrator supplied by run_shortlist receives the
composed resolver.

Concurrency, order preservation, and exception semantics remain
unchanged.

## Terminal reason propagation

A second observed bug exists independently of identity resolution.

When AnalysisOrchestrator normally returns BLOCKED or
EVIDENCE_REQUIRED, DeepAnalysisOrchestrator currently preserves the
status but writes:

    reason=None

Executive already has a reason field in its stable output contract.

For a non-completed AnalysisResult, Deep Analysis must propagate the
first non-empty reason belonging to a BLOCKED stage in lifecycle order:

1. acquisition
2. evidence
3. research
4. valuation
5. publishing

If there is no BLOCKED-stage reason, reason remains None.

This does not change source_status, conclusion_available, expectations,
or bottom_line.

## Design review rulings

Repository review was performed against commit `0762ab6`.

Ruling: the composed Executive resolver implements
RefreshableSymbolResolver and delegates refresh to the existing
CompanyResolver — AnalysisOrchestrator explicitly requires that protocol
before its authoritative-refresh path — omitting delegation would change
the promised legacy fallback behavior.

Ruling: Diamond-authoritative company provenance uses
`diamond://sec-first/security-ref` with no fabricated fetch timestamp,
checksum, or byte size — Diamond is the actual identity handoff boundary
and provider_identity is a different semantic object — using the local
company-reference URL or evidence hash would assert provenance that did
not occur.

Repository review also confirmed:

- Diamond public JSON/CSV serialization is an explicit projection rather
  than an automatic serialization of every DiamondResult field;
- dataset_identity is calculated from FundamentalRecord inputs, not from
  DiamondResult;
- DeepAnalysisOrchestrator already supports an injected synchronous
  analyzer;
- AnalysisOrchestrator already supports an injected SymbolResolver;
- the normal non-exception Deep Analysis path currently discards terminal
  stage reason by assigning reason=None;
- Executive baseline tests and Ruff were green before implementation;
- Dataset Snapshot production implementation remains outside this patch.

## TDD sequence

### RED 1 — Diamond preserves source identity

Given a FundamentalRecord with known security_id and issuer_id,
evaluate_universe must return a DiamondResult containing the exact
SecurityRef.

The test must fail on current HEAD because DiamondResult has no such
field.

### GREEN 1

Add the smallest source_security field and copy it directly from the
record.

Verify existing Diamond serialization remains byte-compatible where
already frozen.

### RED 2 — production Executive reuses Diamond identity

Given a Diamond candidate with a sec-cik issuer identity and an
underlying CompanyResolver that cannot resolve the ticker, production
Executive analysis must reach AnalysisOrchestrator using the supplied
CIK without performing an authoritative identity refresh.

### GREEN 2

Introduce the smallest composed resolver and inject it only in the
production run_shortlist path.

### RED 3 — terminal reason is preserved

Given a normal AnalysisResult with status BLOCKED and a blocked stage
reason, DeepAnalysisOrchestrator must expose that reason through
ExecutiveAnalysisStatus.

### GREEN 3

Extract the existing stage reason deterministically. Do not invent new
reason text.

## Acceptance

The frozen 2026-09-22 replay must retain:

- dataset_identity:
  46677793154fc2a7888361aa613d9c61db124b5f5b1eb414a4b3ad471a05c2a2
- Diamond Top-5:
  MO, UBER, CRH, BKNG, RMD
- provider_requests=0 for Diamond acquisition
- cache_misses=0 for Diamond acquisition

Executive must no longer block those five because of:

    authoritative company resolution could not complete

Any later EVIDENCE_REQUIRED or BLOCKED state must expose its actual
reason.

The change is not accepted merely because the Executive process exits
zero. At least one candidate must demonstrably cross the previous
identity-resolution boundary.

## Non-goals

- No Diamond scoring changes.
- No accounting changes.
- No Goal Seek changes.
- No valuation assumption changes.
- No new SEC downloads for the frozen replay.
- No repair of the small company_tickers cache.
- No Dataset Snapshot implementation in this patch.
- No attempt to force all five candidates to COMPLETED.
