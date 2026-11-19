from __future__ import annotations

import importlib
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from qhapaq_finance.diamond.cache import DiamondCache
from qhapaq_finance.diamond.canonical_json import canonical_json_bytes
from qhapaq_finance.diamond.contracts import FiscalSlot, SecurityRef
from qhapaq_finance.diamond.engine import DiamondResult
from qhapaq_finance.diamond.funnel import FunnelRun, FunnelRunMetadata
from qhapaq_finance.diamond.providers import sec_canonical
from qhapaq_finance.diamond.providers.sec_canonical import CanonicalIssuerCache
from qhapaq_finance.diamond.providers.sec_evidence import SecEvidenceStore
from qhapaq_finance.diamond.snapshot import finalize_snapshot, stage_snapshot
from qhapaq_finance.financial_canonicalization import PeriodKind, RawFact
from qhapaq_finance.sec_client import SecResponse

AS_OF = date(2026, 9, 22)
SOURCE_IDENTITY = f"sec-payload:{'a' * 64}"


def _fact(
    fact_id: str,
    concept: str,
    value: float,
    *,
    start: str | None,
    end: str,
    fiscal_year: int,
    fiscal_period: str,
    form: str,
    accession: str,
    filed: str,
) -> RawFact:
    return RawFact(
        fact_id=fact_id,
        taxonomy="us-gaap",
        concept=concept,
        value=value,
        unit="USD",
        period_kind=PeriodKind.DURATION if start is not None else PeriodKind.INSTANT,
        start=date.fromisoformat(start) if start is not None else None,
        end=date.fromisoformat(end),
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        filing_form=form,
        accession=accession,
        filing_date=date.fromisoformat(filed),
        source_identity=SOURCE_IDENTITY,
    )


def _lineage_facts() -> tuple[RawFact, ...]:
    revenue = "RevenueFromContractWithCustomerExcludingAssessedTax"
    operating_cash_flow = "NetCashProvidedByUsedInOperatingActivities"
    capex = "PaymentsToAcquirePropertyPlantAndEquipment"
    return (
        _fact(
            "revenue-original",
            revenue,
            100.0,
            start="2025-01-01",
            end="2025-12-31",
            fiscal_year=2025,
            fiscal_period="FY",
            form="10-K",
            accession="0000000001-26-000001",
            filed="2026-02-01",
        ),
        _fact(
            "revenue-amendment",
            revenue,
            110.0,
            start="2025-01-01",
            end="2025-12-31",
            fiscal_year=2025,
            fiscal_period="FY",
            form="10-K/A",
            accession="0000000001-26-000002",
            filed="2026-03-01",
        ),
        _fact(
            "revenue-prior-ytd",
            revenue,
            40.0,
            start="2025-01-01",
            end="2025-06-30",
            fiscal_year=2025,
            fiscal_period="Q2",
            form="10-Q",
            accession="0000000001-25-000003",
            filed="2025-08-01",
        ),
        _fact(
            "revenue-current-ytd",
            revenue,
            60.0,
            start="2026-01-01",
            end="2026-06-30",
            fiscal_year=2026,
            fiscal_period="Q2",
            form="10-Q",
            accession="0000000001-26-000004",
            filed="2026-08-01",
        ),
        _fact(
            "ocf-fy",
            operating_cash_flow,
            50.0,
            start="2025-01-01",
            end="2025-12-31",
            fiscal_year=2025,
            fiscal_period="FY",
            form="10-K",
            accession="0000000001-26-000001",
            filed="2026-02-01",
        ),
        _fact(
            "ocf-prior-ytd",
            operating_cash_flow,
            20.0,
            start="2025-01-01",
            end="2025-06-30",
            fiscal_year=2025,
            fiscal_period="Q2",
            form="10-Q",
            accession="0000000001-25-000003",
            filed="2025-08-01",
        ),
        _fact(
            "ocf-current-ytd",
            operating_cash_flow,
            30.0,
            start="2026-01-01",
            end="2026-06-30",
            fiscal_year=2026,
            fiscal_period="Q2",
            form="10-Q",
            accession="0000000001-26-000004",
            filed="2026-08-01",
        ),
        _fact(
            "capex-fy",
            capex,
            -8.0,
            start="2025-01-01",
            end="2025-12-31",
            fiscal_year=2025,
            fiscal_period="FY",
            form="10-K",
            accession="0000000001-26-000001",
            filed="2026-02-01",
        ),
        _fact(
            "capex-prior-ytd",
            capex,
            -4.0,
            start="2025-01-01",
            end="2025-06-30",
            fiscal_year=2025,
            fiscal_period="Q2",
            form="10-Q",
            accession="0000000001-25-000003",
            filed="2025-08-01",
        ),
        _fact(
            "capex-current-ytd",
            capex,
            -6.0,
            start="2026-01-01",
            end="2026-06-30",
            fiscal_year=2026,
            fiscal_period="Q2",
            form="10-Q",
            accession="0000000001-26-000004",
            filed="2026-08-01",
        ),
        _fact(
            "debt-current",
            "LongTermDebtCurrent",
            2.0,
            start=None,
            end="2026-06-30",
            fiscal_year=2026,
            fiscal_period="Q2",
            form="10-Q",
            accession="0000000001-26-000004",
            filed="2026-08-01",
        ),
        _fact(
            "debt-noncurrent",
            "LongTermDebtNoncurrent",
            8.0,
            start=None,
            end="2026-06-30",
            fiscal_year=2026,
            fiscal_period="Q2",
            form="10-Q",
            accession="0000000001-26-000004",
            filed="2026-08-01",
        ),
    )


