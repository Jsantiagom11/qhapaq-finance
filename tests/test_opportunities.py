from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from qhapaq_finance.diamond.contracts import FundamentalRecord, Methodology, SecurityRef
from qhapaq_finance.diamond.funnel import run_funnel
from qhapaq_finance.diamond.providers.sec_evidence import SecEvidenceManifest
from qhapaq_finance.diamond.snapshot import finalize_snapshot, stage_snapshot
from qhapaq_finance.opportunities import (
    OpportunityReportError,
    build_opportunity_report,
    focus_opportunity,
    opportunity_report_json,
    opportunity_report_markdown,
)

try:
    from tests.diamond_helpers import AS_OF, rich_record
except ModuleNotFoundError:
    from diamond_helpers import AS_OF, rich_record


class _Provider:
    provider_requests = 0
    cache_hits = 0
    cache_misses = 0

    def __init__(self, records: tuple[FundamentalRecord, ...]) -> None:
        self.records = records
        self.securities = tuple(
            SecurityRef(record.ticker, record.security_id, record.issuer_id) for record in records
        )

    def universe(self, universe_id: str, as_of: date) -> tuple[SecurityRef, ...]:
        assert universe_id == "sp500"
        assert as_of == AS_OF
        return self.securities

    def fundamentals(
        self,
        securities: tuple[SecurityRef, ...],
        as_of: date,
        history_years: int = 5,
    ) -> tuple[FundamentalRecord, ...]:
        assert securities == self.securities
        assert as_of == AS_OF
        assert history_years == 5
        return self.records


def _records() -> tuple[FundamentalRecord, ...]:
    records: list[FundamentalRecord] = []
    for index in range(20):
        ticker = f"T{index:02d}"
        record = rich_record(
            ticker,
            scale=1.0 + index * 0.03,
            growth=0.04 + index * 0.003,
            op_margin=0.15 + index * 0.004,
            fcf_margin=0.10 + index * 0.003,
            dilution=-0.005 + index * 0.0004,
            recent_share_change=-0.01 + index * 0.001,
            methodology=(
                Methodology.UNSUPPORTED_FINANCIAL if index == 0 else Methodology.OPERATING_COMPANY
            ),
        )
        cik = f"{index + 1:010d}"
        records.append(
            replace(
                record,
                issuer_id=f"sec-cik:{cik}",
                security_id=f"sec-cik:{cik}:{ticker}",
            )
        )
    return tuple(records)


