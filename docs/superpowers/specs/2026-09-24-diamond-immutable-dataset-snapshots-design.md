# Diamond Immutable Dataset Snapshots v0.5

Status: Proposed architecture for review.

## Objective

Make Diamond Funnel and Executive Shortlist reproducible across dates,
Git worktrees and offline replay.

For the same `(universe, as_of)`, both commands must consume the exact
same complete dataset.

Required relationships:

    funnel.snapshot_identity == shortlist.snapshot_identity
    funnel.dataset_identity == shortlist.dataset_identity
    shortlist_tickers == funnel_tickers

`snapshot_identity` proves the exact sealed evidence boundary.

`dataset_identity` retains its existing Diamond meaning: identity of the
resulting FundamentalRecord dataset.

A newer acquisition must never alter an older completed dataset.

Diamond remains the sole owner of ranking and ordering.

## Evidence

Task 7 demonstrated divergent runtime datasets.

Executive worktree:

    universe   1
    canonical  282
    market     51
    splits     267

Debt Zero worktree:

    universe   1
    canonical  504
    market     51
    splits     474

Executive Yahoo market cache contained:

    39 batches -> data_as_of=2026-09-22
    12 batches -> data_as_of=2026-09-24

Debt Zero retained all 51 Yahoo batches for 2026-09-22.

Verified Debt Zero replay:

    Top-5:
    MO
    UBER
    CRH
    BKNG
    RMD

    provider_requests = 0
    cache_hits = 1526
    cache_misses = 0

    legacy_dataset_identity =
    46677793154fc2a7888361aa613d9c61db124b5f5b1eb414a4b3ad471a05c2a2

The existing cache derives its physical path from request_identity.

For Yahoo, request_identity is the URL. data_as_of is validated only
after the cache object is loaded.

Therefore the same URL requested for a later date can replace the older
temporal snapshot.

This is a dataset-consistency defect, not merely a cache-hit defect.

## Architectural Decision

Introduce immutable, manifest-backed Diamond dataset snapshots.

Default shared runtime root:

    ~/.cache/qhapaq-finance/diamond

Optional override:

    QHAPAQ_CACHE_ROOT=/absolute/path

Git worktrees isolate source code.

They must not independently own authoritative runtime datasets.

## Dataset Layout

Conceptual layout:

    ~/.cache/qhapaq-finance/diamond/
    └── sp500/
        ├── 2026-09-22/
        │   ├── manifest.json
        │   ├── universe/
        │   ├── sec/
        │   ├── canonical/
        │   ├── market/
        │   └── splits/
        └── 2026-09-24/
            ├── manifest.json
            ├── universe/
            ├── sec/
            ├── canonical/
            ├── market/
            └── splits/

Different as_of dates never share mutable evidence objects.

## Snapshot Lifecycle

Snapshots have two states:

    BUILDING -> COMPLETE

BUILDING:

- may receive evidence;
- may be resumed;
- may be discarded;
- cannot be treated as reproducible input.

COMPLETE:

- owns a finalized manifest;
- owns deterministic dataset_identity;
- records actual evidence coverage;
- is immutable;
- supports offline replay;
- may be consumed by Funnel and Shortlist.

Normal acquisition must never modify COMPLETE.

## Manifest Contract

The manifest describes one exact evidence selection.

It must distinguish two concepts:

1. physical source inventory;
2. semantic evidence selected for the snapshot.

Raw file counts are not automatically issuer or security counts.

The verified Debt Zero migration source currently contains:

    universe cache objects     1
    SEC index objects          500
    SEC blob objects           500
    canonical cache objects    504
    market batch objects       51
    split cache objects        474
    universe securities        503

These inventory values are observations about the migration source.
They are not universal completeness constants.

In particular, `canonical cache objects = 504` does not imply 504
distinct universe securities.

Canonical request identity currently includes:

- issuer_id;
- as_of;
- history_years;
- evidence_revision_sha256;
- canonical schema version;
- canonicalizer version.

