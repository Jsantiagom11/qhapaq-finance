# Progressive CLI Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `qhapaq analyze TICKER` human-readable by default while preserving `AnalysisResult` as the single source of truth and retaining canonical JSON behind `--json`.

**Architecture:** Add one pure presentation module that consumes `AnalysisResult` plus explicit render options and returns text. Keep all terminal-environment detection in `cli.py`; keep financial computation, status semantics, company resolution, evidence planning, and canonical JSON serialization unchanged.

**Tech Stack:** Python 3.10-3.12, standard library only (`dataclasses`, `shutil`, `textwrap`, ANSI escape sequences), argparse, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-09-17-progressive-cli-rendering-design.md`

## Global Constraints

- `AnalysisResult` remains the only authoritative result for `qhapaq analyze`.
- Renderers may format existing values but must not recalculate finance or create new financial semantics.
- `CompanyResolver.resolve()` and `AnalysisOrchestrator.plan()` remain offline-only.
- `AnalysisOrchestrator.analyze()` keeps the bounded authoritative-refresh contract from `docs/engineering/qhapaq-analysis-resolution-contract.md`.
- No ticker-specific production branches.
- No automatic SEC evidence acquisition in this increment.
- No new runtime dependency unless strictly necessary; standard library is sufficient for this plan.
- `--json` output remains exactly the canonical serialization of `AnalysisResult.to_dict()` plus the existing trailing newline behavior.
- `--json` is mutually exclusive with `--detail` and `--plain`.
- `--plain` disables ANSI color and Unicode presentation glyphs.
- Human color is also disabled when stdout is not a TTY or `NO_COLOR` is present.
- Python 3.10 and 3.12 CI must remain green.

---

### Task 1: Add the pure renderer and incomplete-state executive views

**Files:**
- Create: `src/qhapaq_finance/analysis_render.py`
- Create: `tests/test_analysis_render.py`

**Interfaces:**
- Consumes: `qhapaq_finance.analysis.AnalysisResult`, `AnalysisStatus`, `AnalysisStageState`; `EvidencePlan`, `EvidenceState`.
- Produces:

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

The returned string must end with exactly one newline.

- [ ] **Step 1: Write focused failing tests for `EVIDENCE_REQUIRED`, `BLOCKED`, and `UNSUPPORTED_TICKER`**

Create deterministic test builders in `tests/test_analysis_render.py` rather than invoking network or filesystem behavior. Build `AnalysisResult` objects directly from the public dataclasses.

Representative assertions:

```python
def test_evidence_required_executive_view_is_human_and_omits_empty_valuation() -> None:
    result = evidence_required_result()

    text = render_analysis(result, AnalysisRenderOptions(plain=True, width=72))

    assert "QHAPAQ - JPMorgan Chase & Co. - JPM" in text
    assert "STATUS" in text
    assert "EVIDENCE REQUIRED" in text
    assert "Company facts" in text
    assert "SEC submissions" in text
    assert "BOTTOM LINE" in text
    assert "NEXT" in text
    assert "VALUATION" not in text
    assert '"schema_version"' not in text
    assert "\x1b[" not in text


def test_blocked_view_preserves_blocked_semantics() -> None:
    text = render_analysis(blocked_result(), AnalysisRenderOptions(plain=True))
    assert "BLOCKED" in text
    assert "authoritative company resolution could not complete" in text
    assert "UNSUPPORTED TICKER" not in text


def test_unsupported_ticker_view_does_not_show_financial_sections() -> None:
    text = render_analysis(unsupported_result(), AnalysisRenderOptions(plain=True))
    assert "UNSUPPORTED TICKER" in text
    assert "ticker is absent from the authoritative SEC company reference" in text
    assert "FINANCIAL" not in text
    assert "VALUATION" not in text
```

Use an `EvidencePlan` with four critical `EvidenceItem`s matching the generic SEC requirement shape: `company-facts`, `submissions`, `latest-10k`, `latest-10q`, all `MISSING`.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```bash
uv run --no-sync pytest -q tests/test_analysis_render.py
```

Expected: collection/import failure because `qhapaq_finance.analysis_render` does not exist.

- [ ] **Step 3: Implement the renderer shell and presentation primitives**

Create `analysis_render.py` with no imports from valuation, accounting, canonicalization, market acquisition, SEC clients, or filesystem modules.

Minimum structure:

```python
from __future__ import annotations

from dataclasses import dataclass
from textwrap import wrap

from .analysis import AnalysisResult, AnalysisStatus


