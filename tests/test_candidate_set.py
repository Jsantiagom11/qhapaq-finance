from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from qhapaq_finance.candidate_set import (
    Candidate,
    CandidateSetError,
    DiamondSnapshotRef,
    DiamondTopNPolicy,
    SnapshotStatus,
    build_candidate_set,
    candidate_set_identity,
)
from qhapaq_finance.diamond.archetypes import ArchetypeScores
from qhapaq_finance.diamond.contracts import FundamentalRecord, SecurityRef
from qhapaq_finance.diamond.funnel import FunnelRun, run_funnel

try:
    from tests.diamond_helpers import AS_OF, rich_record
except ModuleNotFoundError:
    from diamond_helpers import AS_OF, rich_record

pytestmark = pytest.mark.fast

UNIVERSE_ID = "synthetic-operating"
SNAPSHOT_ID = "snapshot:synthetic-sealed-v1"
EXPECTED_DATASET_IDENTITY = "6ce1d02f98fdec31e427e84264a229e8cd0d6ca7e8bbf3c1361bf841270638af"
EXPECTED_CANDIDATE_SET_ID = "f88ec443076d1bcc33a270458c200572b2f7348a68e6679252686887e40b96cd"


class _MemoryProvider:
    provider_requests = 0
    cache_hits = 0
    cache_misses = 0

    def __init__(self, records: tuple[FundamentalRecord, ...]) -> None:
        self._records = records
        self._securities = tuple(
            SecurityRef(record.ticker, record.security_id, record.issuer_id) for record in records
        )

    def universe(self, universe_id: str, as_of: date) -> tuple[SecurityRef, ...]:
        assert universe_id == UNIVERSE_ID
        assert as_of == AS_OF
        return self._securities

    def fundamentals(
        self,
        securities: tuple[SecurityRef, ...],
        as_of: date,
        history_years: int = 5,
    ) -> tuple[FundamentalRecord, ...]:
        assert securities == self._securities
        assert as_of == AS_OF
        assert history_years == 5
        return self._records


@pytest.fixture(scope="module")
def funnel() -> FunnelRun:
    records = tuple(
        rich_record(
            f"T{index:02d}",
            scale=1.0 + index * 0.03,
            growth=0.04 + index * 0.003,
            op_margin=0.15 + index * 0.004,
            fcf_margin=0.10 + index * 0.003,
            dilution=-0.005 + index * 0.0004,
            recent_share_change=-0.01 + index * 0.001,
        )
        for index in range(20)
    )
    result = run_funnel(
        _MemoryProvider(records),
        universe_id=UNIVERSE_ID,
        as_of=AS_OF,
        depth=5,
    )
    assert result.metadata.dataset_identity == EXPECTED_DATASET_IDENTITY
    return result


def _snapshot(
    funnel: FunnelRun,
    *,
    status: SnapshotStatus = SnapshotStatus.COMPLETE,
    snapshot_id: str = SNAPSHOT_ID,
    dataset_identity: str | None = None,
    universe_id: str = UNIVERSE_ID,
    cutoff: date = AS_OF,
) -> DiamondSnapshotRef:
    return DiamondSnapshotRef(
        snapshot_id=snapshot_id,
        dataset_identity=dataset_identity or funnel.metadata.dataset_identity,
        universe_id=universe_id,
        cutoff=cutoff,
        status=status,
    )


def _build(
    funnel: FunnelRun,
    *,
    snapshot: DiamondSnapshotRef | None = None,
    universe_id: str = UNIVERSE_ID,
    cutoff: date = AS_OF,
    limit: int = 3,
):
    return build_candidate_set(
        funnel,
        snapshot=snapshot or _snapshot(funnel),
        universe_id=universe_id,
        cutoff=cutoff,
        policy=DiamondTopNPolicy(limit=limit),
    )


def test_build_preserves_exact_diamond_order_rank_and_security(funnel: FunnelRun) -> None:
    candidate_set = _build(funnel)

    assert candidate_set.candidates == (
        Candidate(SecurityRef("T18", "issuer-t18:T18", "issuer-t18"), 1, 1),
        Candidate(SecurityRef("T19", "issuer-t19:T19", "issuer-t19"), 2, 2),
        Candidate(SecurityRef("T17", "issuer-t17:T17", "issuer-t17"), 3, 3),
    )
    assert candidate_set.dataset_identity == EXPECTED_DATASET_IDENTITY
    assert candidate_set.universe_id == UNIVERSE_ID
    assert candidate_set.cutoff == AS_OF
    assert candidate_set.production_reproducible is True


def test_identity_is_canonical_deterministic_and_independently_pinned(funnel: FunnelRun) -> None:
    first = _build(funnel)
    second = _build(funnel)

    assert first.candidate_set_id == EXPECTED_CANDIDATE_SET_ID
    assert second.candidate_set_id == EXPECTED_CANDIDATE_SET_ID
    assert candidate_set_identity(first) == EXPECTED_CANDIDATE_SET_ID


def test_identity_changes_when_selection_or_snapshot_changes(funnel: FunnelRun) -> None:
    base = _build(funnel)
    shorter = _build(funnel, limit=2)
    other_snapshot = _build(
        funnel,
        snapshot=_snapshot(funnel, snapshot_id="snapshot:synthetic-sealed-v2"),
    )

    assert shorter.candidate_set_id != base.candidate_set_id
    assert other_snapshot.candidate_set_id != base.candidate_set_id


