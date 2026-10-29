# H2 — Reconciliation and reuse

Review date: 2026-10-29 (America/Lima)

Status: **GREEN IN THE WORKTREE; ALL EXTERNAL PROJECTS REMAIN CANDIDATES NOT ADOPTED**.

This record consolidates the implemented H2 CandidateSet v1 boundary and evaluates
external GitHub findings without adopting dependencies or changing financial behavior,
ranking, valuation or canonical data. A later explicit user amendment authorized one
urgent inherited full-suite reliability correction; it is isolated and documented below.

## Canonical H2 record

The documents have separate responsibilities:

1. [`2026-10-28-candidate-set-v1-design.md`](../superpowers/specs/2026-10-28-candidate-set-v1-design.md)
   is authoritative for H2 intent, contracts, invariants and non-goals.
2. [`2026-10-28-candidate-set-v1.md`](../superpowers/plans/2026-10-28-candidate-set-v1.md)
   is authoritative for deliverables and verification gates.
3. This document is the post-implementation reconciliation, external-candidate
   backlog and closure-evidence record. It cannot redefine the design or plan.
4. [`2026-09-24-diamond-immutable-dataset-snapshots-design.md`](../superpowers/specs/2026-09-24-diamond-immutable-dataset-snapshots-design.md)
   remains a proposed downstream snapshot architecture. CandidateSet deliberately
   references a snapshot; it does not implement snapshot storage or sealing.

## Recovered repository state

- The repository entry worktree is on `feat/cold-ticker-sec-acquisition` at
  `2840a21a743f5645850d22d7cd18110a590244d7` and contains extensive pre-existing
  tracked and untracked user work. It was inspected but not modified by H2
  reconciliation.
- H2 is isolated in `.worktrees/h2-candidate-set-v1`, branch
  `feat/h2-candidate-set-v1`, at
  `afa8257fcdb6fd80c5a78752b8da90b2cb771b8b` (`feat: add CandidateSet v1 contract`).
  Its pre-reconciliation worktree was clean and the H2 commit is one commit ahead
  of its H1 parent `63d53d5e478562a3e5c1fd162d85d40a183cdfaf`.
- No remote branch contains the H2 commit in the inspected repository state. No
  commit, push, merge, backfill or acquisition was performed by this reconciliation.

## H2 scope, deliverables and closure criteria

H2 creates only the typed boundary that converts the authoritative ordered Diamond
`FunnelRun` into an exact, identity-bound `CandidateSet`. Diamond remains the sole
ranking authority. H2 does not calculate financial metrics, acquire evidence, persist
snapshots, change valuation, or modify Diamond output contracts.

Delivered by `afa8257`:

- `src/qhapaq_finance/candidate_set.py`;
- FAST contract tests in `tests/test_candidate_set.py`;
- frozen local integration coverage in `tests/test_candidate_set_integration.py`;
- the canonical design and implementation plan listed above.

Closure requires observable evidence that:

- exact `SecurityRef`, Diamond rank and selection order are preserved without
  re-ranking or ticker fallback;
- dataset, universe and cutoff mismatches, duplicate identities, unrankable results
  and over-selection fail closed;
- the versioned canonical `candidate_set_id` is deterministic and sensitive to
  selection and snapshot identity;
- an `INCOMPLETE` snapshot remains inspectable but cannot claim production
  reproducibility;
- existing Diamond dataset identity and public serialization remain compatible;
- focused tests, relevant integration/regression tests, Ruff, mypy and the feasible
  full repository gate pass; and
- beyond H2 reconciliation documentation, the final diff contains only the explicitly
  authorized full-suite reliability correction and its regression test.

## External candidate reconciliation

License conclusions below describe the inspected upstream version on the review date;
they are not a substitute for rechecking the exact version and transitive dependencies
before a future adoption. Provider data terms remain separate from source-code licenses.

