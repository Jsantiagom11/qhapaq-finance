# QuantAncash

QuantAncash is a compact, reproducible research project for testing a simple
cross-sectional momentum rule against an equal-weight benchmark. Its purpose is
methodological: make every assumption visible and make optimistic mistakes difficult.

> Research software only. Nothing in this repository is investment advice or evidence
> of future performance.

## What the baseline tests

At each scheduled rebalance, the strategy ranks assets by trailing return, holds up to
the strongest `top_n` assets with positive momentum, and applies the new portfolio one
trading day later. The report shows both gross and net results; net results subtract a
configurable proportional cost from one-way turnover.

The equal-weight universe is included as a benchmark. The repository does **not** claim
an edge, and it intentionally ships without a cherry-picked performance chart.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate              # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e ".[data,dev]"
pytest
quantancash --tickers SPY QQQ IWM EFA --start 2015-01-01 --cost-bps 10
quantancash --tickers SPY QQQ IWM EFA --start 2015-01-01 --walk-forward \
  --report-json reports/generated/baseline.json
```

The CLI downloads current provider data, so results can vary with corrections and the
chosen end date. JSON reports record the exact panel checksum, date range, assets,
configuration, environment and out-of-sample metrics. Preserve the matching dated input
snapshot outside Git when reproducing a published study.

## Leakage controls

- Features use trailing observations only.
- Portfolio weights are shifted one day before they earn returns.
- Walk-forward folds are chronological and test windows do not overlap.
- Every walk-forward test fold is evaluated with its preceding history, then only the
  unseen test rows are concatenated into reported performance.
- Costs are charged when weights change.
- Missing prices and omitted provider symbols fail loudly instead of becoming zero returns.
- Feature selection and parameter tuning must occur inside each training fold; the
  baseline has neither, which keeps the first experiment auditable.

These safeguards reduce common errors but do not prove that a study is unbiased.
Survivorship bias, delistings, corporate-action quality, data snooping, market impact,
taxes and borrow constraints remain outside this baseline.

## Repository map

```text
src/quantancash/
  backtest.py       portfolio accounting and benchmark
  config.py         explicit experiment assumptions
  data.py           validation and optional provider adapter
  metrics.py        transparent performance statistics
  signals.py        past-only baseline signal and weights
  walk_forward.py   chronological expanding splits
  report.py         checksummed machine-readable research manifest
tests/              deterministic tests using synthetic data
docs/AUDIT.md       findings from the original prototype
```

## Interpreting the output

`sharpe_zero_rf` uses a zero risk-free rate, arithmetic mean return and annualized
daily volatility. It is descriptive, not a statistical significance test. Always
compare `strategy_net` with `equal_weight_benchmark`, inspect multiple cost assumptions,
and report negative or inconclusive results.

The deterministic [rainy-day matrix](docs/RAINY_DAY_TESTING.md) covers provider column
reordering, missing observations, impossible returns, cost sensitivity, walk-forward
boundaries and manifest integrity.

## Next research milestone

Add a frozen, point-in-time universe with constituent history, uncertainty estimates and
an HTML report derived from the machine-readable manifest. Only after that foundation
should predictive models be reintroduced.
