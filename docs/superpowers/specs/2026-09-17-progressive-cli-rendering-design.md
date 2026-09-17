# Progressive CLI Rendering Design

## Purpose

Make `qhapaq analyze TICKER` useful to a human by default without changing the canonical analysis contract or financial semantics.

The CLI currently emits the full canonical JSON artifact for every analysis request. That behavior is correct for machines but too verbose and diagnostic for routine analyst use.

The new interface separates human presentation from machine serialization while preserving one upstream source of truth.

## Product contract

`AnalysisResult` remains the only authoritative analysis result for this command.

Renderers may select, label, order, format, wrap, and color existing values. They must not recalculate finance, reinterpret statuses, synthesize new financial values, or introduce a second analytical model.

The public modes are:

```text
qhapaq analyze TICKER
    Executive human view

qhapaq analyze TICKER --detail
    Expanded analyst human view

qhapaq analyze TICKER --json
    Canonical machine artifact

qhapaq analyze TICKER --plain
    Executive human view using plain ASCII and no ANSI color

qhapaq analyze TICKER --detail --plain
    Detailed human view using plain ASCII and no ANSI color
```

`--json` is mutually exclusive with `--detail` and `--plain`. JSON output remains the stable canonical serialization of `AnalysisResult.to_dict()` with no presentation text mixed into stdout.

## Default executive view

The default view is optimized for fast terminal scanning and should normally fit in roughly 20-30 lines when the analysis is incomplete.

It uses restrained presentation:

- minimal Unicode separators and status symbols;
- simple two-column key/value rows rather than decorative boxes;
- semantic color only;
- no animations, spinners, or full-screen TUI behavior;
- no new rendering dependency unless the standard library proves insufficient.

For `EVIDENCE_REQUIRED`, `BLOCKED`, or `UNSUPPORTED_TICKER`, show only information that helps the user understand what happened and what must happen next.

Example shape:

```text
QHAPAQ - JPMorgan Chase & Co. - JPM
----------------------------------

STATUS        EVIDENCE REQUIRED
CIK           0000019617
RESOLUTION    verified

EVIDENCE
  x Company facts       Missing
  x SEC submissions     Missing
  x Latest 10-K         Missing
  x Latest 10-Q         Missing

BOTTOM LINE
JPM was resolved authoritatively, but canonical financial evidence is not
available yet, so Qhapaq cannot continue to a financial analysis.

NEXT
Acquire and verify the missing SEC evidence.
```

Unicode mode may use restrained equivalents such as `─`, `✓`, `⚠`, and `✗`.

## Completed executive view

When `AnalysisResult.status == COMPLETED`, the executive renderer projects the existing `CanonicalResearchResult` into these sections when the corresponding data exists:

1. Identity and as-of date.
2. Financial snapshot.
3. Capital efficiency.
4. Cost of capital.
5. Market comparison and reverse DCF expectations.
6. Sensitivity / scenario summary.
7. Bottom line.
8. Evidence/readiness summary.

The renderer must use existing canonical values such as reconstructed/normalized FCFF, NOPAT, ROIC, WACC, ROIC-WACC spread, market price, scenario outputs, implied growth, expectation gap, readiness, and provenance.

If a desired display item is not represented in `AnalysisResult` or `CanonicalResearchResult`, omit it. Do not derive a replacement in the renderer.

The bottom line is deterministic status-oriented prose assembled from existing state and facts. It must not emit BUY/HOLD/SELL language, price targets, or investment recommendations.

## Detailed analyst view

`--detail` uses the same source result and the same presentation vocabulary, but expands the projection to include:

- analysis stage states and reasons;
- full evidence-plan item states;
- financial evidence/readiness details;
- valuation scenarios and warnings;
- market provenance;
- reverse-valuation fields;
- canonical content identity where useful for auditability.

It remains a human report, not pretty-printed JSON.

## JSON mode

`--json` preserves the current machine-oriented behavior:

```python
canonical_json(result.to_dict())
```

No ANSI escapes, headings, explanatory prose, or stderr diagnostics may contaminate stdout in JSON mode.

This mode is the stable integration surface for tests, scripts, agents, and future renderers.

## Plain mode and terminal compatibility

`--plain` disables all ANSI color and replaces Unicode status/separator glyphs with ASCII equivalents.

Human rendering should also suppress ANSI color automatically when either condition is true:

- stdout is not a TTY;
- environment variable `NO_COLOR` is present.

