# Diamond Funnel — Design Specification

**Status:** Approved / implementation-ready
**Revision:** Technical review incorporated — current dilution overlay + FCF base-effect correction
**Target path:** `docs/superpowers/specs/2026-09-20-diamond-funnel-design.md`
**Product:** Qhapaq Finance
**Scope:** Discovery layer only. This specification does not modify Qhapaq One, SEC canonicalization, or the Evidence Engine.

---

## 1. Purpose

Diamond Funnel is Qhapaq's low-cost discovery layer.

Its job is not to produce BUY/HOLD/SELL recommendations or intrinsic-value targets. Its job is to reduce a broad equity universe into a small, explainable research shortlist using inexpensive structured fundamentals.

The product pipeline becomes:

```text
Discovery             Comprehension             Verification
Diamond Funnel   ->   Qhapaq One          ->   Evidence Engine
breadth / cheap       depth / analytical       primary-source / expensive
```

Primary question:

> Which companies deserve deeper research, and what observable fundamental pattern caused them to surface?

The Funnel must optimize **cost of information per useful research decision**, not maximum accounting precision for every security.

---

## 2. Architectural Decisions

### 2.1 Relative scoring, not "perfect company" absolute thresholds

Diamond Funnel SHALL NOT require every company to satisfy a globally fixed set such as:

```text
ROIC > 15%
FCF yield > 5%
revenue growth > 10%
net debt < 1x EBIT
```

That approach systematically favors certain business models, maturity stages, and sector structures and can produce either mega-cap concentration or an empty result set.

The default scoring model SHALL therefore use:

1. **sector-relative percentiles** for comparable features;
2. **absolute validity guardrails** only where economics become invalid or misleading;
3. **multiple research archetypes**, so a company does not need to be excellent on every dimension simultaneously.

Peer group:

```text
primary: GICS sector
fallback: eligible full universe when peer group n < 20
```

Before percentile calculation, numeric features SHALL be winsorized at the peer group's 5th and 95th percentiles.

The system SHALL retain original values for display and audit. Winsorized values are used only for cross-sectional scoring.

### 2.2 V1 excludes business models requiring different valuation semantics

The generic V1 Funnel is for non-financial operating companies.

The following SHALL NOT be forced through the generic model:

- banks;
- insurers;
- diversified financial institutions whose debt is operational inventory/funding;
- REITs.

Reason: generic `net debt`, `enterprise value`, `FCF margin`, and operating-capital economics are not directly comparable for these structures.

V1 behavior:

```text
supported operating company -> score normally
financial / insurer / REIT  -> UNSUPPORTED_METHODOLOGY
```

They remain visible in universe metadata but are excluded from ranked discovery by default.

Future versions MAY add independent methodologies such as:

```text
Bank Funnel
Insurance Funnel
REIT / FFO Funnel
```

Those are explicitly outside this specification.

If the data provider exposes only sector and cannot identify REITs reliably, the entire Real Estate sector SHALL be excluded in V1 rather than silently applying an inappropriate methodology.

### 2.3 Cyclicality is handled with multi-period normalization

The Funnel SHALL NOT score valuation from TTM cash flow alone.

Each supported operating company requires up to five completed fiscal years of history plus current TTM where available.

Two cash-flow concepts SHALL coexist:

```text
FCF_TTM
NORMALIZED_FCF
```

Where:

```text
FCF = operating_cash_flow - capital_expenditures

NORMALIZED_FCF =
median(FCF_TTM, FCF_FY1, FCF_FY2, FCF_FY3)
using available non-null observations
```

A minimum of three observations is required for `NORMALIZED_FCF`.

The scored FCF yield SHALL use `NORMALIZED_FCF`, not `FCF_TTM`.

Cyclicality SHALL additionally be represented explicitly through:

- operating-margin stability;
- FCF-margin stability;
- negative-FCF frequency;
- peak-to-trough FCF behavior.

This does not claim to identify macroeconomic cycles perfectly. It prevents a single peak TTM observation from dominating the discovery score.

---

## 3. Universe and Entity Schema

### 3.1 Initial universe

V1 validation universe:

```text
S&P 500 constituents
```

The implementation SHALL remain provider-agnostic and SHALL NOT encode S&P 500-specific financial logic.

### 3.2 Entity metadata

Every observation set SHALL contain:

```text
ticker: str
security_id: str
issuer_id: str
company_name: str
currency: str
sector: str | null
industry_group: str | null
is_reit: bool | null
fiscal_year_end: str | null
data_as_of: date
provider: str
provider_identity: str | null
```

All monetary values within one company SHALL be normalized to one reporting currency before scoring.

Cross-currency valuation comparison is allowed only after the provider reports market data and fundamentals in internally coherent currency units. V1 SHALL NOT perform FX translation itself.