| Project | Existing Qhapaq capability and duplication | Architecture and license | Benefit versus integration cost | Classification |
| --- | --- | --- | --- | --- |
| **EdgarTools** (high priority) | Qhapaq already owns SEC HTTP through `SecClient`, immutable staging, manifest-backed corpus export, accession-aware filing discovery, filing-native XBRL extraction and canonical promotion. Replacing that path would be substantial duplication. | Compatible only behind acquisition/extraction boundaries and never as an alternate valuation path. Upstream is MIT. | Broad form/XBRL support could provide an independent parser oracle and expose gaps. Direct runtime adoption would require mapping every output to Qhapaq identities, raw-byte hashes, cutoff rules and fail-closed states, while preventing a second SEC HTTP/cache owner. | **ADOPT LATER**, only as an optional offline validation adapter over Qhapaq-frozen filings after golden parity and provenance tests. Not a replacement for `SecClient`, manifests or canonical promotion. |
| **DuckDB** (high priority) | Qhapaq has immutable SEC artifacts, deterministic identities and a proposed BUILDING/COMPLETE snapshot contract, but no general append-only historical query store or restatement index. Duplication is partial. | It may serve as a disposable derived query/index layer; immutable files and manifests must remain authoritative. Upstream is MIT. | Strong benefit for historical queries, snapshot inspection and restatement analysis. Cost is material: temporal schema, migrations, concurrency, manifest binding, deterministic export and proof that database state cannot silently redefine a sealed snapshot. | **ADOPT LATER**, after the downstream snapshot contract seals a real `COMPLETE` snapshot. Start read-only and rebuildable from verified manifests; never make the database the sole evidence authority. |
| **Hypothesis** (high priority) | Qhapaq already has deterministic examples for cutoff, identity, ranking and replay invariants, but no property-based generation. Functional duplication is low. | Development/test boundary only; no production behavior. Upstream code is MPL-2.0, compatible as an external test dependency while retaining its license. | High value for monotone-knowledge, no-future-leak, serialization round-trip and identity-sensitivity properties. Cost is modest but includes deterministic profiles, bounded runtime and reproducible failing examples. | **ADOPT LATER** as a dev-only dependency in a separately approved test increment after H2; begin with pure temporal and identity properties. |
| **Pandera** (medium priority) | Qhapaq already validates domain contracts with frozen dataclasses, Pydantic and explicit fail-closed constructors. It does not have a uniform schema gate for every pandas bulk boundary. | A dataframe-boundary validator can compose with, but must not replace, domain models. Upstream is MIT. | It could make bulk financial table schemas more explicit. The cost is a second validation vocabulary, coercion/null-semantics risk, extra dependency surface and possible duplication of existing Pydantic checks. | **INVESTIGATE**. First inventory dataframe ingress/egress and prove a concrete validation gap that existing typed contracts cannot cover cleanly. |
| **Polars** (conditional) | Diamond percentiles already use NumPy plus small explicit Python samples and have pinned tie, winsorization, null and peer-scope semantics. No current evidence establishes this path as a bottleneck. | A migration would cross a numerical contract boundary and require exact parity. Upstream is MIT. | Potential throughput benefit only at materially larger universes. Current cost is high relative to evidence: new dependency plus regression risk in quantiles, ties, ordering, NaN handling and dtypes. | **DISCARD** for the current backlog. Reconsider only after a reproducible benchmark identifies the percentile path as the bottleneck and a golden parity suite proves identical outputs. |
| **AsOf** (research) | Qhapaq already preserves accession/filed/cutoff context, immutable corpus artifacts and fail-closed historical selection. It does not yet expose an append-only bitemporal fact store, restatement ledger or dedicated point-in-time reader. | Useful as a reference for separating acquisition/storage from consumers through a `PointInTimeReader`-style protocol. The inspected project is MIT and currently requires Python 3.12, while Qhapaq supports Python 3.10+. | Its two-time-axis and consumer-boundary patterns directly illuminate the downstream snapshot problem. Importing it would duplicate SEC normalization, valuation and storage and would narrow runtime compatibility. | **INVESTIGATE** as architecture only. Extract design lessons into a future approved snapshot proposal; do not depend on or copy its implementation. |
| **FinanceToolkit** (research) | Qhapaq already implements financial primitives, ratios, capital cost, reverse DCF, sensitivity and valuation contracts with Qhapaq-specific evidence semantics. Production adoption would be highly duplicative. | At most an isolated comparison oracle over already-normalized frozen inputs. Upstream is MIT. | Useful for detecting formula disagreements and documenting methodology choices. Cost is reconciliation of signs, periods, units, provider assumptions and floating-point/dataframe behavior; its acquisition path would weaken Qhapaq provenance if used directly. | **INVESTIGATE** only for offline contrast tests. Never source canonical evidence or replace Qhapaq valuation/ranking logic. |
| **OpenBB** (research) | Qhapaq already has provider protocols, a dedicated SEC client, typed provider outputs and acquisition/analysis separation. A framework adoption would duplicate orchestration and connector boundaries. | The V5 extension/provider architecture is relevant; V5 is Apache-2.0, while V4 artifacts remain AGPL-3.0-only. Any review must pin the major version and inspect each provider's data terms. | Useful reference for modular provider discovery and transform/extract/transform boundaries. Runtime adoption has very high dependency, configuration and compatibility cost and does not by itself preserve Qhapaq cutoff or manifest semantics. | **INVESTIGATE** architectural patterns only. Do not adopt the runtime or connectors in H2. |

Every row above remains a **CANDIDATE NOT ADOPTED**. `ADOPT LATER` is a backlog
classification, not approval to install, import, vendor or copy code.

## Reuse guardrails for any later increment

1. Immutable source bytes and verifiable manifests remain the evidence authority.
2. SEC CIK, accession, exact document, filing/acceptance time, retrieval event and
   cutoff admissibility remain explicit and cannot be collapsed into ticker/date.
3. Point-in-time reads fail closed; a derived database or cache is rebuildable and
   cannot silently mutate historical evidence.
4. Acquisition, financial analysis and valuation remain separate. External parsers or
   connectors cannot promote facts, approve semantics or calculate production rankings.
5. Public contracts and byte-stable identities require golden parity before and after
   any adapter.
6. A future adoption requires its own approved design, exact version/license review,
   dependency justification, negative tests and rollback path.

## Urgent full-suite reliability correction

