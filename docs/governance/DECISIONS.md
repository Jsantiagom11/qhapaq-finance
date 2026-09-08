# Decisions

Only decisions supported by repository history or current project documentation belong here.

## 2026-09-02 — Adopt an evidence-first company-to-portfolio product direction

- **Decision:** Make the canonical report flow portfolio summary, economic/statistical exposures,
  asset contribution, company thesis, and underlying evidence; validate it first with one real
  company through a typed record and offline HTML report.
- **Context:** The repository implements a momentum methodological baseline and an ECB FX
  reproducibility demonstration, but neither establishes company research, observed holdings, or
  optimized portfolio weights.
- **Reason:** A one-company evidence path tests provenance, information-availability semantics, the
  research argument, and report navigation before multi-company aggregation adds complexity.
- **Trade-off:** Five-company coverage and portfolio-weight optimization remain dependency-gated;
  portfolio inputs that the user has not supplied remain unresolved rather than inferred.
- **Status:** ACCEPTED as product direction; implementation remains planned in
  `docs/PRODUCT_SPEC.md`.

## 2026-09-01 — Freeze the official ECB response as raw bytes

- **Decision:** Use the official ECB Data Portal `EXR` API for the first point-in-time dataset and
  preserve its CSV response body without normalization or reserialization.
- **Context:** Research reporting requires an independently identifiable input before any result can
  be represented as verified. The ECB publishes daily EUR reference rates and an explicit reuse
  policy with required attribution.
- **Reason:** A canonical official source, fixed request window, raw-byte SHA-256, deterministic
  manifest, and offline loader form a small independently reviewable evidence boundary.
- **Trade-off:** The snapshot remains fixed if the ECB later revises history; refreshing it requires
  a new artifact and manifest rather than silently changing the current evidence.
- **Status:** ACCEPTED for the snapshot acquired 2026-09-01. Source: ECB statistics.

## 2026-08-28 — Adopt the Qhapaq Finance identity

- **Decision:** Use Qhapaq Finance as the human name, `qhapaq-finance` as the repository and Python
  distribution name, `qhapaq_finance` as the import package, and `qhapaq` as the CLI.
- **Context:** The maintained baseline previously used the QuantAncash identity.
- **Reason:** Commit `9fb4fe4` deliberately renamed the README, project metadata, source package,
  imports, tests, CLI entry point, and lock metadata as one coherent identity change.
- **Trade-off:** Existing imports and command invocations using the former names must change.
- **Status:** ACCEPTED and implemented in `9fb4fe4`.

## 2026-08-28 — Do not retain a `quantancash` compatibility alias

- **Decision:** Expose only `qhapaq_finance` and `qhapaq` in the active package and CLI metadata.
- **Context:** The rename commit moved the source package and replaced the console entry point; no
  alias is declared in `pyproject.toml`.
- **Reason:** The committed rename is a clean identity transition; there is no repository evidence
  of a compatibility requirement.
- **Trade-off:** Consumers of the former package or CLI receive no compatibility bridge.
- **Status:** ACCEPTED as evidenced by `9fb4fe4` and current project metadata.

## 2026-08-28 — Commit `uv.lock` as dependency evidence

- **Decision:** Version the generated `uv.lock` file.
- **Context:** The original prototype audit recorded that no reproducible dependency lock was
  supplied.
- **Reason:** Commit `2ebc421` added the lock as the repository's environment-resolution artifact.
- **Trade-off:** Dependency changes must keep project metadata and the lock synchronized.
- **Status:** ACCEPTED and implemented in `2ebc421`.

## 2026-08-28 — Preserve the original prototype audit as history

- **Decision:** Keep `docs/AUDIT.md` under its historical QuantAncash title while active governance
  uses Qhapaq Finance.
- **Context:** The audit explicitly scopes itself to the supplied original prototype and explains
  why the smaller baseline replaced it.
- **Reason:** Rewriting the old name or findings would erase useful decision context.
- **Trade-off:** Readers must distinguish historical findings from current state; this governance
  layer provides that boundary.
- **Status:** ACCEPTED.