def _manifest(cik: str) -> SecEvidenceManifest:
    return SecEvidenceManifest(
        schema_version="diamond-sec-evidence-v1",
        cik=cik,
        request_identity=(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"),
        retrieved_at=datetime(2026, 9, 22, tzinfo=timezone.utc),
        data_as_of=AS_OF,
        payload_sha256="b" * 64,
        evidence_revision_sha256="c" * 64,
        latest_in_scope_filing_date=date(2026, 8, 1),
        latest_in_scope_accession="0000000001-26-000001",
        etag=None,
        last_modified=None,
        blob_name=f"{'b' * 64}.json",
    )


@pytest.fixture()
def report_context(tmp_path: Path):
    records = _records()
    funnel = run_funnel(
        _Provider(records),
        universe_id="sp500",
        as_of=AS_OF,
        depth=100,
    )
    source = tmp_path / "source"
    evidence = source / "universe" / "evidence.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("{}\n", encoding="utf-8")
    staged = stage_snapshot(
        source_root=source,
        snapshot_root=tmp_path / "snapshot",
        selected_paths=(evidence,),
        universe_id="sp500",
        cutoff=AS_OF,
        source_run=funnel,
    )
    snapshot = finalize_snapshot(
        staged,
        replay=funnel,
    )
    manifests = tuple(_manifest(record.issuer_id.removeprefix("sec-cik:")) for record in records)
    return funnel, snapshot, manifests


def test_funnel_preserves_source_records_and_all_evaluated_results() -> None:
    records = _records()
    funnel = run_funnel(
        _Provider(records),
        universe_id="sp500",
        as_of=AS_OF,
        depth=3,
    )

    assert funnel.records == records
    assert len(funnel.results) == 3
    assert len(funnel.evaluated_results) == len(records)


def test_report_preserves_exact_diamond_candidate_order_and_identity(
    report_context,
) -> None:
    funnel, snapshot, manifests = report_context
    report = build_opportunity_report(
        funnel,
        snapshot=snapshot,
        top=10,
        sec_manifests=manifests,
    )
    payload = report.to_dict()

    expected = [item.ticker for item in funnel.results[:10]]
    assert [item["ticker"] for item in payload["opportunities"]] == expected
    assert [
        item["security"]["ticker"] for item in payload["candidate_set"]["candidates"]
    ] == expected
    assert payload["candidate_set"]["snapshot"]["snapshot_id"] == snapshot.snapshot_id
    assert payload["candidate_set"]["candidate_set_id"]
    assert payload["snapshot"]["coverage"] == {
        "canonical_records": 20,
        "rankable_records": 19,
        "universe_securities": 20,
        "unrankable_records": 1,
    }


def test_report_never_pads_and_explains_nonexclusive_exclusions(
    report_context,
) -> None:
    funnel, snapshot, manifests = report_context
    report = build_opportunity_report(
        funnel,
        snapshot=snapshot,
        top=25,
        sec_manifests=manifests,
    ).to_dict()

    assert report["summary"]["requested_count"] == 25
    assert report["summary"]["selected_count"] == 19
    assert report["summary"]["eligible_count"] == 19
    assert report["summary"]["excluded_count"] == 1
    assert report["summary"]["selection_shortfall"] == 6
    assert report["exclusions"]["reason_counts"]["UNSUPPORTED_METHODOLOGY"] == 1
    assert report["exclusions"]["reason_counts"]["NO_RESEARCH_PRIORITY"] == 1
    assert report["blocked_companies"][0]["ticker"] == "T00"


def test_candidate_explanation_separates_epistemic_classes_and_evidence(
    report_context,
) -> None:
    funnel, snapshot, manifests = report_context
    candidate = build_opportunity_report(
        funnel,
        snapshot=snapshot,
        top=3,
        sec_manifests=manifests,
    ).to_dict()["opportunities"][0]

    assert candidate["determinant_factors"]
    assert candidate["risks_and_weaknesses"]
    assert candidate["evidence"]
    assert set(candidate["epistemic"]) == {
        "verified_facts",
        "derived_metrics",
        "inferences",
        "assumptions",
        "insufficient_data",
    }
    assert candidate["financial_period"]["period_type"] == "TTM"
    assert candidate["financial_period"]["period_end"] <= AS_OF.isoformat()
    assert all(item["period_end"] <= AS_OF.isoformat() for item in candidate["evidence"])
    assert all(item["publication_date"] is None for item in candidate["evidence"])
    assert candidate["sec_provenance"]["scope"] == "ISSUER_LEVEL_ONLY"
    assert candidate["sec_provenance"]["latest_in_scope_accession"]
    assert "not an exact per-metric locator" in candidate["sec_provenance"]["warning"]


def test_serialization_and_focused_projection_are_deterministic(report_context) -> None:
    funnel, snapshot, manifests = report_context
    report = build_opportunity_report(
        funnel,
        snapshot=snapshot,
        top=3,
        sec_manifests=manifests,
    )

    first_json = opportunity_report_json(report)
    second_json = opportunity_report_json(report)
    first_markdown = opportunity_report_markdown(report)
    second_markdown = opportunity_report_markdown(report)

    assert first_json == second_json
    assert first_markdown == second_markdown
    assert "not an investment recommendation" in first_markdown
    assert report.to_dict()["integrity_status"] == "PARTIAL_POINT_IN_TIME"
    assert any(
        "membership-effective-dated" in item for item in report.to_dict()["global_limitations"]
    )
    ticker = report.to_dict()["opportunities"][0]["ticker"]
    focused = focus_opportunity(report, ticker)
    assert focused["ticker"] == ticker
    assert focused["why_selected"]
    assert focused["next_research_questions"]

    with pytest.raises(OpportunityReportError, match="OPPORTUNITY_NOT_FOUND"):
        focus_opportunity(report, "MISSING")
