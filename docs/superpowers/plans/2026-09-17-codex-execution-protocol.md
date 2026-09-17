# Codex Execution Protocol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a repository-local execution protocol so Codex receives stable engineering rules from the repo and each task prompt only needs to describe the current mission, invariants, acceptance criteria, and non-goals.

**Architecture:** Keep the agent entrypoint small and durable in root `AGENTS.md`, and place the full reusable operating procedure in `docs/engineering/agent-execution-protocol.md`. The root file points to the detailed protocol; task prompts remain ephemeral and contain only closure-specific intent.

**Tech Stack:** Markdown, Git, Codex repository instructions.

**Spec:** `docs/superpowers/specs/2026-09-17-codex-execution-protocol-design.md`

## Global Constraints

- Pilot only in the Qhapaq repository; do not create or modify `$CODEX_HOME/AGENTS.md`.
- Do not encode `pipeline-contract-matrix`, COST, or other one-off closure details into persistent instructions.
- Persistent instructions govern execution discipline, not Qhapaq financial/product semantics.
- `AGENTS.md` must stay concise and point to the detailed protocol instead of duplicating it.
- Preserve existing repository architecture and tooling; this change is documentation/instruction only.
- Do not introduce a new task-management system, replace CI, replace Janitor, or prescribe exact implementation code.
- No destructive Git operations.

---

## File Structure

- Create `AGENTS.md` — concise repository-level Codex operating contract and pointer to the detailed protocol.
- Create `docs/engineering/agent-execution-protocol.md` — full reusable execution procedure.
- No production code, tests, CI, Janitor, or Python files should change in this implementation.

---

### Task 1: Create the detailed execution protocol

**Files:**
- Create: `docs/engineering/agent-execution-protocol.md`

**Interfaces:**
- Consumes: design requirements from `docs/superpowers/specs/2026-09-17-codex-execution-protocol-design.md`.
- Produces: a stable reference document that `AGENTS.md` can point to as `docs/engineering/agent-execution-protocol.md`.

- [ ] **Step 1: Verify the protocol file does not already exist**

Run:

```bash
test ! -e docs/engineering/agent-execution-protocol.md
```

Expected: exit code `0`. If the file already exists, stop and inspect it before proceeding rather than overwriting it blindly.

- [ ] **Step 2: Create the detailed protocol**

Create `docs/engineering/agent-execution-protocol.md` with this content:

