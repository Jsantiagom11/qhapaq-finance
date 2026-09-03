# Qhapaq Finance

Qhapaq Finance is research software for evidence-based company research and portfolio decisions.
Its intended report moves from general context to specific support:

```text
Portfolio summary -> economic/statistical exposures -> asset contribution
                  -> company thesis -> underlying evidence
```

The product direction and evidence contract are defined in the
[canonical product specification](docs/PRODUCT_SPEC.md).

> Research software only. Nothing in this repository is investment advice, a recommendation, or
> evidence of future performance. The software does not execute orders.

## What works today

- A methodological cross-sectional momentum backtest ranks assets by trailing return, applies a
  one-day signal lag, accounts for proportional turnover costs, and compares results with an
  equal-weight universe benchmark. Deterministic synthetic fixtures test the method; they are not
  an empirical demonstration.
- A checksum-validating offline loader reads the committed, byte-frozen ECB daily EUR reference-rate
  snapshot.
- An ECB FX tear-sheet renderer produces a deterministic PNG with source hashes, effective date,
  analysis window, descriptive calculations, and a research-only warning. It is a reproducibility
  demonstration, not implemented equity research and not a mean-variance or MPT optimizer.

The repository does not yet implement company evidence records, thesis/counterthesis workflows,
observed portfolio ingestion, economic-dependency modeling, decision comparisons, or portfolio
optimization.

## Current usage

```bash
python -m venv .venv
source .venv/bin/activate              # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e ".[data,dev]"
pytest
```

Run the existing momentum baseline with mutable provider data:

```bash
qhapaq --tickers SPY QQQ IWM EFA --start 2015-01-01 --cost-bps 10
```

Provider results can change with corrections and the chosen end date. This command does not create
a vintage, reproducible research record.

Render the reproducibility demonstration entirely from the committed ECB snapshot:

```bash
qhapaq tearsheet \
  --data data/frozen/ecb/exr_daily_eur_reference_rates_2015-01-01_2026-08-31.csv \
  --manifest data/frozen/ecb/exr_daily_eur_reference_rates_2015-01-01_2026-08-31.manifest.json \
  --output /tmp/qhapaq-ecb-tearsheet.png \
  --as-of 2026-08-31
```

## Methodological baseline

At each scheduled rebalance, the baseline ranks assets by trailing return, holds up to the strongest
`top_n` assets with positive momentum, and applies the new weights one trading day later. Gross and
net results are reported; net results subtract a configurable proportional cost from one-way
turnover. Features use trailing observations, walk-forward folds are chronological and
non-overlapping, and an equal-weight universe is the comparison benchmark.

These controls do not resolve survivorship bias, point-in-time constituent membership, delistings,
corporate-action quality, data snooping, market impact, taxes, borrow constraints, or statistical
uncertainty. `sharpe_zero_rf` is descriptive and is not a significance test.

## Repository map

```text
docs/PRODUCT_SPEC.md          canonical product and evidence contract
docs/governance/             workflow, state, decisions, actions, and evidence index
docs/reports/daily/          execution-evidence reports
data/frozen/ecb/             verified ECB snapshot and provenance manifest
src/qhapaq_finance/          momentum baseline, data validation, and ECB renderer
tests/                       deterministic method and evidence-boundary tests
```
