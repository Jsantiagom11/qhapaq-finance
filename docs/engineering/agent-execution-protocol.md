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
