# Product-alignment documentation evidence — 2026-09-02

## Objective and baseline

- Objective: align repository documentation with the evidence-first company research and portfolio
  decision direction without changing implementation.
- Repository root: `/home/propane/workspace/qhapaq-finance`.
- Branch: `feat/frozen-ecb-fx-snapshot` (unchanged).
- Starting HEAD: `92381c9c18edb2d0f965a9b162a94929e19dfbfa`.
- Required predecessor check: the user-reported commit equals starting HEAD.
- Initial worktree: clean; `git status --short` returned no paths.
- Applicable `AGENTS.md`: none found in the repository or its parent workspace.

## Inspected evidence and boundary

The local README, package metadata, governance documents, source, tests, frozen ECB manifest and
dataset documentation, prior daily reports, Git history, and rendered PNG were inspected. Source and
tests implement a momentum methodological baseline plus checksum-validated ECB loading and a
deterministic FX PNG renderer. The recorded renderer report documents passing tests and visual
inspection from its earlier execution; those historical results were not rerun for this
documentation-only increment. The PNG was opened and inspected during this session.

No inspected source implements company research records, portfolio ingestion, economic dependency
modeling, before/after decision comparison, or portfolio optimization. Planned product statements
are labeled accordingly. No supplied research-universe spreadsheet was found in the repository, and
no claim is made about files elsewhere in WSL.

## Documentation changes

- `README.md`: states the product purpose, implemented/planned boundary, current commands, and link
  to the canonical specification.
- `docs/PRODUCT_SPEC.md`: defines portfolio and evidence semantics, the report flow, unresolved
  inputs, prohibited inferences, and acceptance criteria for the one-company increment.
- Governance state and next actions: replace the completed ECB renderer milestone with the bounded
  one-company evidence-to-report workflow and dependency-gate later expansion.
- Decision log: records the evidence-first product direction without rewriting history.
- Evidence index: links this run and distinguishes inspected implementation from planned work.

No source, test, frozen artifact, manifest, dependency, lockfile, CI, Python requirement, or workflow
file was changed.

## Validation

| Command / check | Observed result |
| --- | --- |
| `git diff --check` | PASS; no output. |
| Relative Markdown link validator over `README.md` and `docs/**/*.md` | PASS with `python3`; one relative link checked and resolved: `README.md` to `docs/PRODUCT_SPEC.md`. An initial invocation with `python` did not run because that command is unavailable. |
| `rg` claim-anchor inspection across source, tests, and prior renderer evidence | PASS; momentum lag/cost/benchmark, checksum validation, offline rendering, provenance, and deterministic-render anchors were present. |
| Changed-path scope check | PASS; every changed path is `README.md` or under `docs/`. |
| `git status --short` | Seven documentation paths only; no source, test, artifact, manifest, dependency, lock, CI, requirement, or workflow change. |

Implementation tests were not run in this session because this increment changes documentation
only. Test outcomes in earlier reports remain historical evidence and are not represented as current
execution.

## Unresolved inputs

- Location and contents of the supplied research universe, and selection of one real company from
  that verified universe.
- For future portfolio decisions: horizon, reference currency, liquidity needs, risk tolerance,
  constraints, and comparison benchmark.

These remain unknown and must not be inferred.
