# Verified ECB FX research tear sheet evidence — 2026-09-01

## Objective and identity

- Objective: render a deterministic, headless research tear sheet from only the checksum-verified
  frozen ECB FX snapshot.
- Branch: `feat/frozen-ecb-fx-snapshot`.
- Starting HEAD: `9cd1610ba688d3d23bb82ed5d2363c59c94707c3`.
- Effective as-of: `2026-08-31`.
- Analysis series: `D.USD.EUR.SP00.A`, quoted as USD per EUR.
- Research scope: spot-rate change excluding carry; no trading-edge or investment claim.

## Runtime and inputs

| Item | Value |
| --- | --- |
| uv | `0.12.5` |
| Python | `3.12.14` |
| Matplotlib | `3.11.1` |
| NumPy | `2.5.2` |
| pandas | `3.0.5` |
| CSV SHA-256 | `9233e2547b72171b8b007e1056e09482e360a765b843330532b2a0e9a05a199e` |
| Manifest SHA-256 | `424e1e1e034a25bc141933cbe7c356b0a18057469ca3b46da22bee2a98720dc4` |
| Effective window | `2015-01-02` through `2026-08-31` |
| Primary-series observations | `2985` |
| Validated observations, all four series | `11940` |

The CSV and manifest were re-hashed after final rendering and retained their committed identities.
No network, market-data download, synthetic fallback, random input, governance change, or CI change
was used.

## Calculation contract and results

Financial calculations are built in `build_tearsheet_model()` separately from the drawing function.
Point-in-time filtering occurs in the checksum-validating frozen loader before analytics. The model
requires at least 64 primary-series observations, uses daily log returns, annualizes sample
volatility by `sqrt(252)`, and uses a 63-return rolling sample window. Drawdown is spot divided by
its running maximum minus one, so losses extend downward from zero.

| KPI | Raw value | Display |
| --- | ---: | ---: |
| Spot return (ex-carry) | `-0.037116997426` | `-3.7%` |
| Annualized volatility (252 observations/year) | `0.078071859292` | `7.8%` |
| Maximum drawdown | `-0.234371247899` | `-23.4%` |
| Latest ECB rate | `1.159600000000` | `1.1596 USD per EUR` |

Tests explicitly cover quote direction, ex-carry labeling, annualization, the rolling window,
point-in-time exclusion, insufficient-data failure, checksum failures, source/manifest overwrite
rejection, and absence of a network or synthetic fallback.

## Final quality gates

Commands used `UV_CACHE_DIR=<cache-dir>`; rendering commands and tests additionally used
`MPLCONFIGDIR=<matplotlib-cache-dir>` where applicable.

| Command | Result |
| --- | --- |
| `uv sync --frozen --extra dev --extra data` | PASS: 43 packages checked |
| `uv lock --check` | PASS: 55 packages resolved |
| `uv run ruff format --check .` | PASS: 24 files formatted |
| `uv run ruff check .` | PASS |
| `uv run mypy --no-incremental src` | PASS: 9 source files |
| `uv run mypy src` | PASS: 9 source files |
| `uv run pytest -q tests/test_tearsheet.py` | PASS: 14 tests |
| `uv run pytest -q` | PASS: 31 tests |
| `uv run qhapaq --help` | PASS; default read-only Matplotlib config caused a temporary-cache warning only |
| `uv run qhapaq tearsheet --help` | PASS |
| `git diff --check` | PASS |

The interrupted suite initially passed all 12 existing tear-sheet cases. Two focused cases were
added to make the financial assumptions and insufficient-window failure explicit; the affected
format, lint, and targeted-test checks passed before the complete final sequence above.

## Reproducibility and artifact

Two separate CLI processes rendered to temporary files under `<tmp>/qhapaq-tearsheet-renders/`, each
with `--as-of 2026-08-31`. `cmp` confirmed identical bytes. Both temporary renders and the final
repository demo have:

- Dimensions: `2400 x 1350`, 8-bit RGBA PNG.
- SHA-256: `f64fbef0b0cb3045f32b46b65bed1c438b21f640426f4c5805903eb21e2518db`.
- Final path: `artifacts/research-tearsheet-demo.png`.

The previously existing PNG was preserved outside the repository before overwrite; its historical
SHA-256 was also `f64fbef0b0cb3045f32b46b65bed1c438b21f640426f4c5805903eb21e2518db`.
The PNG and backup remain outside the commit.

## Visual inspection

The newly generated final PNG was viewed at original resolution and as a scaled preview. Visual QA
passed: the four KPI cards are readable; indexed spot performance, rolling 63-observation
annualized volatility, downward drawdown, and daily log-return distribution are all visible with
legible axes; the KPI values match the computed model; the artifact name, both input hashes,
effective date, analysis window, ECB attribution, and research-only disclaimer are complete;
contrast is strong; and no text, chart, or footer is clipped or overlapping. At thumbnail scale the
major hierarchy, KPI values, panel shapes, and warning remain distinguishable, while footer hashes
appropriately require enlargement.

## Limitations

The result is a descriptive tear sheet for one ECB reference-rate series. Spot return excludes
carry, transaction costs, and investability constraints. Annualization assumes 252 observations per
year. The frozen source may differ from later ECB revisions, while the repository bytes remain
fixed. Byte-level PNG reproducibility is verified for the recorded locked runtime; portability
across different Matplotlib or font builds is not claimed.
