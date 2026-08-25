# Audit of the original QuantAncash prototype

Audit date: 2026-08-25. Scope: the supplied `QuantAncash-audit.zip`.

## Executive finding

The original repository was an early architecture sketch, not a valid empirical result.
It contained useful instincts—lagged positions, transaction costs, ranking and rolling
splits—but the main pipeline could not yet support a defensible performance claim.

## Critical methodological issues

1. `build_features(df.loc[start:end])` recomputed rolling features using only the test
   slice. This discards training history at the boundary and makes the first observations
   unusable; it is not a faithful live simulation.
2. Feature selection used the whole training sample and the tuner evaluated predictions
   on the same observations used for fitting. That score measures in-sample fit, not
   generalization.
3. Universe ranking used full history through each rebalance date, including inconsistent
   lifetimes, but did not address point-in-time constituents or survivorship bias.
4. The risk overlay calculated drawdown from the underlying asset return rather than the
   strategy equity, so it did not measure the risk it purported to control.
5. Backtest segments could overlap at rebalance boundaries, and concatenation did not
   verify unique, ordered dates.
6. No benchmark, test suite, reproducible dependency lock, dataset snapshot or statistical
   uncertainty was supplied. Therefore the printed return had no reliable context.

## Software issues

- `features/engineering.py` and `features/feature_engineering.py` duplicated one function
  with incompatible column names.
- Position sizing existed independently in `portfolio/position_sizing.py`,
  `risk/position_sizing.py`, `risk/sizing.py` and `portfolio/risk_model.py`.
- Several imports were absent from `setup.py` (`scikit-learn`, `optuna`, `yfinance` was
  present but unrestricted); meanwhile many package directories lacked `__init__.py`.
- Random-forest and gradient-boosting models had no fixed seed in the executed ensemble.
- Numerous empty modules inflated the architecture without behavior.
- README and `.gitignore` were effectively empty; generated logs and plots were mixed
  into source/data locations.
- Wildcard configuration imports and top-level module imports made installed execution
  fragile.

## Refactor decision

The replacement removes the unvalidated machine-learning layer and establishes a smaller
baseline first. It adds an installable `src/` package, typed configuration, data-boundary
validation, a lagged signal, turnover costs, an equal-weight benchmark, metrics,
chronological splits, deterministic tests and CI.

The removed complexity should be restored only when each component has an out-of-sample
test and a clear contribution relative to the baseline.

## Publication gate

Before calling the project research-complete:

- freeze and checksum point-in-time inputs;
- define the hypothesis and evaluation protocol before viewing the test result;
- tune only within nested training folds;
- test several plausible transaction-cost and slippage scenarios;
- report benchmark-relative results with uncertainty and failed experiments;
- generate a dated report from a clean checkout in CI;
- document data licensing and known universe biases.