@dataclass(frozen=True)
class AnalysisRenderOptions:
    detail: bool = False
    plain: bool = False
    color: bool = False
    width: int = 88


def render_analysis(result: AnalysisResult, options: AnalysisRenderOptions) -> str:
    width = max(48, options.width)
    lines = _render_header(result, options, width)
    if result.status is AnalysisStatus.COMPLETED:
        lines.extend(_render_completed(result, options, width))
    elif result.status is AnalysisStatus.EVIDENCE_REQUIRED:
        lines.extend(_render_evidence_required(result, options, width))
    elif result.status is AnalysisStatus.BLOCKED:
        lines.extend(_render_blocked(result, options, width))
    elif result.status is AnalysisStatus.UNSUPPORTED_TICKER:
        lines.extend(_render_unsupported(result, options, width))
    else:
        lines.extend(_render_blocked(result, options, width))
    return "\n".join(lines).rstrip() + "\n"
```

Add small private helpers for:

- human status labels (`EVIDENCE_REQUIRED` -> `EVIDENCE REQUIRED`);
- header and separators;
- aligned key/value rows;
- wrapped prose using `textwrap.wrap`;
- evidence display labels derived from `EvidenceRequirement.identifier`/`artifact_kind`;
- ASCII vs Unicode glyph selection;
- optional ANSI status coloring.

Use restrained ANSI codes only when `options.color` is true. `options.plain` must suppress both ANSI and Unicode even if `color=True` was passed accidentally.

Do not derive financial values in these helpers.

- [ ] **Step 4: Implement incomplete-state content using only existing result fields**

For `EVIDENCE_REQUIRED`:

- header from `plan.identity.display_name` and ticker;
- status, CIK, resolution text;
- only critical evidence items that are not ready;
- bottom line based on the existing status and plan reason;
- `NEXT` text: `Acquire and verify the missing SEC evidence.` when critical evidence is missing/stale/blocked, otherwise surface the blocking plan reason without inventing a new cause.

For `BLOCKED`:

- show identity if available;
- show the first meaningful blocking reason from plan stages;
- bottom line must explicitly preserve `BLOCKED` semantics;
- no evidence-required or unsupported reinterpretation.

For `UNSUPPORTED_TICKER`:

- show normalized ticker and the authoritative negative reason already stored in the plan;
- omit all financial sections.

- [ ] **Step 5: Run focused tests until GREEN**

```bash
uv run --no-sync pytest -q tests/test_analysis_render.py
uv run --no-sync ruff check src/qhapaq_finance/analysis_render.py tests/test_analysis_render.py
uv run --no-sync mypy --no-incremental src/qhapaq_finance/analysis_render.py
```

- [ ] **Step 6: Commit the pure incomplete-state renderer**

```bash
git add src/qhapaq_finance/analysis_render.py tests/test_analysis_render.py
git commit -m "feat(cli): add human analysis renderer"
```

---

### Task 2: Add completed executive and detailed analyst projections

**Files:**
- Modify: `src/qhapaq_finance/analysis_render.py`
- Modify: `tests/test_analysis_render.py`

**Interfaces:**
- Consumes: `AnalysisResult.canonical_result: CanonicalResearchResult | None`.
- Produces: the same `render_analysis(...) -> str` interface; no new public domain types.

- [ ] **Step 1: Add failing tests using existing deterministic QCOM/AAPL canonical results**

Use `AnalysisOrchestrator(ROOT).analyze("QCOM")` for an existing `COMPLETED` result; do not reconstruct financial numbers in tests.

Representative assertions:

```python
def test_completed_executive_view_projects_canonical_values() -> None:
    result = AnalysisOrchestrator(ROOT).analyze("QCOM")
    canonical = result.canonical_result
    assert canonical is not None

    text = render_analysis(result, AnalysisRenderOptions(plain=True, width=88))

    assert "COMPLETED" in text
    assert "FINANCIAL SNAPSHOT" in text
    assert "CAPITAL EFFICIENCY" in text
    assert "MARKET EXPECTATIONS" in text
    assert "BOTTOM LINE" in text
    assert f"{canonical.valuation['wacc']:.2%}" in text
    assert f"{canonical.valuation['roic']:.2%}" in text
    assert f"{canonical.market_comparison['price']:,.2f}" in text
    assert canonical.content_identity not in text


