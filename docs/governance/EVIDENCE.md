# Evidence

Last verified: 2026-08-28

Evidence here supports current governance claims; it is not a terminal transcript.

## Stable baseline

| Claim | Evidence | Result |
| --- | --- | --- |
| Quality baseline restored | `5ff2c1e` — `chore: restore quality baseline` | PASS |
| Dependency lock committed | `2ebc421` — `chore: add reproducible dependency lock` | PASS |
| Project identity renamed | `9fb4fe4` — `chore: rename project to Qhapaq Finance` | PASS |
| Lock is internally current | `uv lock --check` | PASS |
| Formatting | `ruff format --check .` | PASS: 17 files already formatted |
| Lint | `ruff check .` | PASS: all checks passed |
| Tests | `pytest` | PASS: 4 tests |
| Static typing | `mypy .` | PASS: 10 source files checked |
| CLI entry point | `uv run qhapaq --help` | PASS: usage displayed without network access |
| Whitespace | `git diff --check` | PASS |

The tests use deterministic synthetic data. They cover lagged momentum selection, transaction-cost
effects, the equal-weight benchmark, and chronological non-overlapping walk-forward folds. They do
not validate live market data or financial usefulness.

## Reproducibility boundary

The committed `uv.lock` SHA-256 is
`42430d0aee5a3bc67e0a71be64f36fde8a038abdbd98015fc8bbe60eb55e1136`.

Current source supports explicit configuration and deterministic synthetic tests. It does not yet
produce the complete evidence package required for a reproducible quantitative experiment:

- dataset identity and checksum;
- configuration and applicable random seed;
- Git commit SHA and dependency lock identity;
- walk-forward configuration;
- generated metrics and a result manifest.

Until that package exists for an experiment, results must not be described as a demonstrated
investment or trading edge. `docs/AUDIT.md` preserves the historical prototype audit and its
publication gates.
