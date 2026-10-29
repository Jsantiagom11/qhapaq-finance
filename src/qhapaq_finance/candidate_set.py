"""Exact, deterministic selection boundary over authoritative Diamond results."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from string import hexdigits

from qhapaq_finance.diamond.canonical_json import sha256_canonical_json
from qhapaq_finance.diamond.contracts import SecurityRef
from qhapaq_finance.diamond.funnel import FunnelRun
from qhapaq_finance.string_enum import StringEnum

CANDIDATE_SET_SCHEMA_VERSION = "candidate-set-v1"
CANDIDATE_SET_CANONICALIZER_VERSION = "candidate-set-canonicalizer-v1"


class CandidateSetError(ValueError):
    """Raised when a CandidateSet input violates its fail-closed contract."""


class SnapshotStatus(StringEnum):
    """Completeness state declared by the referenced Diamond snapshot."""

    INCOMPLETE = "INCOMPLETE"
    COMPLETE = "COMPLETE"


def _text(value: str, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CandidateSetError(code)
    return value.strip()


def _sha256(value: str, code: str) -> str:
    normalized = _text(value, code)
    if (
        len(normalized) != 64
        or normalized != normalized.lower()
        or any(character not in hexdigits for character in normalized)
    ):
        raise CandidateSetError(code)
    return normalized


def _positive_integer(value: int, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CandidateSetError(code)
    return value


@dataclass(frozen=True, slots=True)
class DiamondSnapshotRef:
    """Identity and temporal context of one immutable Diamond snapshot."""

    snapshot_id: str
    dataset_identity: str
    universe_id: str
    cutoff: date
    status: SnapshotStatus

    def __post_init__(self) -> None:
        object.__setattr__(self, "snapshot_id", _text(self.snapshot_id, "SNAPSHOT_ID_REQUIRED"))
        object.__setattr__(
            self,
            "dataset_identity",
            _sha256(self.dataset_identity, "DATASET_IDENTITY_INVALID"),
        )
        object.__setattr__(self, "universe_id", _text(self.universe_id, "UNIVERSE_ID_REQUIRED"))
        if not isinstance(self.cutoff, date):
            raise CandidateSetError("CUTOFF_INVALID")
        if not isinstance(self.status, SnapshotStatus):
            raise CandidateSetError("SNAPSHOT_STATUS_INVALID")


@dataclass(frozen=True, slots=True)
class DiamondTopNPolicy:
    """Select the first N entries from Diamond's authoritative result sequence."""

    limit: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "limit",
            _positive_integer(self.limit, "SELECTION_LIMIT_INVALID"),
        )


@dataclass(frozen=True, slots=True)
class Candidate:
    """One exact Diamond-selected security without financial calculations."""

    security: SecurityRef
    diamond_rank: int
    selection_order: int

    def __post_init__(self) -> None:
        if not isinstance(self.security, SecurityRef):
            raise CandidateSetError("SECURITY_REF_REQUIRED")
        object.__setattr__(
            self,
            "diamond_rank",
            _positive_integer(self.diamond_rank, "DIAMOND_RANK_INVALID"),
        )
        object.__setattr__(
            self,
            "selection_order",
            _positive_integer(self.selection_order, "SELECTION_ORDER_INVALID"),
        )


@dataclass(frozen=True, slots=True)
class CandidateSet:
    """Versioned selection bound to one Diamond dataset and snapshot reference."""

    snapshot: DiamondSnapshotRef
    policy: DiamondTopNPolicy
    candidates: tuple[Candidate, ...]
    candidate_set_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, DiamondSnapshotRef):
            raise CandidateSetError("SNAPSHOT_REF_REQUIRED")
        if not isinstance(self.policy, DiamondTopNPolicy):
            raise CandidateSetError("SELECTION_POLICY_REQUIRED")

        candidates = tuple(self.candidates)
        if len(candidates) != self.policy.limit:
            raise CandidateSetError("SELECTION_COUNT_MISMATCH")

        seen_security_ids: dict[str, SecurityRef] = {}
        for expected_order, candidate in enumerate(candidates, start=1):
            if not isinstance(candidate, Candidate):
                raise CandidateSetError("CANDIDATE_INVALID")
            if candidate.diamond_rank != expected_order:
                raise CandidateSetError("DIAMOND_RANK_SEQUENCE_INVALID")
            if candidate.selection_order != expected_order:
                raise CandidateSetError("SELECTION_ORDER_SEQUENCE_INVALID")

            previous = seen_security_ids.get(candidate.security.security_id)
            if previous is not None:
                raise CandidateSetError("SECURITY_IDENTITY_CONFLICT")
            seen_security_ids[candidate.security.security_id] = candidate.security

        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "candidate_set_id", candidate_set_identity(self))

    @property
    def dataset_identity(self) -> str:
        return self.snapshot.dataset_identity

    @property
    def universe_id(self) -> str:
        return self.snapshot.universe_id

    @property
    def cutoff(self) -> date:
        return self.snapshot.cutoff

    @property
    def production_reproducible(self) -> bool:
        return self.snapshot.status is SnapshotStatus.COMPLETE

    def require_production_reproducible(self) -> None:
        """Fail closed unless the referenced snapshot is declared complete."""
        if not self.production_reproducible:
            raise CandidateSetError("SNAPSHOT_NOT_COMPLETE")