def test_detail_adds_provenance_scenarios_and_content_identity() -> None:
    result = AnalysisOrchestrator(ROOT).analyze("QCOM")
    canonical = result.canonical_result
    assert canonical is not None

    executive = render_analysis(result, AnalysisRenderOptions(plain=True))
    detail = render_analysis(result, AnalysisRenderOptions(detail=True, plain=True))

    assert "ANALYSIS STAGES" not in executive
    assert "ANALYSIS STAGES" in detail
    assert "VALUATION SCENARIOS" in detail
    assert "MARKET PROVENANCE" in detail
    assert canonical.content_identity in detail
```

Add a determinism assertion:

```python
assert render_analysis(result, options) == render_analysis(result, options)
```

- [ ] **Step 2: Run the new tests and confirm RED for missing completed/detail sections**

```bash
uv run --no-sync pytest -q tests/test_analysis_render.py -k "completed or detail"
```

- [ ] **Step 3: Implement the completed executive projection**

Read values only from `CanonicalResearchResult`:

- identity: `issuer`, `security`, `research_as_of`;
- financial snapshot: `valuation.reconstructed_fcff`, `normalized_fcff`, `nopat`;
- capital efficiency: `valuation.roic`, `valuation.wacc`, `valuation.roic_minus_wacc`, `valuation.fcff_yield`;
- market expectations: `market_comparison.price`, `market_comparison.fcff_implied_discount_rate`, `reverse_valuation.implied_growth`, `reverse_valuation.expectation_growth_gap`;
- scenario summary: project existing scenario dictionaries; do not recompute enterprise/equity/intrinsic values;
- evidence/readiness: project `financial_evidence` and `readiness` fields already present.

Formatting helpers may convert existing decimal values to percentages and existing numeric values to display strings. Formatting is presentation, not financial derivation.

Bottom line must be deterministic and descriptive. Safe shape:

```text
Qhapaq completed the canonical analysis from the currently verified evidence.
Review the market-expectations and scenario sections together with evidence readiness.
```

Do not create BUY/HOLD/SELL language, target prices, or a ranking.

- [ ] **Step 4: Implement `--detail` projection semantics inside the pure renderer**

When `options.detail` is true, append:

- `ANALYSIS STAGES`: acquisition/evidence/research/valuation/publishing state + existing reason;
- `EVIDENCE DETAIL`: every evidence-plan item with provider, identifier, state, reason;
- `VALUATION SCENARIOS`: existing scenario keys/values and warning strings;
- `READINESS`: existing readiness entries;
- `MARKET PROVENANCE`: fields from `market_provenance.to_dict()`;
- `AUDIT`: research identity and canonical `content_identity`.

Do not dump nested dicts with `repr`; format them as readable key/value rows or wrapped lines.

- [ ] **Step 5: Verify focused renderer tests and static gates**

```bash
uv run --no-sync pytest -q tests/test_analysis_render.py
uv run --no-sync ruff format --check src/qhapaq_finance/analysis_render.py tests/test_analysis_render.py
uv run --no-sync ruff check src/qhapaq_finance/analysis_render.py tests/test_analysis_render.py
uv run --no-sync mypy --no-incremental src/qhapaq_finance/analysis_render.py
```

- [ ] **Step 6: Commit completed/detail rendering**

```bash
git add src/qhapaq_finance/analysis_render.py tests/test_analysis_render.py
git commit -m "feat(cli): render completed analysis views"
```

---

### Task 3: Wire progressive modes into `qhapaq analyze`

**Files:**
- Modify: `src/qhapaq_finance/cli.py`
- Modify: `tests/test_analysis.py`

**Interfaces:**
- Consumes: `AnalysisRenderOptions`, `render_analysis` from `analysis_render.py`.
- Preserves: `AnalysisOrchestrator(...).analyze(ticker)` invocation exactly once per CLI request.
- Public CLI:

```text
qhapaq analyze TICKER
qhapaq analyze TICKER --detail
qhapaq analyze TICKER --plain
qhapaq analyze TICKER --detail --plain
qhapaq analyze TICKER --json
```

- [ ] **Step 1: Replace the old JSON-by-default CLI test with failing progressive-mode tests**

Update the existing `test_analyze_cli_is_a_thin_structured_orchestration_entrypoint` contract rather than keeping the old default behavior.

Add tests like:

```python
def test_analyze_cli_defaults_to_human_view(capsys: object) -> None:
    cli.main(["analyze", "QCOM", "--repository-root", str(ROOT), "--plain"])
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "QHAPAQ" in output
    assert "COMPLETED" in output
    assert '"schema_version"' not in output


