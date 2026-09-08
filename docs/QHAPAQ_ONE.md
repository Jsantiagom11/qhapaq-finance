# Qhapaq One

## Product contract

Qhapaq One is a curated **reverse-engineering workstation** for fundamental underwriting. It is designed to answer one question in roughly 30 seconds:

> What must the business deliver for the observed market price to make sense, what cash base are we actually underwriting from, and what would break the case?

The default interaction remains deliberately small:

```text
qhapaq QCOM
qhapaq NVDA
```

Each invocation refreshes the market observation, freezes it as a reproducible sidecar, loads checksum-gated company research, applies an explicit normalization policy when available, solves the market-implied hurdle, renders one self-contained HTML file, and attempts to open it in the default browser.

## Information hierarchy

```text
PRICE
  -> VERIFIED EVIDENCE
  -> NORMALIZED CASH POWER
  -> MARKET-IMPLIED 10Y HURDLE
  -> SENSITIVITY
  -> THESIS / COUNTERTHESIS
  -> WHAT MATTERS / INVALIDATION
```

The product deliberately excludes technical-indicator clutter, arbitrary AI scores, target prices, order execution, undifferentiated news feeds, and unsupported `BUY / HOLD / SELL` semantics.

## Methodological correction

The previous comparison:

```text
recent FCF growth - implied 10Y FCF growth
```

has been retired. A recent-period FCF growth rate is too sensitive to working-capital timing, capital expenditure, taxes, cyclicality, and one-off effects to be treated as comparable with a ten-year market-implied CAGR. Qhapaq must not turn a noisy cash-flow observation into a directional valuation signal.

There is therefore no `CLEARING HURDLE`, `BELOW HURDLE`, or numerical Expectations Gap in the current product contract.

## Normalized Cash Power

Normalized Cash Power is an analytical starting cash base for the reverse DCF. It is not reported FCF, FCFF, a forecast, fair value, or a claim about sustainable growth.

The v0.1 normalization bridge is deliberately explicit:

```text
reported period FCF proxy
+ comparative working-capital normalization
+ explicit timing normalization, when evidence supports it
- explicit SBC economic-cost adjustment
= normalized period cash power
× disclosed annualization factor
= normalized annualized cash power
```

### Working-capital policy

Qhapaq does not simply add back all working-capital investment. The v0.1 policy retains the prior comparable period's cash pattern and normalizes only the incremental current-period deviation:

```text
adjustment = prior comparable WC cash effect - current WC cash effect
```

This is still an analytical assumption. If the prior period was abnormal or the business has changed structurally, the normalization can be wrong and must be reviewed.

### Stock-based compensation policy

The current policy deducts reported stock-based compensation as an economic cost. An equivalent dilution charge must not then be applied again. This is a conservative analytical convention, not the only valid treatment of SBC.

### Timing adjustments

Timing adjustments require an explicit current/prior comparable evidence pair. QCOM currently uses this mechanism for the unusually large cash-tax timing difference. Qhapaq normalizes only the incremental timing deviation; it does not add back all cash taxes.

### Annualization

Annualization is mechanical. H1 × 2 or 9M × 4/3 does not assert that the next reporting periods will reproduce the current period. This remains a material limitation of v0.1.

## Reverse DCF consistency

The current reverse DCF uses:

```text
equity cash flow -> equity value -> cost of equity
```

The `discount_rate` is therefore a **cost of equity**, not WACC. A future FCFF / enterprise-value model would require a separate WACC-consistent contract.

Qhapaq One shows a 3×3 hurdle sensitivity by default:

- cost of equity: 8%, 9%, 10%
- terminal growth: 2%, 3%, 4%

The central displayed hurdle is the active scenario, currently 9% cost of equity and 3% terminal growth unless overridden.

## State semantics

- `UNDERWRITING`: validated research, a validated normalization record, a usable equity value, and a solvable reverse-DCF scenario are present.
- `INSUFFICIENT DATA`: at least one required layer is absent or incompatible. Missing evidence remains missing.

Qhapaq does **not** currently assert `FAIR`, `STRETCHED`, `BROKEN`, or that a company can sustain the implied hurdle. Those claims require a separate cycle-aware forward-support range that has not yet passed validation.

## Market-cap fallback

Provider market capitalization is preferred. If it is unavailable, Qhapaq can derive effective equity value from evidence-backed shares outstanding:

```text
observed price × filing shares outstanding
```

The provenance is displayed explicitly. A derived value never silently becomes a provider fact.

## Interaction model

The HTML is offline and self-contained. `Scenario` changes cost of equity and terminal growth and recomputes the implied hurdle locally in the browser. The static sensitivity table makes assumption dependence visible even without interacting with the page.

Refreshing the market means rerunning `qhapaq <TICKER>`. Network access remains isolated in the market adapter; a frozen snapshot keeps the rendered artifact reproducible.

## Intended scope

Qhapaq is currently designed for a **small, curated company universe**, not automatic coverage of hundreds of tickers. The research burden is part of the product: thesis, counterthesis, normalization policy, risks, and invalidation must remain reviewable by a human analyst.

Current bounded cases:

- **QCOM:** validated research plus a 9M normalization bridge that includes comparative working capital, cash-tax timing, SBC, and mechanical annualization.
- **NVDA:** validated Q2 FY2027 research plus an H1 normalization bridge that includes comparative working capital, SBC, and mechanical annualization.

The next methodological gate is a cyclical semiconductor stress test. Until the same framework survives peak/trough cases without manufacturing false comfort, Normalized Cash Power remains a candidate methodology rather than a completed valuation doctrine.

This is research software, not investment advice, a recommendation, an expected return, or a target price.
