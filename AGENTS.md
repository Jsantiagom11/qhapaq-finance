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
