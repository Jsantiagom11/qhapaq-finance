# NVDA deterministic financial-core audit

Correction date: 2026-09-09. The prior deterministic outputs are retained below
as historically invalid values; this update corrects their TTM period basis.

## TTM basis and source

TTM is FY2026 - H1 FY2026 + H1 FY2027. H1 FY2026 ended 2025-07-27, so the flow
window is 2025-07-28 through 2026-07-26 and the required opening balance sheet
is **2025-07-27**. Added primary evidence: NVIDIA Form 10-Q, filed 2025-08-27,
period ended 2025-07-27, SEC accession 0001045810-25-000209, SEC stable locator
`nvda-20250727.htm`, USD millions (except shares), checksum-gated local capsule.

## Operating NWC and invested capital (USD millions)

Included operating current assets: accounts receivable and inventory. Included
operating current liabilities: accounts payable and accrued/other current
liabilities. Excluded consistently: cash; marketable debt/equity securities;
debt; prepaids; goodwill; leases; deferred tax assets; other assets/liabilities.
Net operating assets are net PP&E plus acquired intangibles.

| Component | Opening 2025-07-27 | Closing 2026-07-26 |
|---|---:|---:|
| Accounts receivable | 27,808 | 63,059 |
| Inventory | 14,962 | 31,575 |
| Less AP | (9,064) | (15,059) |
| Less accrued/current liabilities | (15,193) | (26,960) |
| Operating NWC | 18,513 | 52,615 |
| Net PP&E + acquired intangibles | 9,896 | 17,283 |
| Invested capital | 28,409 | 69,898 |

ΔNWC TTM is $34,102m (cash use). Average invested capital is $49,153.5m.
Cash ($22,443m), marketable debt securities ($34,143m), and marketable equity
securities ($42,783m) are counted exactly once as $99,369m in the equity bridge;
debt is $33,366m.

## Golden correction record

| Metric | Old | New | Reason |
|---|---:|---:|---|
| Δ operating NWC | 23,910 | 34,102 | TTM-aligned endpoints replace January-to-July endpoints |
| FCFF | 134,437.78 | 124,245.78 | Correct TTM working-capital cash use |
| Average invested capital | 56,146 | 49,153.5 | Opening endpoint now matches TTM flow window |
| ROIC | 288.56% | 329.61% | Period-aligned numerator/denominator |
| ROIC–WACC | 278.10pp | 319.15pp | Period-aligned capital denominator |
| Bear/base/bull per share | 93.66 / 162.78 / 258.07 | 85.92 / 149.17 / 236.36 | Corrected FCFF and valuation-share proxy |
| Reverse DCF growth | 20.9394% | 22.4604% | Corrected FCFF and market EV |

The old 288.56% was primarily a period-basis artifact: TTM NOPAT was paired with
a six-month NWC change and six-month capital average. No ROIC cap or
normalization was applied; the corrected result follows the same narrow,
consistently applied capital classification.

## Share basis, bridge, and status

The old 24,100m was cover-page shares outstanding as of 2026-08-21, not diluted.
The replacement is 24,338m GAAP diluted weighted-average shares for the six
months ended 2026-07-26. It is accurately labeled a period-weighted
valuation-share proxy, not current fully diluted shares. At $230.36, market
equity is $5,606,501.68m and EV is $5,540,498.68m (= equity - 99,369 + 33,366).
The reverse-DCF forward round trip matches EV within 1e-9 relative tolerance.

The 18% operating tax rate remains an **ASSUMPTION**. QCOM is unchanged. The
corrected candidate is ready for independent audit.