def _candidate_set_payload(candidate_set: CandidateSet) -> dict[str, object]:
    return {
        "schema_version": CANDIDATE_SET_SCHEMA_VERSION,
        "canonicalizer_version": CANDIDATE_SET_CANONICALIZER_VERSION,
        "snapshot": {
            "snapshot_id": candidate_set.snapshot.snapshot_id,
            "dataset_identity": candidate_set.snapshot.dataset_identity,
            "universe_id": candidate_set.snapshot.universe_id,
            "cutoff": candidate_set.snapshot.cutoff.isoformat(),
            "status": candidate_set.snapshot.status.value,
        },
        "policy": {
            "kind": "DIAMOND_TOP_N",
            "limit": candidate_set.policy.limit,
        },
        "candidates": [
            {
                "security": {
                    "ticker": candidate.security.ticker,
                    "security_id": candidate.security.security_id,
                    "issuer_id": candidate.security.issuer_id,
                },
                "diamond_rank": candidate.diamond_rank,
                "selection_order": candidate.selection_order,
            }
            for candidate in candidate_set.candidates
        ],
    }


def candidate_set_identity(candidate_set: CandidateSet) -> str:
    """Recompute the canonical identity of a CandidateSet."""
    return sha256_canonical_json(_candidate_set_payload(candidate_set))


def build_candidate_set(
    funnel: FunnelRun,
    *,
    snapshot: DiamondSnapshotRef,
    universe_id: str,
    cutoff: date,
    policy: DiamondTopNPolicy,
) -> CandidateSet:
    """Copy an exact Diamond Top-N into a verifiable CandidateSet without re-ranking."""
    normalized_universe = _text(universe_id, "UNIVERSE_ID_REQUIRED")
    if not isinstance(cutoff, date):
        raise CandidateSetError("CUTOFF_INVALID")
    if snapshot.dataset_identity != funnel.metadata.dataset_identity:
        raise CandidateSetError("SNAPSHOT_DATASET_MISMATCH")
    if snapshot.universe_id != normalized_universe:
        raise CandidateSetError("SNAPSHOT_UNIVERSE_MISMATCH")
    if snapshot.cutoff != cutoff:
        raise CandidateSetError("SNAPSHOT_CUTOFF_MISMATCH")
    if policy.limit > len(funnel.results) or policy.limit > funnel.metadata.ranked_records:
        raise CandidateSetError("SELECTION_EXCEEDS_DIAMOND_RESULTS")

    candidates: list[Candidate] = []
    for diamond_rank, result in enumerate(funnel.results[: policy.limit], start=1):
        if result.data_as_of != cutoff:
            raise CandidateSetError("RESULT_CUTOFF_MISMATCH")
        if result.archetypes.research_priority is None or result.archetypes.surfaced_by is None:
            raise CandidateSetError("DIAMOND_RESULT_UNRANKABLE")
        if result.source_security is None:
            raise CandidateSetError("SOURCE_SECURITY_REQUIRED")
        if result.source_security.ticker != result.ticker:
            raise CandidateSetError("SOURCE_SECURITY_TICKER_MISMATCH")

        candidates.append(
            Candidate(
                security=result.source_security,
                diamond_rank=diamond_rank,
                selection_order=len(candidates) + 1,
            )
        )

    return CandidateSet(
        snapshot=snapshot,
        policy=policy,
        candidates=tuple(candidates),
    )


__all__ = [
    "CANDIDATE_SET_CANONICALIZER_VERSION",
    "CANDIDATE_SET_SCHEMA_VERSION",
    "Candidate",
    "CandidateSet",
    "CandidateSetError",
    "DiamondSnapshotRef",
    "DiamondTopNPolicy",
    "SnapshotStatus",
    "build_candidate_set",
    "candidate_set_identity",
]
