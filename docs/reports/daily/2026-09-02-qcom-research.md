# QCOM evidence-to-report execution — 2026-09-02

## Outcome

Status: `AUTOMATED_RELEASE_VALIDATION_COMPLETE` as of 2026-09-03.

Implemented the bounded QCOM research workflow: a one-symbol universe, three frozen Qualcomm/SEC
primary documents, typed facts and calculations, reviewed Spanish narrative,
thesis/counterthesis/invalidation, and a deterministic self-contained HTML report. This is research
only; it is not a holding, recommendation, allocation, target price, or suitability result.

## Identity and acquisition

- Root: `<repo-root>`; branch `feat/frozen-ecb-fx-snapshot`; starting HEAD
  `92381c9c18edb2d0f965a9b162a94929e19dfbfa`.
- Pre-existing documentation changes were copied with hashes and a baseline diff to an external
  temporary workspace before edits.
- Cutoff: `2026-09-01`; retrieval: `2026-09-02T15:02:17-05:00`.
- SEC returned HTTP 403 to the bounded archive download; no bypass was attempted. Issuer-hosted
  copies discovered from Qualcomm IR were used, with SEC filing-index metadata for filing identity
  and publication dates.
- Exact source paths, URLs where applicable, byte counts, publication/reporting dates and SHA-256
  identities are in `data/research/qcom/manifest.json` and
  `data/research/qcom/relative-context.json`. The immutable runtime inputs are versioned under
  `data/evidence/qcom/`; acquisition scratch files remain ignored under `data/raw/qcom/`.

## Evidence and limitations

The report reconciles FY2025/FY2024 GAAP revenue, operating income and cash flow, plus comparable Q3
and nine-month FY2026/FY2025 facts. Calculations include revenue growth, operating margins and a
defined operating-cash-flow-minus-capex analytical FCF. Valuation is explicitly incomplete because
no dated market-price/share/debt package was frozen. Source revisions after retrieval and the lack of
independent non-issuer corroboration remain limitations.

## Validation

Release hardening made all seven required evidence inputs clone-available and checksum-gated,
rejected duplicate JSON keys and missing declared context, made timestamp conversion explicitly UTC,
moved peer-range calculation into the validated provenance graph, and completed result-manifest
input identity. The visual design, calculations, methodology, data, peers, colors, and analytical
scope were unchanged.

Targeted research tests passed (45), the full suite passed (76), Ruff format and lint passed, cold
mypy passed for 11 source files, the lock check resolved 55 packages, the research CLI smoke passed,
and `git diff --check` passed. UTC and America/Lima renders were byte-identical with HTML SHA-256
`74a34dcdede580c7e4242bc5285a769b2cee21aac1cb2f85212c955d3875c905`.

A clean snapshot containing only tracked and non-ignored candidate files completed a frozen `uv`
install, passed all 76 tests, rendered offline in both timezones, and produced the same approved
HTML identity. CI now enforces the frozen install, lock check, formatting, lint, cold typing, tests,
CLI render, deterministic comparison, and approved checksum, then publishes HTML and its single
named result manifest as workflow artifacts.

Generated reports and manifests remain ignored and are not portable repository inputs. Fresh
desktop, mobile, offline, and interaction visual QA is still required before publication; no visual
PASS is claimed by this automated hardening record. No commit, push, merge, deployment,
publication, trade, or scheduled task was created.
