# Frozen ECB euro foreign-exchange reference rates

This directory contains an exact, byte-frozen response from the European Central Bank Data Portal
API. **Source: ECB statistics.**

## Source and acquisition

- Dataset: ECB exchange-rate reference rates (`EXR`), daily (`D`), reference-rate type `SP00`,
  average suffix `A`.
- Requested currencies: USD, GBP, JPY, and CHF with EUR as the denominator/base currency.
- Requested window: 2015-01-01 through 2026-08-31.
- Observed window: 2015-01-02 through 2026-08-31.
- Acquisition date: 2026-09-01 (`America/Lima`).
- Exact URL:
  `https://data-api.ecb.europa.eu/service/data/EXR/D.USD+GBP+JPY+CHF.EUR.SP00.A?startPeriod=2015-01-01&endPeriod=2026-08-31&format=csvdata`
- Reuse policy: [ECB policy on the use of ECB statistics](https://www.ecb.europa.eu/stats/ecb_statistics/governance_and_quality_framework/html/usage_policy.en.html).

The response body was saved without rewriting, normalizing, sorting, or reserializing it. The
quote convention is units of the named currency per one euro: for example,
`D.USD.EUR.SP00.A = 1.10` means EUR 1 equals USD 1.10.

## Point-in-time and verification semantics

The repository snapshot remains byte-frozen even if the ECB later revises its published history.
The manifest distinguishes the requested window from the actual observation window, identifies
all four series, and records the artifact byte count and SHA-256. The loader verifies those facts
before parsing and defaults its effective `as_of` to the validated final observation date rather
than the wall clock.

From the repository root, independently verify the raw artifact with:

```bash
sha256sum data/frozen/ecb/exr_daily_eur_reference_rates_2015-01-01_2026-08-31.csv
```

Expected SHA-256:
`9233e2547b72171b8b007e1056e09482e360a765b843330532b2a0e9a05a199e`.
The adjacent deterministic JSON manifest is deliberately not self-checksummed; its checksum is
recorded separately in repository execution evidence.
