from __future__ import annotations

from pathlib import Path

import pytest

from qhapaq_finance.candidate_set import (
    CandidateSetError,
    DiamondSnapshotRef,
    DiamondTopNPolicy,
    SnapshotStatus,
    build_candidate_set,
)
from qhapaq_finance.diamond.funnel import run_funnel
from qhapaq_finance.diamond.providers.local import LocalJsonProvider

pytestmark = pytest.mark.integration

DIAMOND_FIXTURE = Path("tests/fixtures/diamond/minimal-universe.json")
EXPECTED_DATASET_IDENTITY = "493294e65e40ea12a3cc96abcee9fb9d6d49ff2e2c29e83da51e8991e91431ff"


def test_frozen_diamond_top_three_becomes_exact_incomplete_candidate_set() -> None:
    provider = LocalJsonProvider(DIAMOND_FIXTURE)
    funnel = run_funnel(
        provider,
        universe_id=provider.universe_id,
        as_of=provider.data_as_of,
        depth=5,
    )
    snapshot = DiamondSnapshotRef(
        snapshot_id="fixture:diamond/minimal-universe.json",
        dataset_identity=funnel.metadata.dataset_identity,
        universe_id=provider.universe_id,
        cutoff=provider.data_as_of,
        status=SnapshotStatus.INCOMPLETE,
    )

    candidate_set = build_candidate_set(
        funnel,
        snapshot=snapshot,
        universe_id=provider.universe_id,
        cutoff=provider.data_as_of,
        policy=DiamondTopNPolicy(limit=3),
    )

    assert candidate_set.dataset_identity == EXPECTED_DATASET_IDENTITY
    assert [candidate.security.ticker for candidate in candidate_set.candidates] == [
        "T19",
        "T18",
        "T17",
    ]
    assert [candidate.diamond_rank for candidate in candidate_set.candidates] == [1, 2, 3]
    assert [candidate.selection_order for candidate in candidate_set.candidates] == [1, 2, 3]
    assert [candidate.security.security_id for candidate in candidate_set.candidates] == [
        "issuer-t19:T19",
        "issuer-t18:T18",
        "issuer-t17:T17",
    ]
    assert candidate_set.production_reproducible is False
    with pytest.raises(CandidateSetError, match="SNAPSHOT_NOT_COMPLETE"):
        candidate_set.require_production_reproducible()