Therefore multiple physical canonical objects may legitimately exist
for one logical issuer across revisions or other identity dimensions.

Likewise, SEC evidence is physically represented by an index plus
content-addressed blobs. The migration source has 500 index objects and
500 blobs; the manifest must not infer semantic coverage merely from the
recursive file count.

Conceptual manifest:

    schema_version: diamond-dataset-v1
    universe: sp500
    as_of: 2026-09-22
    status: COMPLETE
    snapshot_identity: <sha256>

    coverage:
      universe_securities: <observed>
      selected_sec_issuers: <observed>
      selected_canonical_issuers: <observed>
      market_batches: <observed>
      selected_split_issuers: <observed>

    inventory:
      universe_cache_objects: <observed>
      sec_index_objects: <observed>
      sec_blob_objects: <observed>
      canonical_cache_objects: <observed>
      market_cache_objects: <observed>
      split_cache_objects: <observed>

    components:
      universe_identity: <sha256>
      sec_identity: <sha256>
      canonical_identity: <sha256>
      market_identity: <sha256>
      splits_identity: <sha256>

    legacy:
      diamond_dataset_identity: <optional existing identity>

Each semantic coverage value must be derived from evidence actually
selected by the snapshot resolver.

Each component identity must be deterministic over the exact selected
evidence references and their verified content identities.

Inventory counts are diagnostic metadata. They must not by themselves
determine snapshot completeness.

## Identity Model

The architecture has two distinct identities.

### snapshot_identity

`snapshot_identity` is new.

It identifies the exact sealed evidence boundary described by the
COMPLETE manifest.

It must deterministically include at minimum:

- snapshot schema version;
- universe;
- as_of;
- semantic coverage;
- exact selected evidence references;
- component content identities.

It must exclude:

- retrieval timestamps;
- elapsed time;
- machine paths;
- worktree paths.

Equivalent sealed evidence produces the same `snapshot_identity`.

Any change to selected evidence or its verified content changes
`snapshot_identity`.

### dataset_identity

`dataset_identity` already exists in Diamond and must retain its current
meaning.

It is calculated from the resulting FundamentalRecord collection.

This feature must not silently redefine that existing public contract.

The runtime therefore carries both identities:

    snapshot_identity = identity of exact input evidence
    dataset_identity  = identity of Diamond FundamentalRecord output

The distinction is intentional.

Two different snapshots may theoretically produce the same
`dataset_identity` if their evidence differences do not alter the
resulting FundamentalRecords.

Likewise, the same immutable snapshot processed by materially different
future transformation logic may produce a different `dataset_identity`.

Therefore `snapshot_identity` is the evidence reproducibility boundary,
while `dataset_identity` remains the Diamond output identity.

For one execution path, Executive Shortlist must transport both
identities from its Diamond Funnel result without recalculation.

## Temporal Evidence Identity

Evidence whose result depends on as_of must include temporal scope in
its physical identity.

Conceptually:

    provider + as_of + request_identity

Example:

    yahoo-finance
    |2026-09-22
    |https://query1.finance.yahoo.com/...

The equivalent 2026-09-24 request creates another immutable object.

It must never overwrite the 2026-09-22 evidence.

## Dataset Resolution

Funnel and Shortlist use the same selector:

    (universe, as_of, cache_root)

The selector resolves exactly one COMPLETE manifest.

Both commands must expose:

    snapshot_identity
    dataset_identity

For the same invocation and the same resolved Diamond run:

    funnel.snapshot_identity == shortlist.snapshot_identity
    funnel.dataset_identity == shortlist.dataset_identity
    shortlist_tickers == funnel_tickers

Shortlist must transport these identities from Diamond.

It must not independently rebuild, reinterpret or hash snapshot
evidence.

Across arbitrary source-code revisions, only `snapshot_identity` is
required to remain stable for the same sealed snapshot.