```markdown
# Agent Execution Protocol

## Purpose

This protocol defines how an implementation agent should turn an approved engineering objective into a verified, deliverable repository state.

Product intent, financial semantics, architecture decisions, and closure-specific constraints come from the current task. This protocol defines execution discipline only.

## Preflight

Before editing:

1. inspect the current branch and HEAD;
2. inspect `git status` and existing diffs;
3. read the code, tests, documentation, and conventions relevant to the task;
4. identify the current behavior before changing it;
5. preserve pre-existing user work and unrelated local changes.

Do not assume the repository matches an earlier prompt, chat, or remote snapshot when the working tree provides newer evidence.

## Implementation discipline

Prefer the smallest coherent change that satisfies the approved objective.

Reuse existing abstractions when they fit. Small focused helpers, fixture improvements, or relocation of behavior to the correct composition boundary are acceptable when they directly serve the task.

Do not silently redefine public behavior, architecture, financial semantics, or accepted invariants.

When the working tree contradicts a task assumption, use repository evidence to diagnose the mismatch. If resolving it would change the task contract, stop and report instead of making a new product decision.

## Feedback loop

For behavioral changes and regressions, prefer this loop:

```text
reproduce or establish the behavior
-> make the minimum coherent change
-> run focused verification
-> observe failures
-> diagnose root cause
-> correct
-> rerun focused verification
-> run regressions
-> run full repository gates
```

Tests are evidence, not ceremony. Do not weaken assertions, skip meaningful tests, or reinterpret failures merely to obtain GREEN.

For purely mechanical changes, existing verification may be sufficient when it directly proves correctness.

## Debugging behavior

When a check fails:

1. capture the exact failure;
2. determine whether it is pre-existing or introduced by the current change;
3. identify the root cause before patching;
4. avoid speculative multi-file edits;
5. rerun the narrowest useful verification first;
6. expand back to regression and full-gate verification only after the focused failure is resolved.

A process exit code alone is not proof that the intended behavior is correct. Inspect the observable result required by the acceptance criteria.

## Compatibility

Honor the compatibility contract stated by the repository and the current task.

Do not introduce newer language/runtime/library requirements unless explicitly authorized. If compatibility is part of acceptance, verify the stated supported boundaries rather than assuming them.

## Full-gate verification

Before declaring completion, run the repository's required quality gates. Use the canonical project commands when they exist rather than inventing weaker substitutes.

If the task specifies additional sentinel, integration, compatibility, or end-to-end checks, those checks are part of completion.

Do not claim PASS while a required gate is RED.

## Final diff review

Before delivery, inspect at minimum:

```bash
git status
git diff --stat
git diff
```

Also inspect the staged diff when commits are being prepared.

Look specifically for:

- unintended edits;
- unrelated refactors;
- generated or temporary files;
- debug output;
- weakened tests or assertions;
- duplicated fixtures or helpers;
- scope creep;
- accidental changes to caches, local data, or secrets.

The final repository state should be understandable to the next engineer without relying on hidden chat context.

## Stop and escalate

Unless the current task explicitly authorizes them, stop and report before making changes that require:

- different financial semantics;
- different public status semantics;
- ticker-specific production behavior;
- destructive migrations;
- a large architectural rewrite;
- weaker fail-closed behavior;
- weaker tests or quality gates;
- unrelated refactoring;
- destructive Git commands.

A blocked result with precise evidence is preferable to an apparently successful result obtained by changing the problem.

## Git and delivery

Preserve existing user work.

Do not use destructive commands such as broad `git reset`, `git clean`, or destructive checkout patterns to force a clean tree.

Only commit or push when the current task explicitly authorizes it and all required completion conditions are satisfied.

If work remains RED, leave the working tree understandable and report the exact blocker. Do not describe an incomplete closure as complete.

## Completion contract

A task is complete only when:

1. the acceptance criteria are observably true;
2. required focused, regression, integration, and quality checks pass;
3. compatibility requirements are verified when applicable;
4. the final diff is intentional and scoped;
5. the working tree contains no unexplained artifacts;
6. any commit/push requested by the task has completed successfully.

## Default final report

Keep the report concise and evidence-oriented:

```text
STATUS
PASS | BLOCKED

WHAT CHANGED
<important changes only>

TESTS / GATES
<required checks and results>

OBSERVED RESULT
<evidence that acceptance is or is not satisfied>

REMAINING BLOCKERS
<only unresolved items>

SHA
<commit SHA when one was created>
```

Task-specific prompts may request extra sections, such as sentinel matrices, compatibility results, or migration evidence.

## Task prompt contract

A normal task prompt should contain only the changing context:

```text
MISSION
<observable outcome>

CURRENT CONTEXT
<only facts required for this closure>

INVARIANTS
<contracts that must remain true>

ACCEPTANCE
<observable evidence of success>

NON-GOALS
<adjacent work explicitly excluded>

Execute end-to-end and follow AGENTS.md.
```

Add detail when it improves correctness, but do not repeat persistent repository instructions in every prompt.
```

- [ ] **Step 3: Verify the document contains the required execution phases**

Run:

```bash
python3 - <<'PY'
from pathlib import Path

path = Path("docs/engineering/agent-execution-protocol.md")
text = path.read_text()
required = [
    "## Preflight",
    "## Implementation discipline",
    "## Feedback loop",
    "## Debugging behavior",
    "## Compatibility",
    "## Full-gate verification",
    "## Final diff review",
    "## Stop and escalate",
    "## Git and delivery",
    "## Completion contract",
    "## Default final report",
    "## Task prompt contract",
]
missing = [item for item in required if item not in text]
if missing:
    raise SystemExit(f"missing sections: {missing}")
print("agent execution protocol structure: PASS")
PY
```