---

## 4. Raw Financial Input Schema

Diamond Funnel consumes structured data. It does not perform filing-native XBRL reconstruction.

For historical fields:

```text
TTM = trailing twelve months where semantically valid
FY1 = latest completed fiscal year
FY2 = one year before FY1
...
FY5 = five fiscal years back
```

Each observation SHALL retain:

```text
value
period_start | null
period_end
period_kind: duration | instant
currency | shares | ratio
source_provider
source_identity | null
```

### 4.1 Required raw metric families

The provider adapter SHOULD map the following raw families when available:

1. `revenue`
2. `operating_income`
3. `net_income`
4. `operating_cash_flow`
5. `capital_expenditures`
6. `cash_and_equivalents`
7. `marketable_securities`
8. `total_debt`
9. `total_equity`
10. `diluted_shares`
11. `shares_outstanding_latest`
12. `shares_outstanding_fy1_end`
13. `pretax_income`
14. `income_tax_expense`
15. `market_cap`
16. `enterprise_value_provider`
17. `price`

### 4.2 Exact accounting semantics

#### Revenue

```text
standard meaning:
total revenue / sales recognized for the reporting period
period kind:
duration
```

Do not mix gross transaction volume, bookings, ARR, or segment revenue with consolidated revenue.

#### Operating income

```text
standard meaning:
consolidated operating income / EBIT-like operating profit before interest and taxes
period kind:
duration
```

Provider EBITDA is not an acceptable substitute.

#### Net income

```text
standard meaning:
consolidated net income attributable to the reporting entity
period kind:
duration
```

Used for diagnostics, not as the primary valuation cash-flow input.

#### Operating cash flow

```text
standard meaning:
net cash provided by operating activities
period kind:
duration
working-capital treatment:
AFTER working-capital changes
```

Therefore Diamond Funnel SHALL NOT subtract working-capital changes again.

#### Capital expenditures

```text
standard meaning:
cash purchases of property, plant and equipment and capitalized operating fixed assets
period kind:
duration
sign convention:
positive outflow
```

If a provider returns capex as a negative cash-flow number, the adapter SHALL convert it to a positive outflow before storage.

Acquisition consideration is not capex.

#### Cash and equivalents

```text
standard meaning:
cash and cash equivalents
period kind:
instant
```

#### Marketable securities

```text
standard meaning:
liquid financial investments classified as current / readily marketable
period kind:
instant
```

This field MAY be null. It SHALL NOT be populated from long-term strategic investments unless the provider explicitly classifies them as liquid marketable securities.

#### Total debt

```text
standard meaning:
interest-bearing short-term + long-term borrowings
period kind:
instant
```

Accounts payable and operating liabilities are excluded.

#### Total equity

```text
standard meaning:
total shareholders' equity attributable to the reporting entity
period kind:
instant
```

#### Diluted shares and current share-count evidence

```text
diluted_shares:
weighted-average diluted shares for fiscal-period / per-share trend diagnostics

shares_outstanding_latest:
latest point-in-time common shares outstanding at data_as_of

shares_outstanding_fy1_end:
point-in-time common shares outstanding at the latest completed fiscal-year end
```

Weighted-average diluted shares and point-in-time shares are different economic objects and SHALL NOT silently replace one another.

The stable historical dilution metric remains:

```text
share_dilution_3y =
(diluted_shares_FY1 / diluted_shares_FY4)^(1/3) - 1
```

To prevent fiscal-year reporting lag from hiding a recent issuance, the Funnel additionally computes:

```text
recent_share_change =
shares_outstanding_latest / shares_outstanding_fy1_end - 1
```

`recent_share_change` is valid only when both point-in-time share counts are positive, use the same share class, and are expressed on a consistent split-adjusted basis.

This current-period overlay is a scoring feature and diagnostic; it does not replace `share_dilution_3y`.

#### Pretax income / income tax expense

Used only to derive an approximate effective tax rate for ROIC.

```text
effective_tax_rate =
income_tax_expense / pretax_income
```

Valid only when:

```text
pretax_income > 0
income_tax_expense >= 0
0 <= effective_tax_rate <= 0.50
```

If invalid, `effective_tax_rate = null`.

#### Market cap

```text
standard meaning:
equity market capitalization at data_as_of
period kind:
instant market observation
```

#### Provider enterprise value

Stored only for comparison / QA.

The Funnel's canonical screening EV SHALL be derived:

```text
NET_DEBT =
total_debt - cash_and_equivalents - marketable_securities

ENTERPRISE_VALUE =
market_cap + NET_DEBT
```

If marketable securities are null:

```text
ENTERPRISE_VALUE =
market_cap + total_debt - cash_and_equivalents
```

If provider EV differs from derived EV by more than 10%:

```text
EV_CONSISTENCY = WARN
```

The derived value remains the scored value.

#### Price

Latest supported market price corresponding to `data_as_of`.

Price is displayed and used for traceability; market cap is the primary price denominator for screening ratios.

---

## 5. The 15 Compressed Metrics

The public Funnel record SHALL expose exactly these 15 primary metrics.

### Raw / near-raw

1. `revenue_ttm`
2. `operating_income_ttm`
3. `operating_margin_ttm`
4. `operating_cash_flow_ttm`
5. `capex_ttm`
6. `fcf_ttm`
7. `fcf_margin_ttm`
8. `cash_and_marketable_securities`
9. `total_debt`
10. `net_debt`
11. `diluted_shares`
12. `share_dilution_3y`
13. `market_cap`
14. `enterprise_value`
15. `normalized_fcf_yield`

### Definitions

```text
operating_margin_ttm =
operating_income_ttm / revenue_ttm

fcf_ttm =
operating_cash_flow_ttm - capex_ttm

fcf_margin_ttm =
fcf_ttm / revenue_ttm

cash_and_marketable_securities =
cash_and_equivalents + coalesce(marketable_securities, 0)

net_debt =
total_debt - cash_and_marketable_securities

share_dilution_3y =
(diluted_shares_FY1 / diluted_shares_FY4)^(1/3) - 1
when both endpoints > 0

normalized_fcf_yield =
NORMALIZED_FCF / market_cap
```

The CLI MAY expose additional diagnostic features, but these 15 are the stable compressed public fundamentals for V1.

---

## 6. Derived Analytical Features

These are scoring features, not additional public primary metrics.

### 6.1 Growth

```text
revenue_cagr_3y =
(revenue_FY1 / revenue_FY4)^(1/3) - 1

revenue_cagr_5y =
(revenue_FY1 / revenue_FY5)^(1/4) - 1
```

Note: five fiscal observations contain four annual intervals.

CAGR is valid only when both endpoints are positive.

FCF CAGR SHALL NOT be calculated when either endpoint is non-positive.

Instead, the Funnel separates persistence from growth:

```text
fcf_positive_year_ratio =
count(FCF_FY1..FY5 > 0) / count(non-null FCF_FY1..FY5)
```

For GROWTH scoring, V1 SHALL NOT use percentage growth in absolute FCF because a near-zero base can create economically meaningless 100%+ growth rates.

It SHALL use change in FCF margin:

```text
fcf_margin_y =
FCF_y / revenue_y

fcf_margin_trend =
median(
    fcf_margin_FY1 - fcf_margin_FY2,
    fcf_margin_FY2 - fcf_margin_FY3,
    fcf_margin_FY3 - fcf_margin_FY4
)
```

Only adjacent pairs with:

```text
revenue > 0
non-null FCF
```

are eligible.

Minimum valid deltas: 2.

This converts FCF improvement into percentage-point economics relative to the revenue base and removes the small-denominator bias of raw FCF growth rates.

### 6.2 Approximate invested capital / ROIC

Screening invested capital:

```text
INVESTED_CAPITAL_PROXY =
total_equity
+ total_debt
- cash_and_equivalents
- coalesce(marketable_securities, 0)
```

Average capital:

```text
AVG_INVESTED_CAPITAL_PROXY =
(INVESTED_CAPITAL_PROXY_FY1 + INVESTED_CAPITAL_PROXY_FY2) / 2
```

NOPAT proxy:

```text
NOPAT_PROXY =
operating_income_FY1 * (1 - effective_tax_rate)
```

ROIC proxy:

```text
ROIC_PROXY =
NOPAT_PROXY / AVG_INVESTED_CAPITAL_PROXY
```

ROIC proxy is null when:

```text
effective_tax_rate is null
AVG_INVESTED_CAPITAL_PROXY <= 0
```

This is a discovery approximation only. Qhapaq One remains authoritative for invested-capital analysis.

### 6.3 Cash conversion

```text
cash_conversion =
NORMALIZED_FCF / median(operating_income_FY1..FY3)
```

Only valid when the operating-income median is positive.

### 6.4 Recent dilution overlay

```text
recent_share_change =
shares_outstanding_latest / shares_outstanding_fy1_end - 1
```

Only valid when:

```text
shares_outstanding_latest > 0
shares_outstanding_fy1_end > 0
same share class
consistent split-adjusted basis
```

Interpretation:

```text
recent_share_change > 0  -> recent net issuance / dilution signal
recent_share_change < 0  -> recent net repurchase signal
```

If:

```text
recent_share_change >= 0.02
```

emit:

```text
RECENT_DILUTION
```

The 2% threshold is a diagnostic boundary, not a scoring cutoff.

### 6.5 Leverage

