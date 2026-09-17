# Qhapaq Analysis Resolution Contract

## Purpose

This document defines the persistent resolution semantics for the generic `qhapaq analyze TICKER` path.

These rules are project invariants. A task may strengthen them, but must not silently weaken or reinterpret them.

## Resolution rule

1. `CompanyResolver.resolve()` is **offline-only**.
   - It resolves only from the validated local SEC company-reference cache.
   - It must not initiate network access.

2. `AnalysisOrchestrator.plan()` is **offline-only**.
   - Planning inspects current local resolution/evidence readiness.
   - Planning must not hide network side effects.

3. `analyze()` is **offline-first**.
   - It first attempts local resolution.
   - On a local resolution miss, it may perform at most one authoritative refresh of the SEC company-reference data.
   - After that refresh, it may attempt local resolution exactly once more.

4. A local cache miss is never sufficient evidence for `UNSUPPORTED_TICKER`.

5. `UNSUPPORTED_TICKER` is valid only when:
   - an authoritative SEC reference refresh completed successfully; and
   - the normalized ticker is still absent after the post-refresh resolution attempt.

6. Resolution infrastructure failure is `BLOCKED`, not `UNSUPPORTED_TICKER`.
   This includes failures of:
   - SEC/network access;
   - SEC client/configuration;
   - reference decoding/validation;
   - cache refresh/persistence;
   - other failures that prevent an authoritative resolution conclusion.

7. Domain registration and company existence are separate concerns.
   - A company resolved authoritatively must not become `UNSUPPORTED_TICKER` solely because it is absent from `DomainRegistry`.
   - Downstream evidence or capability gaps should use the appropriate fail-closed state, such as `EVIDENCE_REQUIRED` or `BLOCKED`.

## Bounded refresh invariant

For one `analyze()` request, company-reference resolution is bounded to:

```text
local resolve
  -> optional authoritative refresh (maximum 1)
  -> local resolve (maximum 1 post-refresh attempt)
```

No open retry loop may be introduced at the orchestration layer. HTTP retry/backoff policy remains owned by `SecClient`.

## Non-negotiable distinction

```text
cache miss                  != unsupported ticker
registry miss               != unsupported ticker
network/config/refresh fail != unsupported ticker
authoritative negative      == unsupported ticker
```

## Change control

Any future change that would make planning perform hidden network access, allow multiple orchestration-level refreshes, or classify unresolved infrastructure failures as `UNSUPPORTED_TICKER` is an architecture-contract change and must be explicitly approved before implementation.