def test_canonical_lineage_retains_exact_direct_ttm_amendment_and_composite_sources() -> None:
    facts = _lineage_facts()

    traced = sec_canonical.canonicalize_issuer_with_provenance(
        issuer_id="sec-cik:0000000001",
        cik="0000000001",
        as_of=AS_OF,
        history_years=5,
        evidence_revision_sha256="b" * 64,
        facts=facts,
    )

    assert traced is not None
    assert traced.snapshot == sec_canonical.canonicalize_issuer(
        issuer_id="sec-cik:0000000001",
        cik="0000000001",
        as_of=AS_OF,
        history_years=5,
        evidence_revision_sha256="b" * 64,
        facts=facts,
    )
    lineage = {(item.metric_id, item.fiscal_slot): item for item in traced.provenance}

    annual_revenue = lineage[("revenue", FiscalSlot.FY1)]
    assert annual_revenue.derivation_kind == "DIRECT"
    assert tuple(item.fact_id for item in annual_revenue.source_facts) == ("revenue-amendment",)
    assert annual_revenue.source_facts[0].filing_form == "10-K/A"

    ttm_revenue = lineage[("revenue", FiscalSlot.TTM)]
    assert ttm_revenue.derivation_kind == "TTM"
    assert ttm_revenue.formula == "FY - prior comparable YTD + current YTD"
    assert {item.fact_id for item in ttm_revenue.source_facts} == {
        "revenue-amendment",
        "revenue-prior-ytd",
        "revenue-current-ytd",
    }

    total_debt = lineage[("total_debt", FiscalSlot.LATEST)]
    assert total_debt.derivation_kind == "COMPOSITE"
    assert tuple(item.concept for item in total_debt.source_facts) == (
        "LongTermDebtCurrent",
        "LongTermDebtNoncurrent",
    )

    capex = lineage[("capital_expenditures", FiscalSlot.TTM)]
    assert capex.transformations == ("ABSOLUTE_VALUE",)
    assert capex.observation.value == 10.0


def test_canonical_lineage_tracks_fresh_alternative_revenue_ttm_sources() -> None:
    primary = tuple(
        fact
        for fact in _lineage_facts()
        if fact.concept != "RevenueFromContractWithCustomerExcludingAssessedTax"
        or fact.fiscal_period == "FY"
    )
    alternative = (
        _fact(
            "alternative-revenue-fy",
            "Revenues",
            120.0,
            start="2025-01-01",
            end="2025-12-31",
            fiscal_year=2025,
            fiscal_period="FY",
            form="10-K",
            accession="0000000001-26-000001",
            filed="2026-02-01",
        ),
        _fact(
            "alternative-revenue-prior-ytd",
            "Revenues",
            50.0,
            start="2025-01-01",
            end="2025-06-30",
            fiscal_year=2025,
            fiscal_period="Q2",
            form="10-Q",
            accession="0000000001-25-000003",
            filed="2025-08-01",
        ),
        _fact(
            "alternative-revenue-current-ytd",
            "Revenues",
            70.0,
            start="2026-01-01",
            end="2026-06-30",
            fiscal_year=2026,
            fiscal_period="Q2",
            form="10-Q",
            accession="0000000001-26-000004",
            filed="2026-08-01",
        ),
    )
    facts = (*primary, *alternative)

    traced = sec_canonical.canonicalize_issuer_with_provenance(
        issuer_id="sec-cik:0000000001",
        cik="0000000001",
        as_of=AS_OF,
        history_years=5,
        evidence_revision_sha256="b" * 64,
        facts=facts,
        fresh_revenue_from=date(2026, 1, 1),
    )

    assert traced is not None
    assert traced.snapshot == sec_canonical.canonicalize_issuer(
        issuer_id="sec-cik:0000000001",
        cik="0000000001",
        as_of=AS_OF,
        history_years=5,
        evidence_revision_sha256="b" * 64,
        facts=facts,
        fresh_revenue_from=date(2026, 1, 1),
    )
    revenue = next(
        item
        for item in traced.provenance
        if item.metric_id == "revenue" and item.fiscal_slot is FiscalSlot.TTM
    )
    assert revenue.observation.period_end == date(2026, 6, 30)
    assert revenue.observation.value == 140.0
    assert tuple(item.fact_id for item in revenue.source_facts) == (
        "alternative-revenue-fy",
        "alternative-revenue-prior-ytd",
        "alternative-revenue-current-ytd",
    )
    assert {item.concept for item in revenue.source_facts} == {"Revenues"}


