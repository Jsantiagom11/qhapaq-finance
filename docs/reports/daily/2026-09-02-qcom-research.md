# QCOM evidence-to-report execution — 2026-09-02

## Outcome

Implemented the bounded QCOM research workflow authorized by the handoff: a task-supplied one-symbol
universe, three frozen Qualcomm/SEC primary documents, typed facts and calculations, reviewed Spanish
narrative, thesis/counterthesis/invalidation, and a deterministic self-contained HTML report. This is
research only; it is not a holding, recommendation, allocation, target price, or suitability result.

## Identity and acquisition

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

Targeted research tests passed (45), and the research CLI smoke passed. UTC and America/Lima renders
were byte-identical, confirming deterministic research rendering across the tested timezones.

Fresh desktop, mobile, offline, and interaction visual QA is still required before publication; no
visual PASS is claimed for the QCOM report.
