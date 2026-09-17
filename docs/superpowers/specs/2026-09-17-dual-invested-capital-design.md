# Dual Invested Capital Engine Design

## Goal

Make financing identity the generic invested-capital authority, retain operating
composition as an independently auditable reconciliation, and preserve the
existing `snapshot.invested_capital.average` consumer contract.

## Boundary

`financial_promotion.py` promotes a canonical, mutually exclusive component
registry for each balance-sheet endpoint. `accounting.py` turns those promoted
facts into Pydantic component and endpoint models, computes the two identities,
and applies reconciliation independently at opening and closing. No production
branch may depend on ticker.

## Data model and calculations

Every component has a value, `DataState`, and source lineage. A source-reported
zero is `REPORTED_ZERO`; any unavailable, unmapped, or consolidated component
is `MISSING_OR_CONSOLIDATED` and has no numeric value. Missing states never
enter arithmetic as zero.

The primary node is common equity plus exactly one debt representation, operating
lease liabilities only when not represented by debt, other explicitly classified
financing claims, less exactly one cash/securities representation and other
classified non-operating financial assets. Required primary components are
equity, debt policy, cash policy, and securities policy; optional component
absence is permitted only where the canonical policy explicitly establishes
that the component is inapplicable.

The secondary node uses operating NWC, net PPE, net intangibles, other disclosed
non-current operating assets, and non-current operating liabilities. It returns
`None` when a needed operating classification is unknown, including a missing
intangible disclosure. Lease liabilities remain financing claims and their ROU
asset remains an operating asset when they are explicitly available.

For each endpoint, `(bottom_up - top_down) / abs(top_down)` determines status:
at most five percent is `ALIGNED`; more is `MATERIAL_GAP`; missing secondary
data is `INSUFFICIENT_DATA`. A material gap prevents `.average`; insufficient
bottom-up evidence does not.

## Promotion policy

The registry defines preferred, exclusive groups rather than independently
additive aliases: total debt versus current/non-current debt, total marketable
securities versus current/non-current securities, and debt-inclusive versus
separate lease liability. It promotes balance-sheet components at both revenue
TTM endpoints and carries source IDs into provenance. It explicitly emits a
missing state if a policy component cannot be promoted; it does not fabricate a
fact or numeric zero.

## Compatibility and diagnostics

`InvestedCapitalPair.average` remains public. QCOM and NVDA legacy evidence is
adapted through the same endpoint models. Generic analysis maps failures to
stable internal reasons: `PRIMARY_IC_REQUIRED`, `CAPITAL_RECONCILIATION_GAP`,
and `BOTTOM_UP_INSUFFICIENT_DATA`, without changing its external status enum.

## Tests

Tests use generic synthetic endpoint evidence for state, exclusivity, arithmetic,
and reconciliation semantics. The frozen AAPL corpus is the integration case:
the opening missing intangible leaves only its bottom-up node incomplete, while
the financing pair remains approximately 34.542B / 45.347B / 39.945B. Existing
QCOM and NVDA outputs remain regression contracts.

## Constraints

- Preserve fail-closed semantics and do not treat absent XBRL facts as zero.
- Do not alter SEC acquisition, networking, company resolution, or unrelated
  valuation/presentation code.
- Do not add ticker-specific production logic or dependencies.
