# Diamond Immutable Dataset Snapshots v0.5

Status: Proposed architecture for review.

## Objective

Make Diamond Funnel and Executive Shortlist reproducible across dates,
Git worktrees and offline replay.

For the same `(universe, as_of)`, both commands must consume the exact
same complete dataset.

Required invariants:

    funnel.dataset_identity == shortlist.dataset_identity
    shortlist_tickers == funnel_tickers

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

Conceptual manifest:

    {
      "schema_version": "diamond-dataset-v1",
      "universe": "sp500",
      "as_of": "2026-09-22",
      "status": "COMPLETE",
      "dataset_identity": "<sha256>",
      "coverage": {
        "universe_count": 503,
        "canonical_records": 503,
        "market_batches": 51,
        "split_records": 474
      },
      "components": {
        "universe_identity": "<sha256>",
        "sec_identity": "<sha256>",
        "canonical_identity": "<sha256>",
        "market_identity": "<sha256>",
        "splits_identity": "<sha256>"
      }
    }

Coverage values are observations, not hard-coded universal constants.

## Dataset Identity

dataset_identity represents the complete logical dataset.

It includes at minimum:

- schema version;
- universe;
- as_of;
- component identities;
- actual coverage.

It must exclude:

- retrieval timestamps;
- elapsed time;
- machine paths;
- worktree paths.

Equivalent evidence produces the same identity.

Different evidence produces a different identity.

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

Both commands expose the same manifest dataset_identity.

No command may independently reconstruct another logical dataset for
the same selector.

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

Use the verified Debt Zero 2026-09-22 dataset as the first migration
source.

Migration:

    copy
    -> verify checksums
    -> offline replay
    -> provider_requests == 0
    -> cache_misses == 0
    -> verify Top-5
    -> calculate manifest
    -> seal COMPLETE

Migration must not:

- move source evidence;
- mutate Debt Zero;
- use the mixed Executive cache as authoritative source;
- fabricate evidence;
- delete legacy caches.

Acceptance target:

    Top-5:
    MO
    UBER
    CRH
    BKNG
    RMD

    provider_requests = 0
    cache_hits = 1526
    cache_misses = 0

If snapshot-v1 generates a new identity, preserve an auditable mapping:

    legacy_dataset_identity -> snapshot_v1_dataset_identity

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
4. Manifest coverage records actual evidence.
5. Dataset identity covers required components.
6. Funnel and Shortlist resolve the same manifest.
7. Both expose the same dataset identity.
8. Shortlist preserves Diamond Top-N.
9. Offline replay makes zero network requests.
10. Missing required evidence fails explicitly.
11. BUILDING cannot masquerade as COMPLETE.
12. Failed acquisition cannot corrupt COMPLETE.
13. New acquisition cannot alter historical identity.
14. Migration cannot mutate its source.
15. Legitimate null financial evidence remains null-aware.

## Required Tests

### Temporal coexistence

Prove:

    store(URL, 2026-09-22)
    store(URL, 2026-09-24)

    load(URL, 2026-09-22) -> snapshot 22
    load(URL, 2026-09-24) -> snapshot 24

Both physical objects coexist.

### Historical preservation

1. seal 2026-09-22;
2. record identity;
3. build and seal 2026-09-24;
4. replay 2026-09-22;
5. prove identity unchanged;
6. prove Diamond output unchanged.

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
- cache miss fails immediately;
- cache miss does not invoke network;
- COMPLETE replay cannot write.

### Cross-command acceptance

Prove:

    funnel_tickers == shortlist_tickers
    funnel.dataset_identity == shortlist.dataset_identity
    provider_requests == 0
    cache_misses == 0

### Cross-worktree acceptance

Different source worktrees reading the same shared snapshot resolve:

    same manifest
    same dataset_identity
    same Diamond Top-N

## Rollout

Phase 1:

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