class _CompanyFactsClient:
    def __init__(self, payload: dict[str, object]) -> None:
        self.content = canonical_json_bytes(payload)

    def get(
        self,
        url: str,
        *,
        request_headers: dict[str, str] | None = None,
        accepted_statuses: frozenset[int] = frozenset(),
    ) -> SecResponse:
        del url, request_headers, accepted_statuses
        return SecResponse(status_code=200, headers={}, content=self.content)


def _companyfacts_payload(facts: tuple[RawFact, ...]) -> dict[str, object]:
    concepts: dict[str, dict[str, object]] = {}
    for fact in facts:
        detail = concepts.setdefault(fact.concept, {"label": fact.concept, "units": {}})
        units = cast(dict[str, list[dict[str, object]]], detail["units"])
        row: dict[str, object] = {
            "end": fact.end.isoformat(),
            "val": fact.value,
            "accn": fact.accession,
            "fy": fact.fiscal_year,
            "fp": fact.fiscal_period,
            "form": fact.filing_form,
            "filed": fact.filing_date.isoformat(),
            "frame": f"CY{fact.end.year}",
        }
        if fact.start is not None:
            row["start"] = fact.start.isoformat()
        units.setdefault(fact.unit, []).append(row)
    return {"cik": 1, "entityName": "Example", "facts": {"us-gaap": concepts}}


def _snapshot_replay(dataset_identity: str) -> FunnelRun:
    security = SecurityRef("EXM", "sp500:EXM", "sec-cik:0000000001")
    result = SimpleNamespace(
        archetypes=SimpleNamespace(research_priority=1.0),
        source_security=security,
        data_as_of=AS_OF,
    )
    typed = cast(tuple[DiamondResult, ...], (result,))
    return FunnelRun(
        results=typed,
        metadata=FunnelRunMetadata(
            universe_count=1,
            canonical_records=1,
            ranked_records=1,
            unranked_records=0,
            provider_requests=0,
            cache_hits=1,
            cache_misses=0,
            acquisition_seconds=0.0,
            evaluation_seconds=0.0,
            dataset_identity=dataset_identity,
        ),
        evaluated_results=typed,
    )


