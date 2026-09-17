# Codex Execution Protocol — Design

Date: 2026-09-17
Status: approved for implementation planning
Scope: Qhapaq Finance pilot

## Purpose

Create a reusable operating model for handing well-scoped engineering work from ChatGPT to Codex without making Codex rediscover product decisions or reducing it to a mechanical code writer.

The protocol must optimize for three things at once:

- clear objectives and acceptance criteria;
- strong engineering autonomy during implementation;
- low repetition and low context waste across repeated Codex runs.

## Design principle

Separate persistent execution rules from task-specific intent.

```text
ChatGPT
  -> defines objective, constraints, invariants, acceptance

Repository instructions
  -> define how Codex should work in this codebase

Codex in WSL
  -> inspects the real working tree
  -> chooses implementation details
  -> edits code
  -> runs tests
  -> observes failures
  -> diagnoses root causes
  -> iterates
  -> verifies compatibility
  -> inspects the diff
  -> leaves the repo deliverable
```

Codex receives little freedom over what counts as correct, but substantial freedom over how to implement the solution.

## Chosen structure

Use a hybrid, repository-local model for the Qhapaq pilot:

```text
AGENTS.md
  -> short persistent operating contract

docs/engineering/agent-execution-protocol.md
  -> detailed reference protocol

current task prompt
  -> only the task delta
```

Do not promote the protocol to a global `$CODEX_HOME/AGENTS.md` yet. First validate the Qhapaq-local version in at least one real closure.

## Responsibility split

### `AGENTS.md`

Keep this concise and stable. It should define the rules that apply to almost every engineering task in Qhapaq:

- inspect branch, HEAD, status, diff, code, tests, and conventions before editing;
- understand the current implementation before changing it;
- prefer the smallest coherent change that satisfies the objective;
- preserve approved architecture and public contracts unless the task explicitly changes them;
- use tests and runtime feedback rather than speculative edits;
- diagnose root cause before patching failures;
- do not weaken tests to manufacture GREEN;
- run all repository quality gates;
- inspect the final diff and working tree;
- do not use destructive Git operations;
- do not claim success without observable verification;
- leave the repository understandable and deliverable even when blocked.

`AGENTS.md` should point to the detailed protocol rather than duplicate it.

### `docs/engineering/agent-execution-protocol.md`

This document contains the full operating procedure and can evolve without bloating the agent entrypoint.

It should define:

1. preflight inspection;
2. implementation loop;
3. debugging behavior;
4. compatibility verification;
5. full-gate execution;
6. final diff review;
7. stop/escalation conditions;
8. delivery behavior;
9. compact final report format.

The protocol should remain implementation-agnostic and reusable across Qhapaq tasks.

### Task prompt

The task prompt should contain only information that changes between closures.

Default shape:

```text
MISSION
<observable outcome>

CURRENT CONTEXT
<only facts required to understand this closure>

INVARIANTS
<contracts that cannot be broken>

ACCEPTANCE
<observable evidence of success>

NON-GOALS
<adjacent work explicitly excluded>

Execute end-to-end and follow AGENTS.md.
```

Add more detail only when it improves correctness. Do not repeat persistent repository instructions in every task prompt.

## Execution semantics

Codex is responsible for implementation detail.

It may:

- choose the best existing abstraction;
- create small focused helpers;
- improve test fixtures;
- relocate behavior to a more appropriate composition boundary;
- adjust the implementation plan when the real working tree reveals a better path.

It must not silently redefine the objective, public behavior, financial semantics, or accepted invariants.

When the real code contradicts an assumption in the task prompt, Codex should prefer evidence from the working tree, stop if the contradiction changes the task contract, and report the mismatch instead of improvising a product decision.

## Default engineering loop

```text
inspect real state
  -> understand current flow
  -> establish or reproduce failing behavior
  -> make the minimum coherent change
  -> run focused verification
  -> diagnose any new failure
  -> iterate
  -> run regression suite
  -> run full repository gates
  -> inspect git diff/status
  -> report verified result
```

Tests are evidence, not ceremony. TDD is preferred for behavioral changes and regressions, but the protocol should not force artificial tests for purely mechanical changes when existing verification already proves correctness.

## Stop conditions

Codex should stop and report rather than expand scope when satisfying the task would require any of the following unless explicitly authorized:

- changing financial semantics;
- changing public status semantics;
- introducing ticker-specific production behavior;
- destructive migrations;
- large architectural rewrites;
- weakening fail-closed behavior;
- weakening tests or quality gates;
- unrelated refactoring;
- destructive Git commands.

## Delivery contract

A task is not complete because a command exits with code 0.

Completion requires evidence that the acceptance criteria are true and that the repository is in a scoped, intentional state.

Before declaring PASS, Codex should inspect at minimum:

- required tests/gates;
- observable task result;
- `git status`;
- `git diff` or equivalent staged/working-tree diff;
- unexpected generated or temporary files;
- unrelated edits and scope creep.

If all required checks pass, Codex may create coherent commits and push when the task explicitly authorizes it.

If anything required remains RED, it must not claim completion or push a knowingly incomplete closure unless explicitly instructed to preserve a checkpoint.

## Final report

Default final output should be compact and evidence-oriented:

```text
STATUS
PASS | BLOCKED

WHAT CHANGED
<important changes only>

TESTS / GATES
<pass/fail summary>

OBSERVED RESULT
<acceptance evidence>

REMAINING BLOCKERS
<only real unresolved items>

SHA
<if a commit was created>
```

Task-specific prompts may request additional sections such as sentinel matrices or compatibility results.

## Interaction with Qhapaq-specific constraints

This protocol does not redefine Qhapaq's financial architecture. Task prompts remain responsible for supplying closure-specific contracts such as:

- Python compatibility targets;
- fail-closed financial rules;
- allowed public states;
- ticker-resolution semantics;
- sentinel expectations;
- explicitly frozen subsystems.

The persistent protocol governs execution discipline, not product meaning.

## Pilot strategy

1. Implement repository-local `AGENTS.md`.
2. Implement `docs/engineering/agent-execution-protocol.md`.
3. Use the protocol for `feat/pipeline-contract-matrix`.
4. Measure whether task prompts become shorter without losing implementation quality.
5. After one or more successful closures, decide whether the universal subset should move to `$CODEX_HOME/AGENTS.md` for reuse across projects.

## Success criteria

The protocol is successful when:

- task prompts become materially shorter;
- Codex starts by inspecting the real repository instead of rediscovering product intent;
- product decisions remain outside Codex's implementation loop unless explicitly delegated;
- Codex retains enough autonomy to solve emergent implementation issues;
- final reports are compact, evidence-backed, and easy to review;
- repeated instructions no longer dominate token usage;
- the same model can later be reused for Poemaster, PROPA1N, or other repositories with project-specific overlays.

## Non-goals

This design does not:

- introduce a new task-management system;
- replace GitHub CI;
- replace repository tests or Janitor;
- create a global Codex policy yet;
- prescribe exact implementation code;
- encode current one-off Qhapaq task details into persistent instructions;
- change Qhapaq product or financial semantics.
