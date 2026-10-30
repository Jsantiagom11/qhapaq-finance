# Diamond Opportunities v0.1 — acceptance record

Status: **DEMO_ONLY** (usable and reproducible historical research routing; not a
current or filing-native production screen).

## Product outcome

Qhapaq can now replay a real historical S&P 500 cutoff without network access, seal the
exact evidence files read into a checksum-verified `COMPLETE` snapshot, preserve
Diamond's authoritative order in CandidateSet v1, and generate deterministic JSON and
Markdown reports. A focused command explains one selected or blocked company and keeps
verified structured observations, derived metrics, inferences, assumptions and missing
evidence separate.

The report is research routing. It does not produce BUY/HOLD/SELL, fair value or price
targets.

## Reproduction

Source cache (protected, read-only during acceptance):

```text
~/workspace/qhapaq-finance/.worktrees/
diamond-funnel-debt-zero-v0.4/data/cache/diamond
```

From the `feat/diamond-opportunities-v0.1` worktree:

```bash
MPLCONFIGDIR=/tmp/qhapaq-opportunities-mpl .venv/bin/qhapaq opportunities \
  --as-of 2026-09-22 \
  --cache-root ~/workspace/qhapaq-finance/.worktrees/diamond-funnel-debt-zero-v0.4/data/cache/diamond \
  --output output/diamond-opportunities-2026-09-22 \
  --top 10

MPLCONFIGDIR=/tmp/qhapaq-opportunities-mpl .venv/bin/qhapaq opportunity MO \
  --report output/diamond-opportunities-2026-09-22/opportunities.json
```

Generated artifacts are intentionally ignored by Git:

- `output/diamond-opportunities-2026-09-22/opportunities.json`
- `output/diamond-opportunities-2026-09-22/opportunities.json.sha256`
- `output/diamond-opportunities-2026-09-22/opportunities.md`
- `output/diamond-opportunities-2026-09-22/mo-research.md`
- `output/diamond-opportunities-2026-09-22/snapshot/manifest.json`
- `output/diamond-opportunities-2026-09-22/snapshot/cache/`

## Real acceptance result

Cutoff: `2026-09-22` (historical).

| Measure | Result |
|---|---:|
| Universe securities | 503 |
| Canonical records | 503 |
| Diamond-eligible/rankable | 117 |
| Excluded | 386 |
| Requested / selected | 10 / 10 |
| Provider requests | 0 |
| Cache misses | 0 |
| Cache hits during replay | 1,526 |
| Selected snapshot files | 2,026 |
| Snapshot size | 1.9 GiB |
| Future-dated selected observations | 0 |
| Future-dated latest in-scope filings | 0 |

Top 10, in exact Diamond/CandidateSet order:

1. MO — Altria — `QUALITY_VALUE` — 86.94
2. UBER — Uber — `INFLECTION` — 85.42
3. CRH — CRH plc — `INFLECTION` — 80.47
4. BKNG — Booking Holdings — `COMPOUNDER` — 80.22
5. RMD — source name `ResMed|` — `INFLECTION` — 78.66
6. CNC — Centene Corporation — `QUALITY_VALUE` — 77.28
7. ECL — Ecolab — `INFLECTION` — 75.69
8. VRT — Vertiv — `COMPOUNDER` — 74.80
9. IDXX — Idexx Laboratories — `COMPOUNDER` — 74.23
10. EXPE — Expedia Group — `COMPOUNDER` — 73.90

The source `ResMed|` label is preserved verbatim because canonical/source data was not
authorized for alteration. It is a visible source-quality issue, not a report rewrite.

Non-exclusive exclusion reasons recorded by the report:

| Reason | Count |
|---|---:|
| `NO_RESEARCH_PRIORITY` | 386 |
| `UNSUPPORTED_METHODOLOGY` | 104 |
| `FUNDAMENTALS_STALE` | 106 |
| `QUALITY_INSUFFICIENT_DATA` | 382 |
| `GROWTH_INSUFFICIENT_DATA` | 291 |
| `CAPITAL_INSUFFICIENT_DATA` | 366 |
| `PRICE_INSUFFICIENT_DATA` | 354 |

## Identities and checksums

