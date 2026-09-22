import json
from datetime import date
from pathlib import Path

import pytest

from qhapaq_finance.diamond.cache import DiamondCache
from qhapaq_finance.diamond.contracts import (
    FiscalSlot,
    FundamentalObservation,
    FundamentalPeriodType,
    PeriodKind,
    UnitKind,
)
from qhapaq_finance.diamond.providers.sec_canonical import (
    CANONICAL_SCHEMA_VERSION,
    SEC_CANONICALIZER_VERSION,
    CanonicalIssuerCache,
    CanonicalIssuerSnapshot,
    SecCanonicalError,
)


def sample_snapshot(
    *,
    revision: str = "rev-a",
    version: str = SEC_CANONICALIZER_VERSION,
) -> CanonicalIssuerSnapshot:
    return CanonicalIssuerSnapshot(
        schema_version=CANONICAL_SCHEMA_VERSION,
        canonicalizer_version=version,
        issuer_id="sec-cik:0000320193",
        cik="0000320193",
        as_of=date(2026, 9, 22),
        history_years=5,
        evidence_revision_sha256=revision,
        fundamental_period_type=FundamentalPeriodType.TTM,
        fundamental_period_end=date(2026, 6, 30),
        fiscal_year_end="12-31",
        observations=(
            FundamentalObservation(
                metric_id="revenue",
                fiscal_slot=FiscalSlot.TTM,
                value=110.0,
                period_start=date(2025, 7, 1),
                period_end=date(2026, 6, 30),
                period_kind=PeriodKind.DURATION,
                unit_kind=UnitKind.CURRENCY,
                source_provider="sec",
                source_identity="sec-evidence:rev-a",
            ),
        ),
    )


def test_canonical_cache_round_trips_snapshot(tmp_path: Path) -> None:
    cache = CanonicalIssuerCache(DiamondCache(tmp_path / "canonical"))
    expected = sample_snapshot()

    cache.store(expected)

    actual = cache.load(
        issuer_id=expected.issuer_id,
        as_of=expected.as_of,
        history_years=expected.history_years,
        evidence_revision_sha256=expected.evidence_revision_sha256,
    )

    assert actual == expected
    assert cache.cache_hits == 1
    assert cache.cache_misses == 0


def test_canonicalizer_version_change_is_a_cache_miss(tmp_path: Path) -> None:
    cache = CanonicalIssuerCache(DiamondCache(tmp_path / "canonical"))

    cache.store(sample_snapshot(version="sec-canonicalizer-v1"))

    assert (
        cache.load(
            issuer_id="sec-cik:0000320193",
            as_of=date(2026, 9, 22),
            history_years=5,
            evidence_revision_sha256="rev-a",
        )
        is None
    )
    assert cache.cache_hits == 0
    assert cache.cache_misses == 1


def test_canonical_cache_revision_mismatch_fails_closed(tmp_path: Path) -> None:
    raw = DiamondCache(tmp_path / "canonical")
    cache = CanonicalIssuerCache(raw)
    snapshot = sample_snapshot(revision="rev-a")
    cache.store(snapshot)

    request_identity = cache.request_identity(
        issuer_id=snapshot.issuer_id,
        as_of=snapshot.as_of,
        history_years=5,
        evidence_revision_sha256="rev-a",
    )
    cached = raw.load(request_identity)
    assert cached is not None
    assert isinstance(cached.payload, dict)

    payload = dict(cached.payload)
    payload["evidence_revision_sha256"] = "rev-b"

    raw.store(
        request_identity,
        provider=cache.PROVIDER,
        data_as_of=snapshot.as_of,
        payload=payload,
    )

    with pytest.raises(
        SecCanonicalError,
        match="CANONICAL_CACHE_REVISION_MISMATCH",
    ):
        cache.load(
            issuer_id=snapshot.issuer_id,
            as_of=snapshot.as_of,
            history_years=5,
            evidence_revision_sha256="rev-a",
        )


def test_request_identity_is_deterministic_and_versioned() -> None:
    cache = CanonicalIssuerCache(DiamondCache(Path("/tmp/unused-diamond-cache")))

    first = cache.request_identity(
        issuer_id="sec-cik:0000320193",
        as_of=date(2026, 9, 22),
        history_years=5,
        evidence_revision_sha256="rev-a",
    )
    second = cache.request_identity(
        issuer_id="sec-cik:0000320193",
        as_of=date(2026, 9, 22),
        history_years=5,
        evidence_revision_sha256="rev-a",
    )

    assert first == second
    assert first.startswith("sec-canonical:")


def test_snapshot_payload_does_not_freeze_security_or_ranking_fields(
    tmp_path: Path,
) -> None:
    raw = DiamondCache(tmp_path / "canonical")
    cache = CanonicalIssuerCache(raw)
    snapshot = sample_snapshot()

    cache.store(snapshot)

    identity = cache.request_identity(
        issuer_id=snapshot.issuer_id,
        as_of=snapshot.as_of,
        history_years=snapshot.history_years,
        evidence_revision_sha256=snapshot.evidence_revision_sha256,
    )
    cached = raw.load(identity)
    assert cached is not None

    encoded = json.dumps(cached.payload, sort_keys=True)

    for forbidden in (
        "ticker",
        "market_price",
        "market_cap",
        "market_age_trading_days",
        "sector",
        "gics",
        "percentile",
        "archetype",
        "ranking",
    ):
        assert forbidden not in encoded
