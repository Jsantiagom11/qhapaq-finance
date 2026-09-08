# Qhapaq One

## Product contract

Qhapaq One is the primary human-facing surface for company research. It is designed to answer one question in roughly 30 seconds:

> What is the market requiring from this business, what is the business currently delivering, and what would invalidate the underwriting?

The default interaction is intentionally small:

```text
qhapaq QCOM
qhapaq NVDA
```

Each invocation refreshes the market observation, freezes that observation as a reproducible sidecar, builds the decision model, renders one self-contained HTML file, and attempts to open it in the default browser.

## Information hierarchy

```text
PRICE
  -> VERIFIED EVIDENCE
  -> MARKET-IMPLIED FCF HURDLE
  -> RECENT FCF OBSERVATION
  -> EXPECTATIONS GAP
  -> THESIS / COUNTERTHESIS
  -> WHAT MATTERS / INVALIDATION
```

The product does not expose technical-indicator clutter, arbitrary AI scores, target prices, order execution, or a feed of undifferentiated news.

## State semantics

- `UNDERWRITING`: validated research, a compatible FCF proxy, and a usable equity-value input are present, so the reverse-DCF hurdle can be stated explicitly.
- `INSUFFICIENT DATA`: at least one required layer is absent or incompatible. Missing evidence remains missing.
- `CLEARING HURDLE`: the recent evidence-backed FCF proxy growth rate is above the market-implied constant-growth hurdle under the active scenario.
- `BELOW HURDLE`: the recent evidence-backed FCF proxy growth rate is below the market-implied constant-growth hurdle under the active scenario.

The Expectations Gap is a diagnostic comparison, not a forecast. A positive gap does not mean undervalued; it means recent observed growth exceeds the constant growth rate required by the reverse-DCF scenario. The central question then becomes duration.

`FAIR`, `STRETCHED`, and `BROKEN` remain deliberately unimplemented. Those labels require normalized forward business expectations rather than a comparison between recent observed growth and an implied hurdle.

## Market-cap fallback

Provider market capitalization is preferred when available. If the provider omits it and the validated research record explicitly identifies a shares-outstanding fact, Qhapaq One can derive effective equity value as:

```text
observed price × filing shares outstanding
```

The page displays that provenance. The fallback never silently becomes a provider fact.

## Interaction model

The HTML is offline and self-contained. `Scenario` changes the discount rate and terminal growth and recomputes both the implied FCF hurdle and Expectations Gap locally in the browser.

Refreshing the market is not a fake browser button: rerun `qhapaq <TICKER>`. This keeps network access isolated in the Python market adapter and keeps the rendered artifact deterministic for a frozen snapshot.

## Initial coverage

- **QCOM:** validated research pack; can reach `UNDERWRITING` when a usable equity value is available.
- **NVDA:** validated Q2 FY2027 evidence pack; annualized H1 analytical FCF proxy; filing-shares market-cap fallback; reverse-DCF hurdle; recent FCF growth; Expectations Gap; thesis, counterthesis, risks, and invalidation conditions.

The NVDA local evidence files are checksum-gated Qhapaq evidence capsules with explicit SEC / NVIDIA Investor Relations provenance. They are concise derived records, not byte-for-byte mirrors of the official sources.

This is research software, not investment advice, a recommendation, an expected return, or a target price.
