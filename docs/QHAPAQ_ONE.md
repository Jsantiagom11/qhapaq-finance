# Qhapaq One

## Product contract

Qhapaq One is a curated **reverse-engineering workstation** for fundamental investing. In roughly 30 seconds it should answer:

> What does the market price require, what cash basis are we actually using, how assumption-sensitive is that hurdle, and what would break the case?

The default interaction remains deliberately small:

```text
qhapaq QCOM
qhapaq NVDA
```

Each invocation refreshes the market observation, freezes it as a reproducible sidecar, loads checksum-gated research, loads an explicit analytical cash-basis record, solves the market-implied hurdle, renders one self-contained HTML file, and attempts to open it in the default browser.

## Information hierarchy

```text
PRICE
  -> VERIFIED EVIDENCE
  -> ANALYTICAL CASH BASIS · RUN-RATE
  -> MARKET-IMPLIED 10Y HURDLE
  -> SENSITIVITY
  -> THESIS / COUNTERTHESIS
  -> WHAT MATTERS / INVALIDATION
```

The product excludes technical-indicator clutter, arbitrary AI scores, target prices, order execution, undifferentiated news feeds, and unsupported `BUY / HOLD / SELL` semantics.

## Retired methodology

The previous comparison:

```text
recent FCF growth - implied 10Y FCF growth
```

is retired. A recent-period FCF growth rate is too sensitive to working-capital timing, capex, taxes, one-offs, and cyclicality to be compared directly with a ten-year market-implied CAGR.

There is therefore no numerical Expectations Gap, `CLEARING HURDLE`, or `BELOW HURDLE` in the product contract.

## Analytical cash basis

The current cash basis is explicitly **run-rate only**. It is not through-cycle earning power, fair value, FCFF, a forecast, or a claim that current economics are sustainable.

The bridge is:

```text
reported period FCF proxy
+ comparative working-capital timing adjustment
+ explicit comparative timing adjustments when justified
- explicit SBC economic-cost adjustment
= run-rate period cash basis
× disclosed annualization factor
= annualized run-rate cash basis
```

### Working capital

The current policy retains the prior comparable period's cash pattern and normalizes only the incremental current-period deviation:

```text
adjustment = prior comparable WC cash effect - current WC cash effect
```

This corrects timing noise only. It does **not** normalize the business cycle. A prior comparable period can itself be abnormal.

### Stock-based compensation

The current policy deducts reported SBC as an economic cost. An equivalent second dilution charge must not then be applied again. This is an explicit analytical convention, not the only valid SBC treatment.

### Annualization

H1 × 2 or 9M × 4/3 is mechanical. It is not a forecast and must never be presented as through-cycle cash power.

## Cyclical stress result

A Micron peak/trough stress case demonstrated why the distinction matters. Applying the same run-rate timing adjustments produced approximately:

```text
MU FY2022  +$3.423B
MU FY2023  -$5.073B
```

The large reversal shows that working-capital normalization does not make peak-cycle cash sustainable. Qhapaq therefore rejects a `through_cycle` label under the current methodology.

## Reverse DCF consistency

The current model uses:

```text
equity cash flow -> equity value -> cost of equity
```

`discount_rate` is therefore a **cost of equity**, not WACC. A future FCFF / enterprise-value model would require a separate WACC-consistent contract.

Qhapaq One displays a default 3×3 hurdle sensitivity:

- cost of equity: 8%, 9%, 10%
- terminal growth: 2%, 3%, 4%

The central active scenario defaults to 9% cost of equity and 3% terminal growth unless overridden.

## State semantics

- `RUN-RATE ONLY`: validated evidence, a validated run-rate cash basis, usable equity value, and a solvable reverse-DCF scenario are present. The market hurdle can be shown, but cycle durability has not been validated.
- `INSUFFICIENT DATA`: at least one required layer is absent or incompatible. Missing evidence remains missing.

Qhapaq does **not** currently assert `FAIR`, `STRETCHED`, `BROKEN`, expected return, or that a company can sustain the hurdle.

## Market-cap fallback

Provider market capitalization is preferred. If unavailable, Qhapaq can derive effective equity value from evidence-backed shares outstanding:

```text
observed price × filing shares outstanding
```

The provenance is displayed explicitly.

## Interaction model

The HTML remains offline and self-contained. `Scenario` changes cost of equity and terminal growth and recomputes the implied hurdle locally in the browser. The static sensitivity table keeps assumption dependence visible without interaction.

Refreshing the market means rerunning `qhapaq <TICKER>`.

## Intended scope

Qhapaq is designed for a **small curated universe**, not automated coverage of hundreds of companies. Thesis, counterthesis, cash-basis policy, risks, and invalidation remain human-reviewable research work.

Current bounded cases:

- **QCOM:** validated research plus a 9M analytical run-rate bridge with comparative working capital, cash-tax timing, SBC, and mechanical annualization.
- **NVDA:** validated Q2 FY2027 research plus an H1 analytical run-rate bridge with comparative working capital, SBC, and mechanical annualization.

The next methodological problem is not another UI feature. It is to determine whether a defensible **through-cycle support range** can be built without hiding structural change or cyclicality behind a smoothing formula.

This is research software, not investment advice, a recommendation, an expected return, or a target price.