```text
net_debt_to_operating_income =
net_debt / operating_income_ttm
```

If `operating_income_ttm <= 0`, the ratio is null.

Net cash (`net_debt < 0`) is valid and favorable, but SHALL NOT generate unbounded scores.

### 6.6 Operating-margin stability

For available FY1..FY5 operating margins:

```text
margin_median = median(margins)

margin_MAD =
median(abs(margin_i - margin_median))

margin_dispersion =
margin_MAD / max(abs(margin_median), 0.05)
```

Lower dispersion is better.

Minimum observations: 4.

### 6.7 FCF stability

For available FY1..FY5 FCF margins:

```text
fcf_margin_median = median(fcf_margins)

fcf_margin_MAD =
median(abs(fcf_margin_i - fcf_margin_median))

fcf_margin_dispersion =
fcf_margin_MAD / max(abs(fcf_margin_median), 0.05)

negative_fcf_ratio =
count(FCF <= 0) / count(non-null FCF)
```

Minimum observations for dispersion: 4.

### 6.8 Peak-TTM diagnostic

```text
peak_ttm_ratio =
FCF_TTM / max(abs(NORMALIZED_FCF), epsilon)
```

If:

```text
FCF_TTM > 0
NORMALIZED_FCF > 0
peak_ttm_ratio >= 1.75
```

emit:

```text
CYCLICAL_PEAK_RISK
```

This warning does not automatically exclude the company.

---

## 7. Percentile Engine

### 7.1 Direction

Each feature SHALL declare a direction:

```text
higher_is_better
lower_is_better
```

Example:

```text
ROIC_PROXY                 higher_is_better
normalized_fcf_yield       higher_is_better
revenue_cagr_5y            higher_is_better
share_dilution_3y          lower_is_better
net_debt_to_op_income      lower_is_better
margin_dispersion          lower_is_better
negative_fcf_ratio         lower_is_better
```

### 7.2 Winsorization

Within peer group:

```text
x_scored = clamp(x, P05, P95)
```

Original `x` remains unchanged in the record.

### 7.3 Percentile

For higher-is-better:

```text
percentile = empirical_percentile_rank(x_scored)
```

For lower-is-better:

```text
percentile = 1 - empirical_percentile_rank(x_scored)
```

Scores are represented as:

```text
0.0 <= score <= 100.0
```

Ties receive average rank.

---

## 8. Compression Scores

Diamond Funnel exposes four deterministic category scores:

```text
QUALITY
GROWTH
CAPITAL
PRICE
```

### 8.1 QUALITY

Inputs:

```text
35% ROIC_PROXY percentile
25% normalized FCF margin percentile
20% cash conversion percentile
10% operating-margin stability percentile
10% FCF stability percentile
```

Where:

```text
normalized FCF margin =
NORMALIZED_FCF / median(revenue_FY1..FY3)
```

Minimum validity:

```text
ROIC_PROXY OR cash_conversion must be present
and
at least 3 of the 5 inputs must be present
```

Missing optional components cause weights to be renormalized over available components.

### 8.2 GROWTH

Inputs:

```text
45% revenue CAGR 5Y percentile
25% revenue CAGR 3Y percentile
20% FCF-margin trend percentile
10% operating-margin trend percentile
```

Operating-margin trend:

```text
margin_trend =
operating_margin_FY1 - operating_margin_FY3
```

Minimum validity:

```text
revenue CAGR 3Y must be present
and
at least 2 inputs must be present
```

### 8.3 CAPITAL

Inputs:

```text
35% inverse net-debt / operating-income percentile
20% inverse share-dilution 3Y percentile
15% inverse recent-share-change percentile
20% ROIC_PROXY percentile
10% net-cash indicator percentile
```

Net-cash indicator:

```text
1 when net_debt < 0
0 otherwise
```

Within scoring it is converted to peer percentile like other features.

Minimum validity:

```text
share_dilution_3y must be present
and
at least 2 inputs must be present
```

`recent_share_change` is optional. If unavailable, its 15% weight is renormalized across the remaining valid CAPITAL inputs. If available, it prevents a material current-period issuance from remaining invisible until the next fiscal-year close.

### 8.4 PRICE

Inputs:

```text
60% normalized FCF yield percentile
40% EBIT / EV yield percentile
```

Where:

```text
EBIT_EV_YIELD =
operating_income_ttm / enterprise_value
```

Only valid if:

```text
enterprise_value > 0
operating_income_ttm > 0
```

Minimum validity:

```text
normalized_fcf_yield must be present
```

If normalized FCF is non-positive, normalized FCF yield remains numerically valid but is not treated as attractive merely because another valuation ratio is favorable.

---

## 9. Avoiding the "Perfect Combination" Bias

The Funnel SHALL NOT compute shortlist priority from one mandatory weighted average of all four categories.

