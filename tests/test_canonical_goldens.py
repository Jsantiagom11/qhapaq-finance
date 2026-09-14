"""Source-led golden validation and deliberately independent engine comparison."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

_AUDIT_SPEC = importlib.util.spec_from_file_location(
    "canonical_golden_audit", Path("tools/build_canonical_goldens.py")
)
assert _AUDIT_SPEC and _AUDIT_SPEC.loader
_AUDIT = importlib.util.module_from_spec(_AUDIT_SPEC)
_AUDIT_SPEC.loader.exec_module(_AUDIT)
build = _AUDIT.build

CORPUS = Path("tests/fixtures/sec_corpus")
GOLDENS = Path("tests/fixtures/canonical_goldens/v1")


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text())


def test_v1_goldens_are_immutable_and_reproducible_from_frozen_evidence() -> None:
    """The independent audit utility verifies hashes, filing XBRL, and facts."""
    before = {path: path.read_bytes() for path in GOLDENS.glob("*.json")}
    build()
    assert {path: path.read_bytes() for path in GOLDENS.glob("*.json")} == before


def test_golden_manifest_hashes_every_issuer_golden() -> None:
    manifest = _load(GOLDENS / "manifest.json")
    assert (
        manifest["sec_corpus_root_manifest_sha256"]
        == hashlib.sha256((CORPUS / "manifest.json").read_bytes()).hexdigest()
    )
    entries = manifest["issuer_goldens"]
    assert [entry["ticker"] for entry in entries] == sorted(entry["ticker"] for entry in entries)
    for entry in entries:
        assert hashlib.sha256((GOLDENS / entry["path"]).read_bytes()).hexdigest() == entry["sha256"]


@pytest.mark.parametrize("ticker", ("AAPL", "QCOM", "NVDA", "COST", "AMZN", "VRTX"))
def test_every_referenced_artifact_is_in_its_issuer_manifest(ticker: str) -> None:
    golden = _load(GOLDENS / f"{ticker}.json")
    issuer = _load(CORPUS / ticker / "manifest.json")
    artifacts = {item["path"]: item for item in issuer["artifacts"]}
    for metric in golden["metrics"]:
        path = metric["source_artifact_path"]
        record = artifacts[path]
        assert record["sha256"] == metric["source_artifact_sha256"]
        assert (CORPUS / ticker / path).is_file()
        assert record["accession"] == metric["source_accession"]
        assert record["form"] == metric["filing_form"]
        assert record["report_date"] == metric["report_date"]


@pytest.fixture(scope="module")
def engine_outputs() -> dict[str, object]:
    """Run production once per issuer; it is a comparison target only."""
    from qhapaq_finance.financial_canonicalization import CanonicalizationEngine, classify_issuer

    outputs: dict[str, object] = {}
    for ticker in ("AAPL", "QCOM", "NVDA", "COST", "AMZN", "VRTX"):
        companyfacts_path = CORPUS / ticker / "companyfacts.json"
        issuer_manifest = _load(CORPUS / ticker / "manifest.json")
        outputs[ticker] = CanonicalizationEngine().canonicalize(
            None,
            {
                "companyfacts": _load(companyfacts_path),
                "selected_filing": issuer_manifest["selected_filings"]["10-K"],
            },
            profile=classify_issuer(sic=3570),
            source_identity=hashlib.sha256(companyfacts_path.read_bytes()).hexdigest(),
        )
    return outputs


_KNOWN_NON_PERIOD_MISMATCHES = {
    ("AAPL", "total_debt"): "DERIVATION: no approved total-debt derivation",
    ("QCOM", "total_debt"): "DERIVATION: current debt is not total debt",
    ("NVDA", "total_debt"): "DERIVATION: current debt is not total debt",
    ("COST", "total_debt"): "DERIVATION: current debt is not total debt",
    ("AMZN", "total_debt"): "DERIVATION: total-debt ambiguity policy is not implemented",
}


def _comparison_parameter(ticker: str, metric: str) -> object:
    reason = _KNOWN_NON_PERIOD_MISMATCHES.get((ticker, metric))
    return (
        pytest.param(ticker, metric, marks=pytest.mark.xfail(strict=True, reason=reason))
        if reason
        else pytest.param(ticker, metric)
    )


# Only independently classified, non-period mismatches remain strict xfails.
# A fixed period-selection regression is an ordinary passing assertion.
@pytest.mark.parametrize(
    ("ticker", "metric"),
    [
        _comparison_parameter(ticker, metric)
        for ticker in ("AAPL", "QCOM", "NVDA", "COST", "AMZN", "VRTX")
        for metric in (
            "revenue",
            "operating_income",
            "net_income",
            "cash_and_equivalents",
            "total_debt",
            "total_assets",
            "total_liabilities",
            "shareholders_equity",
            "diluted_shares",
        )
    ],
)
def test_engine_matches_independently_established_golden(
    ticker: str, metric: str, engine_outputs: dict[str, object]
) -> None:
    golden = _load(GOLDENS / f"{ticker}.json")
    expected = next(item for item in golden["metrics"] if item["metric"] == metric)
    actual = engine_outputs[ticker].metrics[metric]
    assert actual.decision.status.value == expected["expected_status"]
    if expected["expected_status"] != "RESOLVED":
        return
    assert actual.normalized_value == expected["expected_normalized_value"]
    assert actual.normalized_unit == expected["normalized_unit"]
    assert actual.raw_fact is not None
    assert actual.raw_fact.accession == expected["source_accession"]
    assert actual.raw_fact.concept == expected["source_concept_qname"].split(":", 1)[1]
    assert actual.raw_fact.end.isoformat() == expected["report_date"]
    assert actual.raw_fact.filing_form == expected["filing_form"]
    if "start_date" in expected["period"]:
        assert actual.raw_fact.start is not None
        assert actual.raw_fact.start.isoformat() == expected["period"]["start_date"]
    assert actual.raw_fact.source_identity == expected["companyfacts_corroboration"]["sha256"]
    if "expected_resolution_method" in expected:
        assert actual.decision.method.value == expected["expected_resolution_method"]