During closure verification, the complete suite reproducibly stopped after the first
51 tests in the restricted sandbox. The next test used `asyncio.to_thread()` with a
delayed worker. Root-cause probes showed that an immediate cross-thread callback could
win a race, while a delayed `loop.call_soon_threadsafe()` never woke the loop; the
underlying worker-thread socket send failed with `PermissionError: [Errno 1] Operation
not permitted`. The same test passed outside that sandbox, proving an environment/code
interaction rather than a financial assertion failure.

The user then explicitly expanded scope to correct this class of problem urgently.
`DeepAnalysisOrchestrator` now owns a two-worker `ThreadPoolExecutor`, submits the same
synchronous analyzer work there, and cooperatively awaits each `Future` from the event
loop without depending on cross-thread socket wakeups. Existing behavior remains pinned:
maximum concurrency two, work off the event-loop thread, exact input order, fail-closed
domain errors and propagation of unexpected errors. The active polling interval is one
millisecond and is bounded to at most two in-flight analyses. Cancellation and unexpected
sibling failures cancel and settle the asyncio tasks without synchronously waiting for an
already-running worker thread, so unrelated event-loop work remains responsive.

The regression was observed RED when the event loop's `run_in_executor` boundary was
forbidden, then GREEN after the worker lifecycle change. A separate mixed slow/error test
was RED when executor teardown waited for the slow worker; cancellation coverage was also
run RED against that blocking teardown. Both are GREEN with non-blocking, cancel-aware
cleanup. This correction adds no package, provider, acquisition path, financial rule or
public data contract.

## Differences and remaining conditions

- CandidateSet v1 is implemented, but it intentionally does not create or seal a
  production snapshot. No inspected repository artifact proves a real
  `SnapshotStatus.COMPLETE` input; production reproducibility therefore remains gated.
  This belongs to the downstream snapshot milestone and is not a reason to expand H2.
- The implementation-plan checkboxes remained unchecked after the H2 commit. The plan
  now states that those boxes are the preserved original plan rather than a live ledger;
  commit identity, current tests and this record are the execution evidence.
- H2 exists only on its local feature branch in the inspected refs. Integration or
  publication is a later explicit Git action and is not authorized by this task.
- A real `COMPLETE` Diamond snapshot and branch integration remain subsequent explicit
  actions; neither is a CandidateSet v1 closure requirement.

## Verification evidence

All checks used the existing locked environment with `uv run --no-sync`; none performed
network access, data acquisition or backfill.

- Preflight: H2 branch/HEAD matched `feat/h2-candidate-set-v1` at `afa8257`; the H2
  worktree was clean before reconciliation. `git show --check afa8257` passed.
- Regression RED: `test_orchestrator_does_not_depend_on_event_loop_cross_thread_wakeup`
  failed because production called the forbidden event-loop executor boundary.
- Original symptom GREEN: the formerly hanging ordered-concurrency test completed in the
  restricted sandbox after the correction.
- Deep-analysis regression: `tests/executive/test_deep_analysis.py` — 28/28 passed.
- H2 plus relevant Diamond/deep-analysis selection — 60/60 passed.
- Full restricted-sandbox suite — 1046/1046 passed in 28.52 seconds; this is stronger
  evidence than the earlier outside-sandbox full run, which also reached 100%.
- `ruff check .` — `All checks passed!`.
- `ruff format --check .` — 252 files already formatted.
- `mypy src` — success on 104 source files.
- `uv lock --check` — resolved the existing 90-package lock with no changes.
- `git diff --check` passed, and final status/full-diff review found only the three H2
  reconciliation documents plus the explicitly authorized orchestrator correction and
  its regression tests.
- Independent review identified blocking executor shutdown during cancellation/error as
  an important issue. The issue was reproduced RED, corrected, and covered by the two
  additional GREEN regressions above.
- The repository entry worktree's tracked-diff fingerprint remained
  `cafcbd39d97accd8fdbc91170ca7a6e6f1cc1592ce031d1f7383f387632917b0`; no root-worktree
  file was written by this work.

## Primary upstream references

- EdgarTools repository and MIT license declaration:
  <https://github.com/dgunning/edgartools>
- DuckDB repository/architecture and MIT license:
  <https://github.com/duckdb/duckdb>
- Hypothesis repository and MPL-2.0 license:
  <https://github.com/HypothesisWorks/hypothesis> and
  <https://github.com/HypothesisWorks/hypothesis/blob/master/LICENSE.txt>
- Pandera documentation/repository and MIT license:
  <https://pandera.readthedocs.io/en/stable/> and
  <https://github.com/unionai-oss/pandera>
- Polars repository and MIT license:
  <https://github.com/pola-rs/polars>
- AsOf point-in-time architecture and MIT license:
  <https://github.com/RaghhavMalani/AsOf>
- FinanceToolkit repository and MIT license:
  <https://github.com/JerBouma/FinanceToolkit>
- OpenBB V5 architecture and license history:
  <https://docs.openbb.co/odp/python/concepts/architecture>,
  <https://docs.openbb.co/odp/python/extensions/providers> and
  <https://docs.openbb.co/odp/python/faqs/license>
