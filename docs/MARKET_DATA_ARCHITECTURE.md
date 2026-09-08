# Market data architecture

Status: v0.1 implementation contract.

Qhapaq Finance separates information by **evidence speed** instead of pretending every input has the
same lifetime.

```text
FROZEN evidence                    SNAPSHOT observation                  LIVE query
10-K / 10-Q / earnings release     price + timestamp + provider         provider request now
checksum-gated                     serializable to deterministic JSON   never silently becomes evidence
        \                                  |                              /
         +---------- company research -----+----- expectations engine ----+
```

## Three data speeds

| Layer | Purpose | Mutation model | Typical lifetime |
| --- | --- | --- | --- |
| `FROZEN` | Auditable company evidence | immutable/checksum-gated | filing or evidence cycle |
| `SNAPSHOT` | Reproducible market observation | append/replace intentionally | minutes to days |
| `LIVE` | Best available provider observation now | ephemeral until frozen | seconds to minutes |

A live quote is **not** a filing fact. A frozen filing is **not** a current quote. Consumers must keep
those semantics visible.

## Time semantics

Every market snapshot records both:

- `observed_at`: when the market observation actually occurred.
- `retrieved_at`: when Qhapaq obtained it.

Freshness is computed from `observed_at`, never from download time. A quote downloaded today can still
be stale if the last actual observation came from an earlier session.

Freshness thresholds are caller-owned. Intraday monitoring may use five minutes; a weekend valuation
may intentionally accept the latest completed session with a much wider threshold. Qhapaq reports
`fresh`, `stale`, or `future`; it does not silently substitute a different observation.

## Provider isolation

The expectations engine accepts numerical inputs and does not depend on Yahoo, IBKR, Polygon, or any
other provider. `yfinance` is only the first optional adapter. Replacing or adding a provider should
not change reverse-DCF mathematics or frozen research records.

## Reverse DCF semantics

`qhapaq reverse-dcf` currently solves a constant explicit-period growth rate for an **equity FCF**
proxy against observed equity value. It must not mix FCFF with market capitalization or equity FCF
with enterprise value. Assumptions remain explicit: starting FCF, discount rate, terminal growth, and
explicit horizon.

The output is an expectation implied by the supplied valuation inputs, not a price target or return
forecast.

## CLI examples

Fetch the latest observable NVDA quote and freeze it:

```bash
qhapaq market NVDA --max-age-minutes 30 --output data/snapshots/nvda-latest.json
```

Replay the same observation without network access:

```bash
qhapaq market --snapshot data/snapshots/nvda-latest.json --max-age-minutes 2160
```

Solve an NVDA-like reverse DCF independently of the quote provider:

```bash
qhapaq reverse-dcf \
  --equity-value 5.55e12 \
  --starting-fcf 1.3997e11 \
  --discount-rate 0.09 \
  --terminal-growth 0.03 \
  --years 10
```

## Next bounded increment

After this contract passes CI and review, the next increment may compose a market snapshot with a
company research record in the HTML report. That composition must retain separate timestamps and
provenance and must visibly identify stale market observations. Provider redundancy, streaming,
alerts, and automated trading remain separate capabilities.
