# Evidence

Last verified: 2026-09-02

Evidence here supports current governance claims; it is not a terminal transcript.

## Product-alignment evidence

| Claim | Evidence | Result |
| --- | --- | --- |
| Local implementation boundary inspected | `README.md`, `pyproject.toml`, `src/qhapaq_finance/`, `tests/`, frozen ECB manifest, and renderer evidence at `92381c9` | Momentum baseline and ECB demonstration only |
| ECB rendered output visually inspected | `artifacts/research-tearsheet-demo.png` and `docs/reports/daily/2026-09-01-tearsheet.md` | Legible provenance-labeled FX tear sheet; not equity research |
| Product direction documented | `docs/PRODUCT_SPEC.md` | Planned semantics and acceptance criteria; no implementation claim |
| Documentation increment execution | `docs/reports/daily/2026-09-02-product-alignment.md` | Baseline, scope, and validation results recorded |
| QCOM evidence-to-report execution | `docs/reports/daily/2026-09-02-qcom-research.md` | Frozen primary sources, typed record, deterministic HTML, tests, and visual QA evidence |

## Stable baseline

| Claim | Evidence | Result |
| --- | --- | --- |
| Quality baseline restored | `5ff2c1e` — `chore: restore quality baseline` | PASS |
| Dependency lock committed | `2ebc421` — `chore: add reproducible dependency lock` | PASS |
| Project identity renamed | `9fb4fe4` — `chore: rename project to Qhapaq Finance` | PASS |
| Lock is internally current | `uv lock --check` | PASS |
| Formatting | `ruff format --check .` | PASS: 17 files already formatted |
| Lint | `ruff check .` | PASS: all checks passed |
| Tests | `pytest` | PASS: 4 tests |
| Static typing | `mypy .` | PASS: 10 source files checked |
| CLI entry point | `uv run qhapaq --help` | PASS: usage displayed without network access |
| Whitespace | `git diff --check` | PASS |

The tests use deterministic synthetic data. They cover lagged momentum selection, transaction-cost
effects, the equal-weight benchmark, and chronological non-overlapping walk-forward folds. They do
not validate live market data or financial usefulness.

## Reproducibility boundary

### Frozen ECB FX snapshot

| Evidence | Verified value |
| --- | --- |
| Dataset ID | `ecb-exr-daily-eur-reference-rates-2015-01-01_2026-08-31` |
| Raw artifact | `data/frozen/ecb/exr_daily_eur_reference_rates_2015-01-01_2026-08-31.csv` |
| Raw bytes / SHA-256 | `2541412` / `9233e2547b72171b8b007e1056e09482e360a765b843330532b2a0e9a05a199e` |
| Manifest | `data/frozen/ecb/exr_daily_eur_reference_rates_2015-01-01_2026-08-31.manifest.json` |
| Manifest SHA-256 | `424e1e1e034a25bc141933cbe7c356b0a18057469ca3b46da22bee2a98720dc4` |
| Requested / actual window | `2015-01-01`–`2026-08-31` / `2015-01-02`–`2026-08-31` |
| Series | `D.CHF.EUR.SP00.A`, `D.GBP.EUR.SP00.A`, `D.JPY.EUR.SP00.A`, `D.USD.EUR.SP00.A` |
| Observations | `11940` total; `2985` per series |
| Validation | Checksum-first offline loader and 13 targeted data/manifest tests pass |

The artifact is the unmodified ECB API response. Values are units of each quoted currency per one
euro. Source: ECB statistics. The acquisition URL, attribution, reuse policy, and point-in-time
semantics are documented in the dataset README and deterministic manifest.

### Remaining boundary

The committed `uv.lock` SHA-256 is
`42430d0aee5a3bc67e0a71be64f36fde8a038abdbd98015fc8bbe60eb55e1136`.

Current source supports explicit configuration, deterministic tests, one validated frozen dataset,
and a deterministic ECB FX renderer with recorded visual evidence. It does not yet produce the
complete evidence package required for a general reproducible quantitative experiment:

- configuration and applicable random seed;
- Git commit SHA and dependency lock identity;
- walk-forward configuration;
- generated metrics and a result manifest.

Until that package exists for an experiment, results must not be described as a demonstrated
investment or trading edge. `docs/AUDIT.md` preserves the historical prototype audit and its
publication gates.