Instead it computes three independent archetype scores.

### 9.1 COMPOUNDER

```text
COMPOUNDER =
0.45 * QUALITY
+ 0.35 * GROWTH
+ 0.20 * CAPITAL
```

Purpose:

```text
surface durable profitable growth
```

PRICE is displayed but is not required to be attractive.

### 9.2 QUALITY_VALUE

```text
QUALITY_VALUE =
0.40 * QUALITY
+ 0.35 * PRICE
+ 0.25 * CAPITAL
```

Purpose:

```text
surface economically strong companies whose cash economics look inexpensive relative to peers
```

### 9.3 INFLECTION

```text
INFLECTION =
0.35 * GROWTH
+ 0.25 * QUALITY
+ 0.20 * margin_trend_percentile
+ 0.20 * PRICE
```

Purpose:

```text
surface companies whose current economics are improving rather than already perfect
```

### 9.4 Research priority

```text
RESEARCH_PRIORITY =
max(COMPOUNDER, QUALITY_VALUE, INFLECTION)
```

The winning archetype is stored as:

```text
surfaced_by =
COMPOUNDER | QUALITY_VALUE | INFLECTION
```

This is a research-routing signal, not an investment recommendation.

---

## 10. Cyclicality Adjustment

No category score is directly multiplied by a hard cyclicality penalty.

Instead, the Funnel SHALL:

1. score PRICE using normalized rather than TTM FCF;
2. include stability in QUALITY;
3. emit explicit diagnostics.

Diagnostics:

```text
CYCLICAL_PEAK_RISK
FCF_VOLATILITY_HIGH
OPERATING_MARGIN_VOLATILITY_HIGH
NEGATIVE_FCF_HISTORY
RECENT_DILUTION
```

A company with excellent current yield but unstable historical economics can still surface, but its explanation SHALL expose why the result may be cyclical.

This preserves discovery optionality instead of silently discarding cyclicals.

---

## 11. Boundary Conditions

### 11.1 Nulls

Rules:

```text
never convert null to zero
never fabricate a missing metric
never forward-fill across fiscal years
```

Category scores use the minimum-validity requirements above.

If insufficient:

```text
score = null
reason = INSUFFICIENT_DATA
```

A company with `RESEARCH_PRIORITY = null` SHALL NOT appear in the default ranked shortlist.

### 11.2 Negative revenue

If:

```text
revenue <= 0
```

then revenue-derived margins and growth are invalid.

The security remains inspectable but is excluded from generic ranking.

### 11.3 Negative operating income

Do not calculate:

```text
net_debt_to_operating_income
EBIT_EV_YIELD
```

QUALITY/GROWTH may still exist if coverage rules permit.

Emit:

```text
OPERATING_LOSS
```

### 11.4 Negative FCF

Negative FCF is preserved.

Do not invert or take an absolute value to create a positive yield.

If normalized FCF <= 0:

```text
normalized_fcf_yield <= 0
```

and PRICE reflects its peer-relative economics normally.

### 11.5 CAGR with non-positive endpoints

CAGR SHALL be null when either endpoint <= 0.

No signed-root CAGR approximation is allowed.

### 11.6 Enterprise value <= 0

`EBIT_EV_YIELD = null`.

Negative EV is not interpreted as "infinitely cheap."

### 11.7 Extreme multiples / ratios

Ratios are not capped in stored output.

Only scoring inputs are winsorized P05/P95 within peer group.

Thus a temporary 1000x P/E-like observation cannot dominate the score, while the underlying extreme remains inspectable.

### 11.8 Share count inconsistency

If historical diluted-share methodology changes or series units are inconsistent:

```text
share_dilution_3y = null
SHARE_SERIES_INCONSISTENT
```

If current and FY1 point-in-time share counts use different share classes, split bases, or incompatible units:

```text
recent_share_change = null
CURRENT_SHARE_SERIES_INCONSISTENT
```

No interpolation.

### 11.9 Sparse peer groups

If eligible sector peer group:

```text
n >= 20 -> sector-relative percentiles
n < 20  -> eligible-universe percentiles
```

The score record SHALL store:

```text
peer_scope
peer_count
```

### 11.10 Stale market data

A provider adapter SHALL expose data observation dates.

Default V1 market-data freshness:

```text
price / market cap <= 3 trading days old
```

If stale:

```text
PRICE = null
MARKET_DATA_STALE
```

Fundamental categories may still be computed.

---

## 12. Output Contract

Per company:

```json
{
  "schema_version": "diamond-funnel-v1",
  "ticker": "MSFT",
  "data_as_of": "2026-09-20",
  "peer_scope": "Information Technology",
  "peer_count": 62,
  "metrics": {
    "revenue_ttm": 0,
    "operating_income_ttm": 0,
    "operating_margin_ttm": 0,
    "operating_cash_flow_ttm": 0,
    "capex_ttm": 0,
    "fcf_ttm": 0,
    "fcf_margin_ttm": 0,
    "cash_and_marketable_securities": 0,
    "total_debt": 0,
    "net_debt": 0,
    "diluted_shares": 0,
    "share_dilution_3y": 0,
    "market_cap": 0,
    "enterprise_value": 0,
    "normalized_fcf_yield": 0
  },
  "scores": {
    "quality": 0,
    "growth": 0,
    "capital": 0,
    "price": 0,
    "compounder": 0,
    "quality_value": 0,
    "inflection": 0,
    "research_priority": 0
  },
  "surfaced_by": "COMPOUNDER",
  "diagnostics": [],
  "coverage": {
    "quality": "READY",
    "growth": "READY",
    "capital": "READY",
    "price": "READY"
  }
}
```

Zeros above are placeholders illustrating shape, not default values. Production serialization SHALL emit null for unavailable values.

---

## 13. Explainability Contract

Every surfaced company SHALL produce:

1. the archetype that surfaced it;
2. the strongest positive contributors;
3. the strongest negative / caution contributors;
4. relevant diagnostics;
5. raw values and peer percentiles used.

Example:

```text
MSFT
RESEARCH PRIORITY 84.2
SURFACED BY COMPOUNDER

QUALITY 91
- ROIC proxy: 94th percentile
- normalized FCF margin: 89th percentile
- operating-margin stability: 83rd percentile

GROWTH 82
- revenue CAGR 5Y: 78th percentile
- operating-margin trend: 88th percentile

CAPITAL 90
- net cash / low leverage
- share count declining

PRICE 24
- normalized FCF yield below sector median

CAUTION
- valuation is demanding relative to sector

WHY IT SURFACED
Exceptional quality and durable growth outweighed weak relative cash-flow yield.
```

Generated prose must be derived from deterministic score contributions. It SHALL NOT invent causal explanations.

---

## 14. CLI UX

### 14.1 Screen

```bash
qhapaq screen
```

Default:

```text
universe = configured default universe
depth = 25
exclude unsupported methodologies
sort = research_priority descending
```

### 14.2 Explicit universe

```bash
qhapaq screen --universe sp500 --depth 50
```

### 14.3 Sector filter

```bash
qhapaq screen --sector "Information Technology" --depth 50
```

Provider aliases MAY allow:

```bash
qhapaq screen --sector tech
```

but serialized output SHALL use canonical sector names.

### 14.4 Archetype filter

```bash
qhapaq screen --archetype compounder --depth 25
qhapaq screen --archetype quality-value --depth 25
qhapaq screen --archetype inflection --depth 25
```

### 14.5 Point-in-time evaluation

```bash
qhapaq screen --as-of 2026-09-20
```

The command SHALL fail closed if the provider cannot provide a coherent point-in-time dataset required by the requested mode.

### 14.6 Machine-readable output

```bash
qhapaq screen --format json
qhapaq screen --format csv
```

JSON SHALL use the canonical `diamond-funnel-v1` contract.

### 14.7 Company inspection

```bash
qhapaq inspect MSFT
```

Displays:

```text
compressed fundamentals
category scores
archetype scores
peer percentiles
coverage
diagnostics
data provenance
```

### 14.8 Deep analysis handoff

```bash
qhapaq analyze MSFT
```

Remains Qhapaq One / deep analysis.

Diamond Funnel SHALL NOT silently invoke deep SEC verification during a broad screen.

---

## 15. Provider Boundary

Diamond Funnel SHALL depend on a provider-neutral interface.

Conceptual contract:

```python
class FundamentalDataProvider(Protocol):
    def universe(self, universe_id: str, as_of: date) -> tuple[SecurityRef, ...]: ...
    def fundamentals(
        self,
        securities: tuple[SecurityRef, ...],
        as_of: date,
        history_years: int = 5,
    ) -> tuple[FundamentalRecord, ...]: ...
```

Provider adapters are responsible for:

```text
field mapping
units
currency consistency
period identity
sign normalization
source metadata
```

The scoring engine is responsible for:

```text
derived metrics
boundary conditions
peer groups
percentiles
compression
archetype scoring
explainability
```

Provider-specific field names MUST NOT leak into scoring logic.

---

## 16. Cost Boundary

Discovery SHALL NOT automatically trigger:

- SEC filing-native downloads;
- filing XBRL relationship parsing;
- company-specific debt-security research;
- analyst-style document research;
- Qhapaq One reverse DCF.

Those belong downstream.

A screen operation should be able to process hundreds of companies from one structured provider batch.

---

## 17. Relationship to Existing Qhapaq Components

