# Rainy-day testing

The research gate protects two things independently: software correctness and the
integrity of financial conclusions. Passing tests does not establish an investable edge.

## Automated matrix

| Scenario | Expected behavior |
|---|---|
| Provider returns tickers in another order | Requested order is restored by label, never by position |
| Provider omits one ticker | Download fails with the missing symbol |
| One asset contains a missing observation | Backtest rejects the panel by default |
| Duplicate dates or asset columns | Validation rejects the panel |
| Zero, negative or non-finite prices | Validation rejects the panel |
| −100% or non-finite strategy return | Metrics reject the series |
| Zero volatility | Sharpe is explicitly undefined (`NaN`) |
| Invalid annualization | Metrics fail fast |
| Signal date and earned return | Weights remain lagged by one session |
| Costs at 0/10/25/50/100 bps | Net result degrades monotonically |
| Expanding walk-forward folds | Test windows are chronological and never overlap |
| Insufficient training history | Runner refuses to emit an empty report |
| One source price changes | SHA-256 dataset checksum changes |
| JSON manifest | Records data, configuration, environment and metrics |

## Required publication scenarios

Before interpreting a strategy result, run at least:

1. Base commission and slippage assumption.
2. Costs multiplied by 2 and 5.
3. One-session execution delay beyond the baseline lag.
4. A frozen point-in-time universe including failed/delisted members where licensing permits.
5. Subperiods containing a crisis, low-volatility regime and recent unseen period.
6. Benchmark-relative confidence intervals or block-bootstrap uncertainty.

## Known boundaries

- Yahoo Finance is a convenient research source, not an auditable institutional feed.
- Strict complete-case validation is deliberately conservative; production research may
  introduce a documented missing-data policy, but must never silently convert gaps to zero.
- The current fixed momentum rule has no fitted parameters inside folds. Any future tuning
  must be nested entirely inside each training window.
- The manifest identifies the panel used, but reproducibility still requires retaining the
  corresponding licensed dataset snapshot.