```text
dataset_identity      46677793154fc2a7888361aa613d9c61db124b5f5b1eb414a4b3ad471a05c2a2
snapshot_id           diamond-snapshot:27402ba617976a44cdea0760dae667cb0a4223a072ead4403fd3c4252766e8ae
ranked_order_sha256   222d06d4f8562db175ac4c5b13b0b36a1fb3e3039f562110c776c070f97c4c8a
candidate_set_id      780d27e732dd26eaa7f0343fe9e7f7727db013ddc5016bcc783b136c16fb69e4
opportunities.json    5d3822cd228600e340a001310114881fe31f5ff89e3eda9c884b96b8ace75b23
json checksum sidecar 458916b72bb130c1dd8c651c59ef8517bdc8bb456795c90d28be60ac91789a6a
opportunities.md      4cdf4fc56f9ce0c8bfa5f9c9446e305d1c9e5323a28b3003d89332213a16d1fd
snapshot/manifest     0f11097c2e06497e0318de15cd0a73658f2ccc102628f6f02350855dac116b82
mo-research.md        d8ec5225200c708deb0006b98cb386fbd01433ed22cc50156f7eb42fedeefe00
```

An independent second seal under
`output/diamond-opportunities-2026-09-22-repro/` produced byte-identical JSON,
Markdown and manifest files (`cmp` exit 0) and the same dataset, snapshot, ranked-order
and CandidateSet identities.

Measured wall times on this machine:

- first source audit + seal + replay + report: 43.33 s, max RSS 194,128 KiB;
- independent second seal + replay + report: 69.96 s, max RSS 194,312 KiB;
- replay of the existing snapshot with a nonexistent source path: 7.51 s, max RSS
  176,376 KiB.
- checksum/snapshot/CandidateSet-validated focused MO view: 3.33 s, max RSS 118,912
  KiB.

The successful nonexistent-source replay proves that a finalized artifact no longer
depends on the migration source.

Final repository gates after review fixes:

- pytest: 1,075/1,075 passed in 36.61 s (max RSS 506,508 KiB);
- Ruff format: 261 files formatted;
- Ruff lint: pass;
- mypy `--no-incremental src`: 107 source files, pass in 11.69 s;
- `uv lock --check`: 90 packages resolved, pass;
- focused opportunity/snapshot/provider regression cohort: 72/72 passed;
- independent code review: all three integrity findings resolved; no residual blockers.

Continuation verification on 2026-10-30:

- environment preflight confirmed the worktree-local editable install, Python 3.12.14,
  the existing 90-package lock, and successful full/FAST collection;
- FAST: 140/140 passed in 1.91 s;
- expanded opportunity/snapshot/provider/CandidateSet cohort: 89/89 passed in 3.33 s;
- full pytest: 1,075/1,075 passed in 29.64 s;
- Ruff format/lint, cold mypy over 107 source files, `uv lock --check`, and
  `git diff --check`: pass;
- existing-snapshot replay with a deliberately nonexistent source path: 12.19 s,
  max RSS 176,364 KiB, `COMPLETE`, 10 selected;
- checksum/snapshot/CandidateSet-validated focused MO view: 2.63 s, max RSS
  119,332 KiB;
- artifact hashes and byte-equality checks still match the identities above.

## Integrity and confidence boundary

- Every selected snapshot file is content-addressed by relative path, size and SHA-256.
- The public manifest is written only after an offline replay reproduces dataset identity
  and the complete rankable order.
- Snapshot files have no write bits; loader verification rejects missing, extra or
  changed bytes.
- Focused inspection verifies the JSON checksum sidecar, the complete snapshot inventory,
  snapshot context and the recomputed CandidateSet identity/order before rendering.
- SEC evidence retains CIK, evidence revision, payload SHA-256, latest in-scope filing
  date and accession at issuer level.
- All 337 determinant evidence observations in the Top 10 are on or before the cutoff.
- All Top 10 issuers have issuer-level SEC provenance.
- All 337 determinant observations explicitly mark exact per-metric publication date as
  unavailable. The report does not misrepresent the issuer-level latest accession as the
  locator for those values.
- The Wikipedia universe object declares `data_as_of=2026-09-22` but was retrieved at
  `2026-09-23T01:30:47.763255+00:00` and is not membership-effective-dated. Financial
  observations are point-in-time filtered, but historical S&P 500 membership cannot be
  independently certified from this source.
- The protected source worktree remained clean and contained 2,030 files before/after
  acceptance. The snapshot selected only the 2,026 files actually read.
- No dependency was added and no canonical-data file was changed.

## Why status is DEMO_ONLY

The delivery is functional and reproducible, but three conditions prevent a production or
"today" claim:

1. the latest available complete cutoff is historical (`2026-09-22`), not the execution
   date (`2026-10-29`);
2. the Wikipedia universe is not membership-effective-dated, so full point-in-time
   universe membership is not certifiable;
3. canonical observations do not retain exact per-metric filing accession/publication
   locators, so evidence is suitable for structured discovery but not filing-native
   certification.

The minimum path to `VALUE_DELIVERED` under current-date production semantics is to
produce a current exact-cutoff source cache with zero misses and preserve per-observation
filing locators through canonicalization, then rerun the unchanged seal/replay/report
workflow.