Cross-worktree equality of `dataset_identity` and Top-N is an acceptance
requirement only when the compared executions use compatible Diamond
transformation/scoring code.

## Offline Replay

Add explicit cache-only execution.

Conceptual CLI:

    qhapaq funnel \
      --universe sp500 \
      --depth 5 \
      --as-of 2026-09-22 \
      --offline

    qhapaq shortlist \
      --universe sp500 \
      --depth 5 \
      --as-of 2026-09-22 \
      --offline

Offline mode:

- makes zero network calls;
- never mutates COMPLETE snapshots;
- never silently acquires missing data;
- fails immediately when required evidence is missing.

Representative failure:

    DATASET_INCOMPLETE:
    provider=yahoo-finance
    as_of=2026-09-22
    request=<identity>

## CLI Alignment

qhapaq shortlist must accept explicit --as-of.

Funnel and Shortlist must share:

- universe;
- as_of;
- cache root;
- offline policy.

date.today() may remain a convenience default for current interactive
analysis.

Historical replay and acceptance must pin an explicit date.

## Acquisition Contract

Building a snapshot:

1. resolve (universe, as_of);
2. create or resume BUILDING;
3. acquire universe evidence;
4. acquire SEC evidence;
5. build canonical evidence;
6. acquire market evidence;
7. acquire split evidence;
8. validate evidence;
9. calculate actual coverage;
10. calculate component identities;
11. calculate dataset identity;
12. atomically finalize manifest;
13. transition to COMPLETE.

Failure before finalization must never expose COMPLETE.

## Fail-Closed Semantics

Distinguish:

1. legitimate unavailable financial evidence inside COMPLETE;
2. missing acquisition required for dataset completion.

The first may remain null under existing financial semantics.

The second produces:

    DATASET_INCOMPLETE

No values are fabricated.

Offline mode never silently falls back to network.

## Migration

Use the verified Debt Zero 2026-09-22 evidence as the first migration
source.

Observed physical source inventory:

    universe cache objects     1
    SEC index objects          500
    SEC blob objects           500
    canonical cache objects    504
    market batch objects       51
    split cache objects        474

Observed universe cardinality:

    universe securities        503

These numbers describe the legacy source inventory.

They are not hard-coded requirements for future snapshots and must not
be interpreted as one-object-per-security guarantees.

Migration procedure:

    copy selected evidence
    -> verify source checksums
    -> resolve semantic evidence set
    -> calculate component identities
    -> calculate snapshot_identity
    -> offline replay
    -> provider_requests == 0
    -> cache_misses == 0
    -> verify Diamond dataset_identity
    -> verify Top-5
    -> atomically seal COMPLETE

Migration must not:

- move source evidence;
- mutate Debt Zero;
- use the mixed Executive cache as authoritative source;
- fabricate evidence;
- delete legacy caches;
- infer semantic coverage from raw file counts.

Acceptance target for the existing Diamond output remains:

    Top-5:
    MO
    UBER
    CRH
    BKNG
    RMD

    provider_requests = 0
    cache_hits = 1526
    cache_misses = 0

The known legacy Diamond output identity is:

    46677793154fc2a7888361aa613d9c61db124b5f5b1eb414a4b3ad471a05c2a2

Migration introduces a new `snapshot_identity`.

The manifest may record the known legacy `dataset_identity` for audit,
but the two identities must never be treated as interchangeable.

## Compatibility

Do not modify:

- Diamond scoring;
- archetypes;
- research priority;
- ranking order;
- SEC accounting semantics;
- financial promotion;
- Goal Seek;
- Executive synthesis.

This feature changes evidence lifecycle and reproducibility only.

## Required Invariants