def test_analyze_cli_json_preserves_canonical_machine_artifact(capsys: object) -> None:
    cli.main(["analyze", "QCOM", "--repository-root", str(ROOT), "--json"])
    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["status"] == "COMPLETED"
    assert payload["plan"]["identity"]["ticker"] == "QCOM"
    assert payload["canonical_result"]["security"]["ticker"] == "QCOM"


def test_analyze_cli_rejects_json_with_human_flags() -> None:
    with pytest.raises(SystemExit):
        cli.main(["analyze", "QCOM", "--json", "--detail"])
    with pytest.raises(SystemExit):
        cli.main(["analyze", "QCOM", "--json", "--plain"])
```

Also add tests for environment selection by monkeypatching `sys.stdout.isatty`, `NO_COLOR`, and `shutil.get_terminal_size` rather than depending on the test runner terminal.

- [ ] **Step 2: Run focused CLI tests and confirm RED**

```bash
uv run --no-sync pytest -q tests/test_analysis.py -k "analyze_cli"
```

Expected: default output is still JSON and flags do not exist.

- [ ] **Step 3: Add CLI flags and mutual exclusion**

In `_analyze`, use an argparse mutually exclusive group for JSON vs human-mode-only flags:

```python
human_or_json = parser.add_mutually_exclusive_group()
human_or_json.add_argument("--json", action="store_true")
human_or_json.add_argument("--detail", action="store_true")
parser.add_argument("--plain", action="store_true")
```

Because the spec also forbids `--json --plain`, perform an explicit post-parse check:

```python
if args.json and args.plain:
    parser.error("--json cannot be combined with --plain")
```

`--detail --plain` remains valid.

- [ ] **Step 4: Add terminal presentation option detection in `cli.py` only**

Import `shutil` and renderer symbols. Build options after the analysis completes:

```python
width = shutil.get_terminal_size(fallback=(88, 24)).columns
color = (
    not args.plain
    and sys.stdout.isatty()
    and "NO_COLOR" not in os.environ
)
options = AnalysisRenderOptions(
    detail=args.detail,
    plain=args.plain,
    color=color,
    width=width,
)
```

Behavior:

```python
result = AnalysisOrchestrator(args.repository_root).analyze(args.ticker)
if args.json:
    print(canonical_json(result.to_dict()), end="")
    return
print(render_analysis(result, options), end="")
```

No other CLI command changes.

- [ ] **Step 5: Verify CLI behavior including JSON purity**

```bash
uv run --no-sync pytest -q tests/test_analysis.py -k "analyze_cli"
uv run --no-sync qhapaq analyze QCOM --repository-root . --plain
uv run --no-sync qhapaq analyze QCOM --repository-root . --detail --plain
uv run --no-sync qhapaq analyze QCOM --repository-root . --json | python3 -m json.tool >/dev/null
```

The first human command must contain no JSON envelope. The JSON command must parse with `json.tool` and contain no headings/ANSI text.

- [ ] **Step 6: Commit the CLI integration**

```bash
git add src/qhapaq_finance/cli.py tests/test_analysis.py
git commit -m "feat(cli): add progressive analyze output modes"
```

---

### Task 4: Lock compatibility, plain-mode behavior, and non-calculation boundary

**Files:**
- Modify: `tests/test_analysis_render.py`
- Modify: `tests/test_analysis.py`

**Interfaces:**
- No production API changes.
- This task proves architectural constraints from the spec.

- [ ] **Step 1: Add plain-mode and color-suppression regression tests**

Plain-mode renderer assertion:

```python
def test_plain_mode_has_no_ansi_or_unicode_presentation_glyphs() -> None:
    text = render_analysis(
        AnalysisOrchestrator(ROOT).analyze("QCOM"),
        AnalysisRenderOptions(plain=True, color=True),
    )
    assert "\x1b[" not in text
    for glyph in ("─", "✓", "⚠", "✗"):
        assert glyph not in text
```

CLI tests must prove `NO_COLOR` and non-TTY disable ANSI even without `--plain`.

- [ ] **Step 2: Add a renderer purity regression**

The renderer test module must import only domain result objects and the renderer. Add a monkeypatch test that makes known financial entry points fail if accidentally invoked during rendering:

```python
def test_renderer_does_not_invoke_financial_engines(monkeypatch: pytest.MonkeyPatch) -> None:
    result = AnalysisOrchestrator(ROOT).analyze("QCOM")

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("renderer must not calculate finance")

    monkeypatch.setattr("qhapaq_finance.valuation.analyze_case", forbidden)
    monkeypatch.setattr("qhapaq_finance.research_result.build_canonical_research_result", forbidden)

    text = render_analysis(result, AnalysisRenderOptions(plain=True))
    assert "COMPLETED" in text
