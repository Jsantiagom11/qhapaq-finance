# Value Research Engine v0.2

v0.1 uses FCFF discounted at WACC as its canonical valuation path: NOPAT plus D&A, less capex and change in NWC. Reported/reconstructed FCFF and every normalization adjustment remain visible as an audit bridge to normalized FCFF. Enterprise value is then bridged explicitly to equity with cash, debt, and only represented senior claims.

Cost of capital is an estimated WACC assembled from risk-free rate, ERP, beta, debt cost, tax, and market-value capital weights. It is not an investor-required return. `fcff_implied_discount_rate` is an IRR-style operating-enterprise discount-rate solve that equates modeled FCFF enterprise value to observed market enterprise value; it is explicitly not a shareholder expected-return forecast.

ROIC is NOPAT/invested capital. The engine reports reinvestment × ROIC alongside the scenario growth assumption as an economic-consistency diagnostic, not an artificial equality.

Each bear/base/bull scenario has its own explicit growth, terminal growth, and forecast horizon. Terminal value uses Gordon growth and is rejected when growth is at least WACC. A terminal-value share over 75% emits a warning because valuation becomes especially assumption-sensitive.

Reverse DCF holds the base model fixed and solves the explicit growth rate implied by market enterprise value within declared bounds. QCOM, VRTX, and CSCO are intentionally labelled deterministic example fixtures, not live facts: together they exercise cyclical/licensing, high-return biotech/product concentration, and mature recurring-cash/acquisition economics without ticker-specific valuation formulas.

## QCOM evidence case

`qhapaq research QCOM` is an evidence-backed, offline-replayable case as of
2026-09-08. It consumes `data/research/qcom/financial-evidence.json`, whose SEC
10-K and 10-Q references contain accession number, filing date, local immutable
artifact path, SHA-256, locator, extraction method, fiscal period and explicit
duration/instant semantics. The authoritative hierarchy is SEC filing/XBRL,
Qualcomm IR copy of that filing, then earnings release solely for reconciliation.
Finance sites are not accounting evidence.

Facts are always `FACT`; TTM and bridges are `DERIVED`; scenario, tax and market
inputs are `ASSUMPTION` or separately timestamped external observations. The
loader rejects a source filed after the research as-of date, checksum failures,
instant facts in duration arithmetic, and overlapping/non-comparable YTD TTM
inputs. QCOM TTM is explicitly `FY2025 - 9M FY2025 + 9M FY2026` ending
2026-06-28; it is never formed by adding overlapping YTD periods.

FCFF remains `EBIT × (1-tax) + D&A - capex - change in NWC`. QCOM uses total
filing-derived capex (no invented maintenance/growth split). Operating NWC is
accounts receivable plus inventory less trade payables and accrued operating
liabilities; cash and debt are excluded. The report exposes opening, closing and
change in this definition. Reported/reconstructed FCFF is retained before a
normalization ledger. The v0.2 ledger is zero: uncertain discretionary items are
not normalized away.

SBC remains included in reported EBIT and is already an operating-cash-flow
reconciliation add-back; it is not separately subtracted from FCFF. Potential
dilution is represented through period-end shares in the market-equity bridge,
not weighted-average EPS shares. NOPAT is EBIT after the explicit model tax-rate
assumption. Invested capital is average opening/closing operating NWC plus net
operating assets; it is a book convention and does not mix market values.

Cash and marketable securities are separately represented in the QCOM liquidity
bridge (cash $4,533m plus marketable securities $3,771m at 2026-06-28); they are
not silently collapsed into cash. Debt is short-term debt plus long-term debt
($2,489m + $12,781m), while other liabilities are not silently called debt.
The balance-sheet share observation (1,057m at 2026-06-28) is distinct from the
cover-page observation (1,050m at 2026-07-27), which is used for market equity.
Price is a frozen external observation dated 2026-09-04; ERP, beta,
risk-free rate and pre-tax debt cost are explicit configurable analyst assumptions,
not SEC facts. `qhapaq research QCOM --provenance` prints the core audit bridge.

VRTX and CSCO remain clearly-labelled illustrative fixtures. Current limitations:
no live-data collection, no multi-stage detailed forecast, no tax-loss modelling,
and no dynamic debt or payout schedule.
