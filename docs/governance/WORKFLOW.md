# Workflow

This layer exists to control work, expose constraints, and preserve evidence with minimal ceremony.

```text
INBOX → NEXT → DOING → REVIEW → DONE
                   ↓
            BLOCKED / DEFERRED / DROPPED
```

## State rules

| State | Meaning |
| --- | --- |
| INBOX | Unassessed input; it is not a commitment. |
| NEXT | Defined, prioritized work ready to start; maximum three items. |
| DOING | Actively changing the system; maximum two items. Prefer finishing before starting. |
| REVIEW | Implementation is complete but required evidence or review is pending. |
| DONE | The Definition of Done is satisfied and linked to reproducible evidence. |
| BLOCKED | Progress cannot continue until a named dependency, decision, or external condition changes. |
| DEFERRED | Valid work intentionally postponed because it is not the current bottleneck or would expand scope. |
| DROPPED | Work explicitly rejected, with a brief reason when rediscovery is likely. |

`DONE` never means “looks correct.” Evidence may be passing tests, a reproducible command, a
generated artifact, checksum, commit, documented result, or measurable output. Move completed work
to `REVIEW` until its promised evidence exists.

## Decision model

- Keep strategy (desired state), tactics (chosen transitions), operations (current work), and
  evidence/feedback distinct.
- Identify the system bottleneck before adding work. Prioritize impact, urgency, and unlock
  potential against cost, risk, and cognitive load.
- Optimize the whole system, keep technical debt visible, and prefer reversible decisions under
  uncertainty.
- Keep feedback loops short. Defer adjacent ideas instead of expanding an active item's scope.
- Record a decision only when its context will affect future choices. Update governance only when
  project state materially changes.

## Minimal session lifecycle

1. Read `CURRENT_STATE.md`.
2. Read `NEXT_ACTIONS.md`.
3. Select one objective without exceeding the WIP limit.
4. Establish a relevant baseline.
5. Make the smallest coherent change.
6. Validate the Definition of Done.
7. Commit the isolated change.
8. Update governance only if project state materially changed.

For quantitative experiments, evidence must identify the dataset and checksum, configuration, Git
SHA, dependency lock, applicable random seed, walk-forward configuration, metrics, and result
manifest. No investment or trading-edge claim is valid without reproducible evidence.
