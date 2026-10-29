# H1.1 Fast Feedback Foundation Design

## Intent

Provide a trustworthy sub-10-second pytest loop for ordinary deterministic financial work without changing production behavior, financial outputs, public contracts, or the full test collection.

## Approved scope

- Register `fast`, `integration`, `browser`, `socket`, and `live_data` pytest markers.
- Mark complete, demonstrably pure test modules covering financial contracts; Diamond scoring, metrics, percentiles, serialization, and dataset identities; and Executive contracts and goal-seek.
- Run FAST through native pytest marker selection: `uv run --no-sync pytest -q -p no:cacheprovider -m fast`.
- Fail FAST tests if they require sockets or also carry an environment-dependent marker.
- Preserve the original full collection and validate collection with Python 3.10 and 3.12 when available.

## Approaches

1. **Module-local markers — selected.** Each pure module declares `pytestmark = pytest.mark.fast`. Classification stays next to the tests and new tests in those modules inherit it.
2. **Central path allowlist — rejected.** It changes fewer files but hides classification in `conftest.py` and creates a second dependency map.
3. **Per-test decorators — rejected.** It is explicit but noisy and easy to apply inconsistently within modules that are pure as a whole.

The isolation guard belongs in `tests/conftest.py`: for the supported `-m fast` lane, a Python audit hook denies socket events from collection through session teardown, including previously imported constructors and broad-scope fixtures. Collection rejects overlap between FAST and `integration`, `browser`, `socket`, or `live_data`. The guard does not skip tests and remains inactive outside the FAST lane.

## Non-goals

- No production code, CI, CLI wrappers, changed-file selection, `-k` filtering, or financial refactoring.
- No reclassification of integration/live/browser tests beyond registering their public markers.
- No weakening of assertions, skips, or fail-closed financial behavior.

## Acceptance

FAST has zero failures and zero skips across ten runs with p95 below 10 seconds. Its modules use deterministic in-memory inputs or immutable literals, its socket guard remains active, and full collection has the same node IDs before and after.