### Reuse

Diamond Funnel MAY reuse:

- company/security identity concepts;
- deterministic content identities;
- quality-state conventions;
- CLI infrastructure;
- rendering conventions where useful.

### Do not couple

Diamond Funnel SHALL NOT require:

- `SecCanonicalGate`;
- filing fallback;
- `AccountingSnapshot`;
- Qhapaq One market-quality profiles;
- canonical WACC;
- filing-native evidence.

The Funnel is intentionally lower-cost and lower-assurance.

---

## 18. Acceptance Criteria

### Data

- S&P 500-sized batch can be represented with the provider-neutral schema.
- All 15 compressed metrics have explicit definitions.
- OCF is explicitly after working-capital changes.
- Capex has one canonical positive-outflow sign.
- Nulls never become zeros.
- Provider EV cannot override derived screening EV silently.

### Financial logic

- Financials / insurers / REITs are not scored by the generic operating-company model.
- TTM FCF alone cannot determine scored FCF yield.
- Cyclical peak diagnostics are deterministic.
- Negative FCF and operating losses do not create mathematically favorable artifacts.
- CAGR is never fabricated from non-positive endpoints.
- Current-period share issuance can affect CAPITAL before the next fiscal-year close when compatible point-in-time share data exists.
- FCF growth scoring cannot be dominated by a microscopic absolute FCF base; GROWTH uses FCF-margin trend instead of raw FCF percentage growth.

### Scoring

- Percentiles are sector-relative when peer count >= 20.
- Scoring winsorizes inputs but preserves original values.
- QUALITY, GROWTH, CAPITAL, PRICE are deterministic.
- Shortlisting uses multiple archetypes, not a mandatory "perfect company" conjunction.
- `research_priority = max(archetype scores)`.

### Explainability

For every surfaced company, Qhapaq can show:

```text
what surfaced it
which raw metrics contributed
which peer percentiles were used
what cautions were detected
what data was missing
```

### Product boundary

- `qhapaq screen` does not invoke Qhapaq One automatically.
- `qhapaq inspect TICKER` explains Funnel output.
- `qhapaq analyze TICKER` remains the explicit deep-analysis transition.

---

## 19. Non-Goals

V1 does not attempt to:

- predict stock returns;
- issue BUY/HOLD/SELL recommendations;
- produce target prices;
- model banks;
- model insurers;
- model REITs;
- identify macroeconomic cycle phases;
- perform filing-native SEC normalization across the whole universe;
- acquire issuer-specific market debt;
- use machine learning for ranking;
- infer missing financial values.

---

## 20. Open Implementation Decisions

These are implementation choices, not unresolved product semantics:

1. Which structured data provider(s) satisfy the schema at acceptable cost.
2. Local cache format: SQLite, Parquet, or equivalent.
3. Exact provider adapter package boundaries.
4. Whether the first universe source is provider-native S&P 500 membership or a separate universe source.
5. Human-table rendering layout.

None of these changes the financial/scoring contract above.

---

## 21. Summary

Diamond Funnel is deliberately not Qhapaq One at scale.

Its design principle is:

```text
cheap data to discover
Qhapaq intelligence to prioritize
expensive evidence only to verify
```

The Funnel uses sector-relative robust scoring, historical normalization, and multiple research archetypes to avoid both mega-cap bias and the "perfect combination" trap.

The result is not an investment verdict. It is a deterministic, explainable answer to:

> Where should Qhapaq spend its next unit of research effort?

---

## 22. V0.1 Implementation Resolution Addendum

**Status:** Approved
**Scope:** Core offline + local canonical adapter + provider benchmark harness. No live FMP/Tiingo integration.

This addendum resolves the implementation ambiguities discovered during preflight and is normative for V0.1.

### 22.1 Provider-neutral comparative cohort

`FundamentalRecord` SHALL include a provider-normalized comparative key:

```text
peer_group_id: str
```

Rules:

- `peer_group_id` is required, trimmed, non-empty, and preserved verbatim for audit.
- The scoring engine SHALL NOT contain a GICS taxonomy or provider-specific sector aliases.
- A provider/local fixture may set `peer_group_id` equal to a canonical sector name, but this is an adapter decision.
- `sector` and `industry_group` remain descriptive metadata.
- The engine uses `peer_group_id` for primary peer formation.
- When the number of methodology-eligible records in that peer group is `< 20`, scoring falls back to the eligible full universe as already specified.
- A feature percentile additionally requires at least `8` finite, non-null observations after methodology and temporal eligibility filtering. Otherwise that feature percentile is null with `INSUFFICIENT_PEER_OBSERVATIONS`.

### 22.2 Explicit methodology identity

Provider normalization SHALL produce:

```text
methodology:
    OPERATING_COMPANY
    | UNSUPPORTED_FINANCIAL
    | UNSUPPORTED_INSURER
    | UNSUPPORTED_REIT
    | UNKNOWN
```

Only `OPERATING_COMPANY` is eligible for V0.1 generic scoring.

This prevents the scoring engine from inferring business-model semantics from provider-specific sector strings.

### 22.3 Temporal basis and granularity

`FundamentalRecord` SHALL include:

```text
fundamental_period_type: TTM
fundamental_period_end: date
market_age_trading_days: int | null
```

V0.1 accepts only `TTM` as the current-flow comparison basis. Historical FY1..FY5 observations remain available for derived history features.

Dataset-level rules:

```text
all records in one screen request:
    same data_as_of

every score-eligible record:
    fundamental_period_type == TTM
    fundamental_period_end <= data_as_of
    0 <= (data_as_of - fundamental_period_end).days <= 130
```

Within a resolved peer scope:

```text
period_end spread <= 45 calendar days:
    no temporal diagnostic

45 < spread <= 92 calendar days:
    scoring allowed
    emit PEER_PERIOD_DRIFT

period_end spread > 92 calendar days:
    peer scope is temporally incoherent
    percentile features for that scope are unavailable
    emit PEER_PERIOD_MISALIGNED
```

Rationale: a 45-day hard cutoff would discard legitimate off-calendar filers. V0.1 therefore treats 45 days as a warning boundary and one reporting cycle (~92 days) as the fail-closed boundary. The provider is responsible for constructing valid TTM observations; the engine independently enforces comparability instead of trusting the provider silently.

Market freshness remains:

```text
market_age_trading_days <= 3
```

If `market_age_trading_days` is null or > 3, `PRICE = null` and `MARKET_DATA_STALE` is emitted. The offline core does not invent an exchange holiday calendar.

### 22.4 Observation identity

Each raw observation SHALL include a fiscal slot:

```text
TTM | FY1 | FY2 | FY3 | FY4 | FY5 | LATEST
```

and retain the existing:

```text
period_start | null
period_end
period_kind: duration | instant
unit_kind: currency | shares | ratio
source_provider
source_identity | null
```

Share-count observations MAY additionally contain:

```text
share_class_id: str | null
adjustment_basis_id: str | null
```

`recent_share_change` is valid only when the two point-in-time share observations have equal non-null `share_class_id` and `adjustment_basis_id`. Otherwise the feature is null and `CURRENT_SHARE_SERIES_INCONSISTENT` is emitted.

Historical `share_dilution_3y` requires compatible diluted-share units and adjustment basis at FY1/FY4; otherwise it is null and `SHARE_SERIES_INCONSISTENT` is emitted.

### 22.5 Winsorization interpolation and percentile ties

Winsorization SHALL use NumPy's explicit linear quantile method:

```python
np.quantile(values, q, method="linear")
```

with `q=0.05` and `q=0.95`.

For `N=8`, the zero-based linear-quantile index for P95 is:

```text
h = (N - 1) * 0.95 = 6.65
```

This method is pinned by regression tests; no implicit library default is permitted.

Percentile ranks SHALL:

- operate on winsorized values;
- assign average rank to ties;
- map average rank `r` in a sample of `n > 1` to `(r - 1) / (n - 1) * 100`;
- invert lower-is-better features as `100 - percentile`;
- return null when fewer than 8 eligible finite observations exist.

### 22.6 V0.1 implementation boundary

V0.1 SHALL implement:

```text
pure core contracts
validation / normalization
derived metrics
peer formation
linear P05/P95 winsorization
deterministic percentiles
QUALITY / GROWTH / CAPITAL / PRICE
COMPOUNDER / QUALITY_VALUE / INFLECTION
RESEARCH_PRIORITY
deterministic diagnostics and explainability
local canonical JSON provider
offline provider-feasibility benchmark harness
screen / inspect / provider-benchmark CLI over local input
stable JSON + CSV output
```

V0.1 SHALL NOT implement:

```text
live FMP integration
live Tiingo integration
SQLite or Parquet persistence
network acquisition
bank scoring
insurer scoring
REIT scoring
portfolio optimization
machine-learning ranking
BUY/HOLD/SELL recommendations
price targets
automatic SEC deep-analysis invocation from screen
```

### 22.7 Worktree safety gate

The implementation bundle SHALL refuse to mutate an unrelated dirty worktree automatically.

The current preflight shows the SEC acquisition feature is still uncommitted. Therefore Diamond Funnel implementation is prepared independently and is applied only after the operator intentionally provides a suitable clean implementation branch/worktree or explicitly chooses to continue in the existing worktree after closing that feature.

Protected local paths remain outside Diamond Funnel staging and automation:

```text
.env.example
data/cache/sec/company_tickers.json
```