def _audit_fixture(tmp_path: Path, *, canonical_mismatch: bool = False) -> tuple[Path, Path]:
    source = tmp_path / "source"
    facts_payload = _companyfacts_payload(_lineage_facts())
    evidence_store = SecEvidenceStore(
        root=source / "sec",
        client=_CompanyFactsClient(facts_payload),
        legacy_cache=None,
    )
    resolved = evidence_store.resolve("0000000001", AS_OF)
    facts = evidence_store.load_facts(resolved.manifest)
    canonical = sec_canonical.canonicalize_issuer(
        issuer_id="sec-cik:0000000001",
        cik="0000000001",
        as_of=AS_OF,
        history_years=5,
        evidence_revision_sha256=resolved.manifest.evidence_revision_sha256,
        facts=facts,
    )
    assert canonical is not None
    if canonical_mismatch:
        first = replace(canonical.observations[0], value=canonical.observations[0].value + 1.0)
        canonical = replace(canonical, observations=(first, *canonical.observations[1:]))
    CanonicalIssuerCache(DiamondCache(source / "canonical")).store(canonical)

    selected_paths = tuple(path for path in source.rglob("*.json") if path.is_file())
    replay = _snapshot_replay("d" * 64)
    staged = stage_snapshot(
        source_root=source,
        snapshot_root=tmp_path / "snapshot",
        selected_paths=selected_paths,
        universe_id="sp500",
        cutoff=AS_OF,
        source_run=replay,
    )
    snapshot = finalize_snapshot(staged, replay=replay)

    observations = {(item.metric_id, item.fiscal_slot): item for item in canonical.observations}

    def evidence(metric_id: str, slot: FiscalSlot) -> dict[str, object]:
        item = observations[(metric_id, slot)]
        return {
            "evidence_id": f"{metric_id}:{slot.value}:{item.period_end.isoformat()}",
            "metric_id": metric_id,
            "fiscal_slot": slot.value,
            "value": item.value,
            "unit_kind": item.unit_kind.value,
            "period_kind": item.period_kind.value,
            "period_start": item.period_start.isoformat() if item.period_start else None,
            "period_end": item.period_end.isoformat(),
            "source_provider": "sec",
            "source_identity": item.source_identity,
        }

    report = {
        "dataset_identity": snapshot.dataset_identity,
        "snapshot": {"snapshot_id": snapshot.snapshot_id},
        "candidate_set": {"candidate_set_id": "candidate-set:test"},
        "opportunities": [
            {
                "rank": 1,
                "ticker": "EXM",
                "issuer_id": "sec-cik:0000000001",
                "sec_provenance": {
                    "cik": "0000000001",
                    "payload_sha256": resolved.manifest.payload_sha256,
                    "evidence_revision_sha256": resolved.manifest.evidence_revision_sha256,
                },
                "evidence": [
                    evidence("revenue", FiscalSlot.FY1),
                    evidence("revenue", FiscalSlot.TTM),
                    {
                        "evidence_id": "market_cap:LATEST:2026-09-21",
                        "metric_id": "market_cap",
                        "fiscal_slot": "LATEST",
                        "value": 123.0,
                        "unit_kind": "currency",
                        "period_kind": "instant",
                        "period_start": None,
                        "period_end": "2026-09-21",
                        "source_provider": "yahoo-finance",
                        "source_identity": "e" * 64,
                    },
                ],
            }
        ],
    }
    report_path = tmp_path / "opportunities.json"
    report_path.write_bytes(canonical_json_bytes(report) + b"\n")
    return snapshot.root, report_path


def test_locator_matrix_replays_exact_sources_and_reconciles_coverage(tmp_path: Path) -> None:
    module = importlib.import_module("qhapaq_finance.sec_locator")
    snapshot_root, report_path = _audit_fixture(tmp_path)

    matrix = module.build_sec_locator_matrix(
        snapshot_root=snapshot_root,
        opportunities_path=report_path,
    )
    observations = matrix["observations"]

    assert matrix["schema_version"] == "qhapaq-sec-locator-matrix-v1"
    assert matrix["summary"]["total_observations"] == 3
    assert matrix["summary"]["by_status"] == {
        "AMBIGUOUS": 0,
        "EVIDENCE_MISSING": 1,
        "EXACT_FILING_MATCH": 2,
        "ISSUER_LEVEL_ONLY": 0,
    }
    by_id = {item["evidence_id"]: item for item in observations}
    annual = by_id["revenue:FY1:2025-12-31"]
    ttm = by_id["revenue:TTM:2026-06-30"]
    market = by_id["market_cap:LATEST:2026-09-21"]
    assert annual["classification"] == "EXACT_FILING_MATCH"
    assert annual["source_facts"][0]["form"] == "10-K/A"
    assert annual["source_facts"][0]["companyfacts_json_pointer"].startswith("/facts/")
    assert ttm["derivation"]["kind"] == "TTM"
    assert len(ttm["source_facts"]) == 3
    assert market["classification"] == "EVIDENCE_MISSING"
    assert market["reason"] == "NOT_SEC_FILING_METRIC"
    assert module.sec_locator_matrix_json(matrix) == module.sec_locator_matrix_json(matrix)


def test_locator_matrix_fails_closed_when_canonical_replay_differs(tmp_path: Path) -> None:
    module = importlib.import_module("qhapaq_finance.sec_locator")
    snapshot_root, report_path = _audit_fixture(tmp_path, canonical_mismatch=True)

    try:
        module.build_sec_locator_matrix(
            snapshot_root=snapshot_root,
            opportunities_path=report_path,
        )
    except module.SecLocatorAuditError as exc:
        assert str(exc) == "CANONICAL_REPLAY_MISMATCH"
    else:  # pragma: no cover - documents the fail-closed requirement
        raise AssertionError("canonical mismatch was accepted")