@pytest.mark.parametrize(
    ("snapshot", "universe_id", "cutoff", "error"),
    (
        ("dataset", UNIVERSE_ID, AS_OF, "SNAPSHOT_DATASET_MISMATCH"),
        ("universe", UNIVERSE_ID, AS_OF, "SNAPSHOT_UNIVERSE_MISMATCH"),
        ("cutoff", UNIVERSE_ID, AS_OF, "SNAPSHOT_CUTOFF_MISMATCH"),
    ),
)
def test_snapshot_context_mismatch_fails_closed(
    funnel: FunnelRun,
    snapshot: str,
    universe_id: str,
    cutoff: date,
    error: str,
) -> None:
    snapshot_ref = {
        "dataset": _snapshot(funnel, dataset_identity="0" * 64),
        "universe": _snapshot(funnel, universe_id="other-universe"),
        "cutoff": _snapshot(funnel, cutoff=date(2026, 9, 19)),
    }[snapshot]

    with pytest.raises(CandidateSetError, match=error):
        _build(
            funnel,
            snapshot=snapshot_ref,
            universe_id=universe_id,
            cutoff=cutoff,
        )


def test_result_cutoff_mismatch_fails_closed(funnel: FunnelRun) -> None:
    inconsistent = replace(
        funnel,
        results=(replace(funnel.results[0], data_as_of=date(2026, 9, 19)), *funnel.results[1:]),
    )

    with pytest.raises(CandidateSetError, match="RESULT_CUTOFF_MISMATCH"):
        _build(inconsistent)


def test_missing_source_security_never_falls_back_to_ticker(funnel: FunnelRun) -> None:
    inconsistent = replace(
        funnel,
        results=(replace(funnel.results[0], source_security=None), *funnel.results[1:]),
    )

    with pytest.raises(CandidateSetError, match="SOURCE_SECURITY_REQUIRED"):
        _build(inconsistent)


def test_source_security_ticker_mismatch_fails_closed(funnel: FunnelRun) -> None:
    first = funnel.results[0]
    inconsistent = replace(
        funnel,
        results=(
            replace(
                first,
                source_security=SecurityRef("OTHER", "issuer-t18:T18", "issuer-t18"),
            ),
            *funnel.results[1:],
        ),
    )

    with pytest.raises(CandidateSetError, match="SOURCE_SECURITY_TICKER_MISMATCH"):
        _build(inconsistent)


def test_conflicting_reuse_of_security_id_fails_closed(funnel: FunnelRun) -> None:
    first, second, *rest = funnel.results
    assert first.source_security is not None
    assert second.source_security is not None
    inconsistent = replace(
        funnel,
        results=(
            first,
            replace(
                second,
                source_security=SecurityRef(
                    second.ticker,
                    first.source_security.security_id,
                    second.source_security.issuer_id,
                ),
            ),
            *rest,
        ),
    )

    with pytest.raises(CandidateSetError, match="SECURITY_IDENTITY_CONFLICT"):
        _build(inconsistent)


def test_same_ticker_with_distinct_security_refs_remains_unambiguous(funnel: FunnelRun) -> None:
    first, second, *rest = funnel.results
    assert first.source_security is not None
    assert second.source_security is not None
    second_identity = SecurityRef(
        first.ticker,
        second.source_security.security_id,
        second.source_security.issuer_id,
    )
    ambiguous_ticker = replace(
        funnel,
        results=(
            first,
            replace(second, ticker=first.ticker, source_security=second_identity),
            *rest,
        ),
    )

    candidate_set = _build(ambiguous_ticker, limit=2)

    assert [candidate.security.ticker for candidate in candidate_set.candidates] == ["T18", "T18"]
    assert [candidate.security.security_id for candidate in candidate_set.candidates] == [
        "issuer-t18:T18",
        "issuer-t19:T19",
    ]


def test_unrankable_result_is_never_promoted_or_replaced(funnel: FunnelRun) -> None:
    first = funnel.results[0]
    unrankable = replace(
        first,
        archetypes=ArchetypeScores(None, None, None, None, None),
    )
    inconsistent = replace(funnel, results=(unrankable, *funnel.results[1:]))

    with pytest.raises(CandidateSetError, match="DIAMOND_RESULT_UNRANKABLE"):
        _build(inconsistent)


def test_policy_cannot_select_beyond_authoritative_results(funnel: FunnelRun) -> None:
    with pytest.raises(CandidateSetError, match="SELECTION_EXCEEDS_DIAMOND_RESULTS"):
        _build(funnel, limit=len(funnel.results) + 1)


def test_incomplete_snapshot_builds_but_cannot_claim_production_reproducibility(
    funnel: FunnelRun,
) -> None:
    candidate_set = _build(
        funnel,
        snapshot=_snapshot(funnel, status=SnapshotStatus.INCOMPLETE),
    )

    assert candidate_set.production_reproducible is False
    with pytest.raises(CandidateSetError, match="SNAPSHOT_NOT_COMPLETE"):
        candidate_set.require_production_reproducible()


@pytest.mark.parametrize("limit", (0, -1, True))
def test_policy_limit_must_be_a_positive_integer(limit: int) -> None:
    with pytest.raises(CandidateSetError, match="SELECTION_LIMIT_INVALID"):
        DiamondTopNPolicy(limit=limit)


def test_snapshot_requires_a_sha256_dataset_identity() -> None:
    with pytest.raises(CandidateSetError, match="DATASET_IDENTITY_INVALID"):
        DiamondSnapshotRef(
            snapshot_id=SNAPSHOT_ID,
            dataset_identity="dataset:unsealed",
            universe_id=UNIVERSE_ID,
            cutoff=AS_OF,
            status=SnapshotStatus.COMPLETE,
        )