```

The important property is that the `AnalysisResult` is built before patching, then rendering succeeds without calling calculation functions.

- [ ] **Step 3: Add width/determinism regression coverage**

Use explicit widths such as 60 and 88. Assert repeated renders are byte-identical and that wrapped prose lines do not exceed the configured width except unavoidable atomic tokens such as content hashes in `--detail`.

Do not snapshot the entire screen unless a small golden fixture proves more stable than semantic assertions.

- [ ] **Step 4: Run focused and broad regressions**

```bash
uv run --no-sync pytest -q tests/test_analysis_render.py tests/test_analysis.py tests/test_research_result.py
```

Confirm existing resolution/status tests in `tests/test_analysis.py` remain unchanged except for the intentionally changed CLI presentation test.

- [ ] **Step 5: Commit regression protection**

```bash
git add tests/test_analysis_render.py tests/test_analysis.py
git commit -m "test(cli): lock progressive analysis rendering contracts"
```

---

### Task 5: Full verification and observable acceptance

**Files:**
- No production files expected unless a verification failure identifies a real implementation defect.

**Interfaces:**
- Final observable contract only.

- [ ] **Step 1: Run repository publication and dependency gates**

```bash
python3 scripts/check_publication.py
uv lock --check
```

- [ ] **Step 2: Run formatting, lint, typing, and complete test suite**

```bash
uv run --no-sync ruff format --check .
uv run --no-sync ruff check .
uv run --no-sync mypy --no-incremental src
uv run --no-sync pytest -q
```

- [ ] **Step 3: Verify all four public analyze modes with observable output**

Use a completed sentinel and an evidence-required arbitrary ticker when available locally.

```bash
uv run --no-sync qhapaq analyze QCOM --plain
uv run --no-sync qhapaq analyze QCOM --detail --plain
uv run --no-sync qhapaq analyze QCOM --json | python3 -m json.tool >/dev/null
uv run --no-sync qhapaq analyze JPM --plain
```

Acceptance evidence:

- QCOM default/plain is human-readable and does not begin with a JSON object;
- QCOM detail contains `ANALYSIS STAGES`, scenario detail, provenance, and audit identity;
- QCOM JSON parses and preserves `analysis-result-v1`;
- JPM displays `EVIDENCE REQUIRED` plus missing SEC evidence and no empty valuation section.

If JPM is no longer evidence-required because later repository state has added evidence, use another resolved ticker without canonical evidence; do not add ticker-specific behavior just to satisfy the demonstration.

- [ ] **Step 4: Verify current sentinel status semantics were not altered**

Run the existing tests that cover:

```text
AAPL          -> COMPLETED
QCOM          -> COMPLETED
NVDA          -> COMPLETED
MSFT          -> EVIDENCE_REQUIRED
COST          -> EVIDENCE_REQUIRED
ZZZZZINVALID  -> UNSUPPORTED_TICKER
```

Use the repository's existing sentinel tests rather than adding duplicate production logic.

- [ ] **Step 5: Inspect the final diff and scope**

```bash
git status --short
git diff --stat origin/main...HEAD
git diff origin/main...HEAD -- \
  src/qhapaq_finance/analysis_render.py \
  src/qhapaq_finance/cli.py \
  tests/test_analysis_render.py \
  tests/test_analysis.py \
  docs/superpowers/specs/2026-09-17-progressive-cli-rendering-design.md \
  docs/superpowers/plans/2026-09-17-progressive-cli-rendering-plan.md
git diff --check origin/main...HEAD
```

Reject unrelated refactors, generated files, cache/data mutations, financial-engine edits, or status-semantic changes.

- [ ] **Step 6: Push only after all gates are GREEN**

```bash
git push origin feat/progressive-cli-rendering
```

Then verify GitHub Actions on Python 3.10 and 3.12 before integration.

## Final report contract

```text
STATUS
PASS | BLOCKED

WHAT CHANGED
- human executive renderer
- detail renderer
- JSON compatibility
- plain/no-color compatibility

TESTS / GATES
- publication guard
- lock
- Ruff format/lint
- mypy
- full pytest
- CLI observable acceptance
- GitHub Actions 3.10/3.12 when pushed

OBSERVED RESULT
- qhapaq analyze TICKER -> human executive output
- --detail -> analyst output
- --plain -> ASCII/no ANSI
- --json -> canonical machine artifact only

REMAINING BLOCKERS
<only actual unresolved blockers>

SHA
<final branch HEAD>
```