1. COMPLETE snapshots are immutable.
2. Different as_of dates cannot overwrite one another.
3. Worktrees do not independently own authoritative datasets.
4. Physical inventory and semantic coverage are distinct.
5. Manifest coverage describes evidence actually selected.
6. snapshot_identity covers exact selected input evidence.
7. Existing dataset_identity semantics remain unchanged.
8. Funnel and Shortlist resolve the same COMPLETE manifest.
9. Shortlist transports snapshot_identity without recalculation.
10. Shortlist transports dataset_identity without recalculation.
11. Shortlist preserves Diamond Top-N exactly.
12. Offline replay makes zero network requests.
13. Missing required evidence fails explicitly.
14. BUILDING cannot masquerade as COMPLETE.
15. Failed acquisition cannot corrupt COMPLETE.
16. New acquisition cannot alter historical snapshot_identity.
17. Migration cannot mutate its source.
18. Legitimate null financial evidence remains null-aware.
19. Raw cache-file counts cannot define completeness by themselves.
20. Same sealed evidence means same snapshot_identity independent of
    worktree path.

## Required Tests

### Temporal coexistence

Prove:

    store(URL, 2026-09-22)
    store(URL, 2026-09-24)

    load(URL, 2026-09-22) -> snapshot 22
    load(URL, 2026-09-24) -> snapshot 24

Both temporal objects coexist.

### Physical inventory versus semantic coverage

Construct evidence where multiple physical canonical objects correspond
to one logical issuer.

Prove that:

- physical object count records inventory;
- semantic issuer count records selected coverage;
- completeness does not assume one file per security.

### Historical preservation

1. seal 2026-09-22;
2. record snapshot_identity;
3. record dataset_identity;
4. build and seal 2026-09-24;
5. replay 2026-09-22;
6. prove snapshot_identity unchanged;
7. with compatible Diamond code, prove dataset_identity unchanged;
8. prove Diamond output unchanged.

### Manifest lifecycle

Prove:

- BUILDING cannot replay;
- incomplete acquisition cannot become COMPLETE;
- COMPLETE manifest is deterministic;
- mutation of COMPLETE is rejected;
- interrupted finalization cannot expose COMPLETE.

### Offline behavior

Prove:

- zero network calls on complete replay;
- missing evidence fails immediately;
- missing evidence does not invoke network;
- COMPLETE replay cannot write.

### Identity separation

Prove independently that:

- changing selected evidence changes snapshot_identity;
- worktree path does not change snapshot_identity;
- dataset_identity continues to use the existing FundamentalRecord
  identity algorithm;
- Shortlist does not calculate either identity itself.

### Cross-command acceptance

For one real COMPLETE snapshot:

    funnel.snapshot_identity == shortlist.snapshot_identity
    funnel.dataset_identity == shortlist.dataset_identity
    funnel_tickers == shortlist_tickers
    provider_requests == 0
    cache_misses == 0

### Cross-worktree acceptance

Two compatible code worktrees reading the same shared snapshot must
resolve:

    same manifest
    same snapshot_identity

When their Diamond transformation/scoring revision is equivalent, they
must additionally produce:

    same dataset_identity
    same Diamond Top-N

## Rollout

Phase 1:

- explicit snapshot_identity contract;
- preserve existing dataset_identity contract;
- temporal immutable identities;
- shared configurable runtime root;
- snapshot and manifest contracts.

Phase 2:

- BUILDING/COMPLETE lifecycle;
- atomic finalization;
- shared dataset resolver;
- offline enforcement.

Phase 3:

- align Funnel and Shortlist CLI;
- Shortlist --as-of;
- shared cache-root behavior.

Phase 4:

- migrate verified Debt Zero 2026-09-22;
- seal first COMPLETE snapshot;
- historical replay acceptance.

Phase 5:

- resume Executive Shortlist Task 7;
- execute Task 8 integration readiness.

## Non-Goals

Do not:

- redesign Diamond;
- alter scoring;
- alter canonical accounting;
- add providers;
- infer missing financial values;
- merge unrelated worktrees;
- delete legacy caches automatically;
- label incomplete datasets as complete.

## Final Decision

The reproducible input boundary becomes an immutable,
manifest-backed dataset snapshot.

A mutable cache directory is not sufficient to define a dataset.