Expected:

```text
agent execution protocol structure: PASS
```

- [ ] **Step 4: Verify one-off closure details did not leak into the persistent protocol**

Run:

```bash
if grep -En 'pipeline-contract-matrix|ZZZZZINVALID|\bCOST\b' docs/engineering/agent-execution-protocol.md; then
  echo 'task-specific detail leaked into persistent protocol' >&2
  exit 1
fi

echo 'persistent protocol scope: PASS'
```

Expected:

```text
persistent protocol scope: PASS
```

- [ ] **Step 5: Commit the detailed protocol**

```bash
git add docs/engineering/agent-execution-protocol.md
git commit -m "docs: add agent execution protocol"
```

Expected: one commit containing only the new detailed protocol.

---

### Task 2: Add the concise repository agent entrypoint

**Files:**
- Create: `AGENTS.md`
- Read: `docs/engineering/agent-execution-protocol.md`

**Interfaces:**
- Consumes: `docs/engineering/agent-execution-protocol.md`.
- Produces: root-level persistent instructions discovered by Codex for repository work.

- [ ] **Step 1: Verify a root `AGENTS.md` does not already exist**

Run:

```bash
test ! -e AGENTS.md
```

Expected: exit code `0`. If it exists, inspect and reconcile it rather than replacing it blindly.

- [ ] **Step 2: Create `AGENTS.md`**

Create root `AGENTS.md` with this content:

```markdown
# Qhapaq Finance — Agent Instructions

## Operating contract

Work from the real repository state, not assumptions from earlier prompts.

Before editing, inspect the current branch, HEAD, `git status`, existing diffs, relevant code, tests, documentation, and repository conventions. Preserve unrelated user work.

Understand the current implementation before changing it. Prefer the smallest coherent change that satisfies the current objective and reuse existing abstractions when they fit.

Use tests and runtime feedback to drive behavioral changes. When something fails, identify the root cause before patching. Do not weaken tests, assertions, fail-closed behavior, or quality gates merely to obtain GREEN.

Honor the task's approved architecture, public contracts, financial semantics, compatibility targets, invariants, acceptance criteria, and non-goals. If satisfying the task requires changing one of those, stop and report the conflict instead of silently redefining the task.

Run all required repository gates and task-specific verification. A zero exit code alone is not sufficient when acceptance requires an observable runtime result.

Before declaring completion, inspect `git status`, the final diff, unintended files, unrelated edits, duplication, debug artifacts, and scope creep.

Do not use destructive Git operations. Do not claim completion while required verification is RED. Only commit or push when the task authorizes it and completion criteria are satisfied.

Leave the repository understandable and deliverable whether the result is PASS or BLOCKED.

## Detailed procedure

Follow `docs/engineering/agent-execution-protocol.md` for the full preflight, development loop, debugging, compatibility, verification, diff-review, stop-condition, delivery, and reporting procedure.

## Task-specific intent

The current task prompt owns the changing engineering intent: mission, current context, invariants, acceptance criteria, non-goals, and any additional verification or delivery requirements.

Do not infer new product or financial decisions from this file.
```

- [ ] **Step 3: Verify `AGENTS.md` is concise and linked to the protocol**

Run:

```bash
python3 - <<'PY'
from pathlib import Path

path = Path("AGENTS.md")
text = path.read_text()
lines = text.splitlines()
if len(lines) > 100:
    raise SystemExit(f"AGENTS.md too long: {len(lines)} lines")
needle = "docs/engineering/agent-execution-protocol.md"
if needle not in text:
    raise SystemExit("AGENTS.md does not reference detailed protocol")
print(f"AGENTS.md structure: PASS ({len(lines)} lines)")
PY
```

