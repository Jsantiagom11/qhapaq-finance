# Diamond Opportunities v0.1 Design

Status: Approved for autonomous execution by the task dated 2026-10-29.

## Intent

Turn the closed CandidateSet v1 boundary into the smallest usable research-routing
experience over real Diamond data. A user must be able to replay one historical S&P 500
cutoff offline, see the exact Diamond Top N, understand the financial factors and
limitations behind each candidate, and inspect one candidate without treating the result
as an investment recommendation.

## Product outcome

The primary command is:

```text
qhapaq opportunities \
  --as-of 2026-09-22 \
  --cache-root <verified-debt-zero-cache> \
  --output <artifact-directory> \
  --top 10
```

On its first run it consumes an exact historical cache with network access disabled,
seals the evidence files actually read into an immutable local snapshot, replays that
snapshot, builds a `CandidateSet`, and writes deterministic JSON and Markdown reports.
Later runs verify and replay the sealed snapshot without reading the migration source.

The focused inspection command is:

```text
qhapaq opportunity TICKER --report <artifact-directory>/opportunities.json
```

It renders the same stored facts, derived metrics, inferences, assumptions, missing
evidence and next research questions for one selected or blocked company.

## Constraints

- The cutoff is required and immutable; the command has no implicit current-date mode.
- The workflow is offline-only. Any missing cache object fails explicitly and never
  falls back to a provider request.
- Diamond remains the only ranking authority. CandidateSet copies its exact order.
- No scoring weight, percentile, archetype, valuation or Qhapaq One behavior changes.
- Nulls remain null; no observation is inferred, forward-filled or converted to zero.
- The source cache is read-only and is never mutated by sealing or replay.
- A snapshot becomes `COMPLETE` only after every selected file is copied and hash
  verified, Diamond reports zero requests/misses, and a replay reproduces the dataset
  identity and Top N. The manifest is finalized last.
- The report distinguishes verified structured observations, derived metrics,
  deterministic research inferences, model assumptions and insufficient evidence.
- SEC Company Facts is described honestly as structured screening evidence. The report
  does not claim filing-native certification when the canonical observation lacks an
  exact per-metric filing locator.
- The result is research routing, not BUY/HOLD/SELL, fair value or a price target.

## Existing components reused

- `SecFirstProvider`, Diamond provider caches and canonical issuer snapshots.
- `run_funnel()` and the existing scoring/archetype implementation unchanged.
- `DiamondResult` metrics, percentiles, coverage and diagnostics.
- CandidateSet v1 for exact identity-bound Top-N selection.
- Existing canonical JSON and checksum helpers.

## Architecture

```text
legacy verified cache (read-only)
        |
        v
strict offline provider + selected-file audit
        |
        v
Diamond full-universe evaluation
        |
        v
copy selected evidence -> hash -> staged snapshot
        |
        v
strict offline replay from staged snapshot
        |
        v
verify identity/order -> COMPLETE manifest (last)
        |
        +--> exact CandidateSet Top N
        +--> exclusion summary
        +--> evidence-aware opportunity report
```

`DiamondCache` records successful read paths without changing cache semantics.
`SecEvidenceStore` gains an explicit offline mode: an exact-cutoff manifest may be used
despite operational TTL, while a miss or cutoff mismatch fails instead of revalidating.
The offline provider factory passes `None` clients so a network request is impossible.

The staged inventory contains schema/canonicalizer versions, universe, cutoff, semantic
coverage, dataset identity, exact selected relative paths, byte sizes and SHA-256 values.
Its identity excludes machine and worktree paths. Snapshot storage is a copied, read-only
tree rather than a reference to the mutable migration source. The public manifest does
not exist until a strict offline replay has reproduced the source identity and order;
that final atomic write is the only transition to `COMPLETE`.

The report retains the source `FundamentalRecord` values used by Diamond. Factor
explanations are deterministic projections of the winning archetype, category scores and
feature percentiles; they do not create causal claims. Evidence records expose period,
unit, provider and source identity. Issuer-level SEC provenance exposes CIK, evidence
revision, raw payload checksum, latest in-scope accession and filing date, with an
explicit warning that these issuer-level fields are not exact per-metric locators.

## Approaches considered

1. **Sealed historical report — selected.** Reuses the verified 2026-09-22 Debt Zero
   evidence, adds the missing offline and custody boundary, and delivers value without
   touching Qhapaq One or acquiring current data.
2. **Integrate directly into the uncommitted Diamond Board/Qhapaq One worktrees.** This
   could produce a richer UI, but would mix unrelated dirty user work, duplicate pending
   temporal work and make the first delivery much harder to verify independently.
3. **Implement the complete shared multi-date snapshot platform first.** Architecturally
   desirable, but materially larger than the minimum vertical slice. v0.1 implements the
   sealing/replay subset required by one real historical cutoff and keeps its manifest
   compatible with later migration.

## Report contract

The deterministic JSON report contains:

- universe, cutoff, snapshot and dataset identities;
- universe/canonical/rankable/excluded/selected counts;
- non-exclusive exclusion reasons and representative blocked companies;
- CandidateSet identity and exact ordered securities;
- for each selected candidate: identity, period, scores, metrics, determinant factors,
  diagnostics, evidence lines, SEC provenance, limitations and next research questions;
- epistemic sections named `verified_facts`, `derived_metrics`, `inferences`,
  `assumptions` and `insufficient_data`;
- a prominent non-recommendation statement.

Markdown is a human-readable projection of the same object. Focused inspection reads the
JSON artifact and performs no acquisition or recalculation.

## Failure semantics

- `OFFLINE_CACHE_MISS`: an exact evidence object is unavailable.
- `SNAPSHOT_INCOMPLETE`: sealing did not reach all required conditions.
- `SNAPSHOT_TAMPERED`: a copied file or manifest hash fails verification.
- `SNAPSHOT_CONTEXT_MISMATCH`: universe/cutoff/dataset differs.
- `INSUFFICIENT_RANKABLE_CANDIDATES`: fewer than requested are returned without filling.
- Existing Diamond/provider errors remain fail-closed and retain their meaning.

## Acceptance

1. The primary command completes against the protected 2026-09-22 Debt Zero cache with
   zero provider requests and zero cache misses.
2. The replayed dataset identity and Top N are identical across two runs.
3. CandidateSet is built only from the verified `COMPLETE` manifest and preserves exact
   Diamond identity/order.
4. The report shows real companies, universe/exclusion counts, decisive metrics,
   provenance, missing evidence and limitations.
5. `qhapaq opportunity TICKER` gives a comprehensible research view for at least one
   selected company and does not issue an investment recommendation.
6. Altering one snapshot byte makes verification fail before ranking/reporting.
7. Focused, integration, regression, Ruff, mypy and full repository gates pass.
8. Two generated JSON/Markdown artifacts from the same snapshot are byte-identical.
9. No external dependency, push, merge, canonical-data edit or root-worktree change is
   introduced.

## Explicit limits

This is a historical 2026-09-22 research snapshot, not a claim about opportunities on
2026-10-29. Company Facts provenance is sufficient for structured discovery but does not
meet the draft filing-native integrity specification's per-value round-trip standard.
Current/live analysis and full multi-date snapshot acquisition remain subsequent work.
