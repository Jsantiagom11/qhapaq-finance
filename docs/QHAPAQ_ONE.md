# Qhapaq One

## Product contract

Qhapaq One is the primary human-facing surface for company research. It is designed to answer one question in roughly 30 seconds:

> What is the market requiring from this business, what does validated evidence currently support, and what would invalidate the underwriting?

The default interaction is intentionally small:

```text
qhapaq QCOM
qhapaq NVDA
```

Each invocation refreshes the market observation, freezes that observation as a reproducible sidecar, builds the decision model, renders one self-contained HTML file, and attempts to open it in the default browser.

## Information hierarchy

```text
PRICE
  -> EVIDENCE
  -> IMPLIED EXPECTATIONS
  -> THESIS / COUNTERTHESIS
  -> WHAT MATTERS
  -> INVALIDATION
```

The product does not expose technical-indicator clutter, arbitrary AI scores, target prices, order execution, or a feed of undifferentiated news.

## State semantics

- `UNDERWRITING`: validated research, a compatible FCF proxy, and a usable market capitalization are present, so the reverse-DCF hurdle can be stated explicitly.
- `INSUFFICIENT DATA`: at least one required layer is absent or incompatible. Missing evidence remains missing.

`FAIR`, `STRETCHED`, and `BROKEN` are deliberately not implemented in v0.1. Those labels require an evidence-backed comparison between the market hurdle and a normalized business expectation; Qhapaq must not manufacture that comparison.

## Interaction model

The HTML is offline and self-contained. The only interactive control in v0.1 is `Scenario`, which changes the discount rate and terminal growth and recomputes the implied FCF growth hurdle locally in the browser.

Refreshing the market is not a fake browser button: rerun `qhapaq <TICKER>`. This keeps network access isolated in the Python market adapter and keeps the rendered artifact deterministic for a frozen snapshot.

## Initial coverage

- **QCOM:** validated research pack exists and can reach `UNDERWRITING` when the market snapshot supplies market capitalization.
- **NVDA:** market observations can render immediately, but the product must remain `INSUFFICIENT DATA` until a validated primary-evidence NVDA research pack is added.

This is research software, not investment advice, a recommendation, an expected return, or a target price.
