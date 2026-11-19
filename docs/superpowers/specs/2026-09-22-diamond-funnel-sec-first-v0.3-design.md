# Diamond Funnel SEC-First v0.3

Status: Approved design.

## Objective
Make `qhapaq funnel --universe sp500 --depth 10` produce a real S&P 500 shortlist without paid FMP bulk/batch access.

## Architecture
S&P 500 universe -> ticker/CIK/sector -> SEC companyfacts -> Diamond FundamentalRecord -> batch market data -> existing Diamond engine -> Top N.

FMP remains optional enrichment.

## Invariants
- Do not change Diamond scoring.
- Do not run AnalysisOrchestrator across the universe.
- Missing evidence remains missing.
- No forward fill or invented zero values.
- Capex is a positive canonical outflow.
- Unsupported financials/insurers/REITs remain visible but unranked.
- Preserve .env.example.
- Preserve data/cache/sec/company_tickers.json.
- Preserve the existing stash.

## Cache
Use provider-specific checksum-verified caches for universe, SEC evidence, market data, and FMP.

## Acceptance
A real `qhapaq funnel --universe sp500 --depth 10` must return a ranked shortlist.
Ruff, mypy, Diamond tests and full pytest must pass.
Cache replay must reduce network acquisition.
FMP must not be required for the broad screen.
`qhapaq analyze TICKER` remains unchanged.