Unicode is allowed by default for the human view, but the semantic structure must not depend on glyphs alone. Text labels such as `COMPLETED`, `EVIDENCE REQUIRED`, `MISSING`, and `BLOCKED` remain present.

Human output must remain useful when copied into logs, issues, or chat.

## Rendering architecture

Introduce a presentation-only module, preferably `src/qhapaq_finance/analysis_render.py`.

The boundary is:

```text
AnalysisOrchestrator.analyze(ticker)
            |
            v
      AnalysisResult
       /     |      \
      /      |       \
Executive  Detail   JSON serializer
Renderer   Renderer
```

The renderer consumes domain objects and returns text. It does not perform filesystem reads, network access, company resolution, acquisition, canonicalization, accounting, capital-cost calculation, or valuation.

`cli.py` owns argument parsing and selecting the requested renderer only.

## Proposed renderer interface

Keep the interface small and testable. A suitable shape is:

```python
@dataclass(frozen=True)
class AnalysisRenderOptions:
    detail: bool = False
    plain: bool = False
    color: bool = False
    width: int = 88


def render_analysis(result: AnalysisResult, options: AnalysisRenderOptions) -> str:
    ...
```

Exact helper decomposition may follow repository conventions, but rendering must remain pure for a supplied result/options pair.

CLI detection of TTY, `NO_COLOR`, and terminal width occurs outside the financial engine. Tests should pass explicit options rather than depend on the developer terminal.

## Width and wrapping

Use terminal width only for presentation. A stable fallback width of 88 columns is sufficient.

Do not create horizontally scrolling wide tables. Long explanatory text wraps within the available width. Key/value rows should degrade gracefully in narrow terminals.

Tests use explicit fixed widths to keep snapshots deterministic.

## Status-specific behavior

### COMPLETED

Show executive financial analysis and evidence/readiness summary. `--detail` exposes the deeper canonical projection.

### EVIDENCE_REQUIRED

Show authoritative identity when available, missing/blocked critical evidence, the blocked stages, a concise bottom line, and the evidence acquisition/verification next action.

Do not print empty valuation sections.

### BLOCKED

Show identity if known, the blocking stage/reason, and a concise operational next action. Do not reinterpret an infrastructure failure as unsupported or missing evidence.

### UNSUPPORTED_TICKER

Show normalized ticker, `UNSUPPORTED TICKER`, and the authoritative resolution reason available in the plan. Do not display financial sections.

## Color semantics

Color is optional enhancement only and must never carry unique information.

If enabled:

- `COMPLETED`: success color;
- `EVIDENCE_REQUIRED`: warning color;
- `BLOCKED`: error color;
- `UNSUPPORTED_TICKER`: neutral/error emphasis;
- verified/ready evidence: success color;
- missing/blocked evidence: warning/error color.

No arbitrary decorative palette.

## Testing contract

Add focused renderer/CLI tests covering at least:

- `EVIDENCE_REQUIRED` executive output for a resolved arbitrary ticker-shaped result;
- `COMPLETED` executive projection from an existing canonical result fixture;
- `--detail` includes deeper evidence/provenance fields absent from default output;
- `--json` remains valid canonical JSON and preserves the current schema;
- `--plain` contains no ANSI escapes and no Unicode-only structural requirement;
- non-TTY or `NO_COLOR` suppresses ANSI color;
- renderer output is deterministic for the same `AnalysisResult` and explicit options;
- no financial calculation functions are invoked by renderer tests;
- existing sentinel/status and financial tests remain unchanged and green.

Prefer semantic assertions over brittle whole-screen snapshots, with small golden text fixtures only where they improve regression protection.

## Non-goals

This increment does not:

- enable automatic SEC acquisition;
- change company-resolution semantics;
- change `AnalysisResult` status definitions;
- change canonicalization, accounting, capital cost, valuation, or reverse-DCF logic;
- build HTML/PDF output;
- build a full-screen TUI;
- add recommendations, BUY/HOLD/SELL, or target prices;
- redesign Qhapaq One.

Automatic evidence acquisition for arbitrary tickers remains a separate subsequent closure.

## Acceptance

The change is accepted when:

```text
qhapaq analyze JPM
```

prints a concise human executive view rather than raw JSON;

```text
qhapaq analyze JPM --detail
```

prints an expanded analyst-oriented human view;

```text
qhapaq analyze JPM --plain
```

prints robust ASCII/no-color output; and

```text
qhapaq analyze JPM --json
```

emits only the canonical machine artifact.

All repository quality gates and Python 3.10/3.12 CI remain green, and the renderers demonstrably project existing result data without recalculating finance.
