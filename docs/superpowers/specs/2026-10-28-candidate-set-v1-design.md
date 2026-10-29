# CandidateSet v1 Design

## Intent

Create the smallest typed boundary that turns an already ranked Diamond `FunnelRun`
into an exact, identity-bound set of companies that later research stages may consume.
Diamond remains the only ranking authority; CandidateSet copies identity and order and
does not calculate or retain financial metrics.

## Goals

- Bind the selection to one Diamond dataset identity, snapshot reference, universe and
  analysis cutoff.
- Preserve each selected company's exact `SecurityRef`, original one-based Diamond rank
  and deterministic one-based selection order.
- Make the Top-N policy explicit and make the resulting set content-addressable.
- Reject context, identity and rankability inconsistencies rather than guessing.
- Distinguish a valid local selection from a production-reproducible selection: only a
  `COMPLETE` snapshot may cross the production reproducibility gate.

## Non-goals and anti-goals

- No ranking, scoring, financial calculation, acquisition, persistence or serialization
  engine.
- No ResearchDossier, UI, Executive or valuation changes.
- No changes to Diamond result ordering, public JSON/CSV, dataset identity v2 or caches.
- No ticker fallback when the exact provider-neutral `SecurityRef` is absent or
  inconsistent.
- No claim that an existing cache or fixture is a complete production snapshot.

## Selected approach

Add a standalone `qhapaq_finance.candidate_set` boundary. It consumes the existing
`FunnelRun` and uses the sequence as authoritative. `DiamondSnapshotRef` is intentionally
small so Unidad 3 can supply a real snapshot implementation without CandidateSet owning
storage. `SnapshotStatus.INCOMPLETE` keeps draft/local selections representable while
`require_production_reproducible()` fails closed.

The v1 policy is deliberately only `DiamondTopNPolicy(limit)`. The builder takes the
first `limit` results without sorting, filtering or filling gaps. If any selected result
is unrankable or lacks an exact identity, the entire selection fails.

## Alternatives considered

1. **Standalone boundary — selected.** Keeps ranking inside Diamond and keeps later
   research contracts independent from Executive presentation and analysis.
2. **Embed CandidateSet in Diamond.** Fewer modules, but makes the discovery engine own a
   downstream research-selection lifecycle and encourages future scoring/selection
   coupling.
3. **Adapt Executive Shortlist.** Reuses an existing container, but it is ticker-facing,
   already couples selection to deep analysis, expectations and presentation, and is not
   the minimal dossier input contract.

## Contract

`DiamondSnapshotRef(snapshot_id, dataset_identity, universe_id, cutoff, status)` binds
the selection context. `snapshot_id` is an opaque non-empty reference in v1; Unidad 3
owns its production content-addressing and artifact verification. `dataset_identity`
must be the lowercase SHA-256 emitted by Diamond dataset v2.

`Candidate(security, diamond_rank, selection_order)` carries no financial values.
`CandidateSet(snapshot, policy, candidates, candidate_set_id)` exposes dataset,
universe and cutoff through the snapshot and computes `candidate_set_id` as SHA-256 over
canonical JSON containing:

- CandidateSet schema/canonicalizer versions;
- the complete snapshot reference and status;
- the explicit Top-N policy;
- each exact `SecurityRef`, Diamond rank and selection order.

`build_candidate_set()` rejects:

- snapshot dataset, universe or cutoff mismatches;
- selected results whose `data_as_of` differs from the cutoff;
- absent or ticker-inconsistent `source_security`;
- duplicate exact securities or conflicting reuse of one security id;
- unrankable selected results;
- a limit beyond the supplied authoritative Diamond result sequence.

Multiple securities may share a ticker when their exact `SecurityRef` values differ.
This preserves ambiguity instead of silently collapsing it to a ticker.

## Reproducibility gate

A CandidateSet may be built against an `INCOMPLETE` snapshot so local evidence remains
inspectable. Such a set has `production_reproducible == False` and
`require_production_reproducible()` raises `SNAPSHOT_NOT_COMPLETE`. Tests may use sealed
synthetic references; they do not promote any current Diamond cache.

## Compatibility and verification

The implementation imports but does not modify Diamond contracts. CandidateSet uses the
existing canonical JSON primitive under its own versioned payload. Existing Diamond v2
golden identities and public serialization must remain byte-compatible. Unit tests are
pure/in-memory and FAST; one INTEGRATION test composes the frozen local Diamond fixture
with an explicitly `INCOMPLETE` snapshot reference.