Expected: `PASS` with no more than 100 lines.

- [ ] **Step 4: Verify `AGENTS.md` contains no current-closure implementation details**

Run:

```bash
if grep -En 'pipeline-contract-matrix|ZZZZZINVALID|\bCOST\b|CompanyResolver' AGENTS.md; then
  echo 'task-specific detail leaked into AGENTS.md' >&2
  exit 1
fi

echo 'AGENTS.md scope: PASS'
```

Expected:

```text
AGENTS.md scope: PASS
```

- [ ] **Step 5: Commit the repository entrypoint**

```bash
git add AGENTS.md
git commit -m "docs: add Qhapaq agent instructions"
```

Expected: one commit containing only `AGENTS.md`.

---

### Task 3: Verify the protocol as one coherent repository contract

**Files:**
- Verify: `AGENTS.md`
- Verify: `docs/engineering/agent-execution-protocol.md`
- Verify: `docs/superpowers/specs/2026-09-17-codex-execution-protocol-design.md`

**Interfaces:**
- Consumes: the two new persistent instruction files.
- Produces: evidence that Codex can start from root instructions and reach the detailed procedure without task-specific leakage.

- [ ] **Step 1: Verify both files exist and are non-empty**

Run:

```bash
test -s AGENTS.md
test -s docs/engineering/agent-execution-protocol.md
echo 'instruction files present: PASS'
```

Expected:

```text
instruction files present: PASS
```

- [ ] **Step 2: Verify the entrypoint-to-reference link resolves**

Run:

```bash
python3 - <<'PY'
from pathlib import Path

agents = Path("AGENTS.md").read_text()
protocol = Path("docs/engineering/agent-execution-protocol.md")
if str(protocol) not in agents:
    raise SystemExit("AGENTS.md reference mismatch")
if not protocol.is_file():
    raise SystemExit("referenced protocol file does not exist")
print("instruction chain: PASS")
PY
```

Expected:

```text
instruction chain: PASS
```

- [ ] **Step 3: Verify the implementation stayed documentation-only**

Run:

```bash
git diff HEAD~2..HEAD --name-only
```

Expected implementation files:

```text
AGENTS.md
docs/engineering/agent-execution-protocol.md
```

The earlier approved spec and implementation plan may also be present on the branch from prior commits, but no `src/`, `tests/`, CI, Janitor, or Python files should be changed by these implementation commits.

- [ ] **Step 4: Inspect the final diff and working tree**

Run:

```bash
git status --short --branch
git diff --check
git log -3 --oneline
```

Expected:

- no whitespace errors from `git diff --check`;
- no unexplained untracked or modified files from this implementation;
- the latest implementation commits correspond to the detailed protocol and root instructions.

- [ ] **Step 5: Perform the pilot handoff smoke test**

Without changing production code, confirm that the next Codex task can be stated using only this task-delta shape:

```text
MISSION
<observable outcome>

CURRENT CONTEXT
<only facts required for the closure>

INVARIANTS
<contracts that cannot be broken>

ACCEPTANCE
<observable evidence of success>

NON-GOALS
<adjacent work excluded>

Execute end-to-end and follow AGENTS.md.
```

Expected: the prompt does not need to restate preflight inspection, debugging loop, quality-gate discipline, final diff review, destructive-Git prohibition, or final reporting behavior because those are now repository-persistent.

- [ ] **Step 6: Report the implementation state**

Use:

```text
STATUS
PASS | BLOCKED

FILES
AGENTS.md
docs/engineering/agent-execution-protocol.md

VERIFICATION
instruction files present: PASS/FAIL
instruction chain: PASS/FAIL
persistent scope: PASS/FAIL
git diff --check: PASS/FAIL

COMMITS
<implementation SHAs>

NEXT
Use the protocol for feat/pipeline-contract-matrix with a task-delta-only Codex prompt.
```

Do not push merely because this plan says to commit. Push only if the active task/session explicitly authorizes pushing the branch.
