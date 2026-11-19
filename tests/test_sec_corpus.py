from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

import qhapaq_finance.sec_corpus as sec_corpus
from qhapaq_finance.analysis import CompanyIdentity
from qhapaq_finance.sec_acquisition import ImmutableArtifactConflictError
from qhapaq_finance.sec_client import SecResponse
from qhapaq_finance.sec_evidence_provider import StructuredSecProvider

_CORPUS_TICKERS = ("AAPL", "QCOM", "NVDA", "COST", "AMZN", "VRTX")
_CORPUS_CIKS = {
    "AAPL": "0000320193",
    "QCOM": "0000804328",
    "NVDA": "0001045810",
    "COST": "0000909832",
    "AMZN": "0001018724",
    "VRTX": "0000875320",
}


def _write_issuer(root: Path, ticker: str) -> Path:
    cik = _CORPUS_CIKS[ticker]
    issuer_root = root / ticker
    issuer_root.mkdir(parents=True)
    records: dict[str, dict[str, Any]] = {}
    for kind in ("submissions", "companyfacts"):
        content = f"{ticker}-{kind}".encode()
        path = issuer_root / f"{kind}.json"
        path.write_bytes(content)
        records[kind] = {
            "ticker": ticker,
            "cik": cik,
            "path": path.name,
            "sha256": hashlib.sha256(content).hexdigest(),
            "byte_size": len(content),
        }
    manifest = {
        "schema_version": "sec-corpus-issuer-v1",
        "ticker": ticker,
        "cik": cik,
        "submissions": records["submissions"],
        "companyfacts": records["companyfacts"],
        "artifacts": [],
        "selected_filings": {
            "10-K": {"form": "10-K", "accession": f"{cik}-25-000001"},
            "10-Q": {"form": "10-Q", "accession": f"{cik}-26-000001"},
        },
    }
    manifest_path = issuer_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    return manifest_path


def _write_six_issuers(root: Path) -> None:
    for ticker in _CORPUS_TICKERS:
        _write_issuer(root, ticker)


def test_existing_identical_corpus_artifact_is_reused(tmp_path: Path) -> None:
    artifact = tmp_path / "AAPL" / "submissions.json"
    sec_corpus._export_immutable(artifact, b'{"cik":"0000320193"}')
    sec_corpus._export_immutable(artifact, b'{"cik":"0000320193"}')

    assert artifact.read_bytes() == b'{"cik":"0000320193"}'


def test_conflicting_existing_corpus_artifact_is_preserved(tmp_path: Path) -> None:
    artifact = tmp_path / "AAPL" / "submissions.json"
    sec_corpus._export_immutable(artifact, b"first")

    with pytest.raises(ImmutableArtifactConflictError, match="refusing to overwrite"):
        sec_corpus._export_immutable(artifact, b"second")

    assert artifact.read_bytes() == b"first"


def test_repeated_corpus_export_keeps_manifests_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    submissions: dict[str, Any] = {
        "cik": "0000320193",
        "tickers": ["AAPL"],
        "filings": {
            "recent": {
                "accessionNumber": [],
                "form": [],
                "filingDate": [],
                "reportDate": [],
                "primaryDocument": [],
            }
        },
    }
    facts: dict[str, Any] = {"cik": "0000320193", "facts": {}}

    def fake_fetch(
        client: object, staging: Path, issuer: Path, ticker: str, cik: str, kind: str, url: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        del client, staging, issuer, ticker, cik, url
        payload = submissions if kind == "submissions" else facts
        return payload, {"artifact_kind": kind, "sha256": kind, "fetched_at": "first-fetch"}

    monkeypatch.setattr(sec_corpus, "_fetch_json", fake_fetch)
    first = sec_corpus.build_sec_corpus(
        object(),
        corpus_root=tmp_path / "corpus",
        staging_root=tmp_path / "staging",
        tickers=("AAPL",),
    )
    manifest_path = tmp_path / "corpus" / "manifest.json"
    issuer_manifest = tmp_path / "corpus" / "AAPL" / "manifest.json"
    first_bytes = (manifest_path.read_bytes(), issuer_manifest.read_bytes())

    second = sec_corpus.build_sec_corpus(
        object(),
        corpus_root=tmp_path / "corpus",
        staging_root=tmp_path / "staging",
        tickers=("AAPL",),
    )

    assert second == first
    assert (manifest_path.read_bytes(), issuer_manifest.read_bytes()) == first_bytes
    assert json.loads(manifest_path.read_text())["created_at"] == first["created_at"]


def test_reconciliation_registers_all_six_validated_issuers(tmp_path: Path) -> None:
    _write_six_issuers(tmp_path)

    manifest = sec_corpus.reconcile_sec_corpus_manifest(corpus_root=tmp_path)

    assert manifest["schema_version"] == "sec-corpus-v2"
    assert [entry["ticker"] for entry in manifest["issuers"]] == list(_CORPUS_TICKERS)
    assert all(entry["artifact_count"] == 2 for entry in manifest["issuers"])
    assert all(len(entry["issuer_manifest_sha256"]) == 64 for entry in manifest["issuers"])


def test_reconciliation_rejects_missing_issuer_manifest(tmp_path: Path) -> None:
    _write_six_issuers(tmp_path)
    (tmp_path / "NVDA" / "manifest.json").unlink()

    with pytest.raises(ImmutableArtifactConflictError, match="missing issuer manifest"):
        sec_corpus.reconcile_sec_corpus_manifest(corpus_root=tmp_path)


def test_reconciliation_rejects_invalid_referenced_checksum(tmp_path: Path) -> None:
    _write_six_issuers(tmp_path)
    (tmp_path / "QCOM" / "companyfacts.json").write_bytes(b"tampered")

    with pytest.raises(ImmutableArtifactConflictError, match="checksum mismatch"):
        sec_corpus.reconcile_sec_corpus_manifest(corpus_root=tmp_path)


def test_reconciliation_rejects_issuer_ticker_cik_mismatch(tmp_path: Path) -> None:
    _write_six_issuers(tmp_path)
    manifest_path = tmp_path / "VRTX" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["cik"] = _CORPUS_CIKS["AAPL"]
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")

    with pytest.raises(ImmutableArtifactConflictError, match="ticker/CIK mismatch"):
        sec_corpus.reconcile_sec_corpus_manifest(corpus_root=tmp_path)


def test_reconciliation_is_byte_stable_when_issuer_manifests_are_unchanged(tmp_path: Path) -> None:
    _write_six_issuers(tmp_path)
    first = sec_corpus.reconcile_sec_corpus_manifest(corpus_root=tmp_path)
    first_bytes = (tmp_path / "manifest.json").read_bytes()

    second = sec_corpus.reconcile_sec_corpus_manifest(corpus_root=tmp_path)

    assert second == first
    assert (tmp_path / "manifest.json").read_bytes() == first_bytes


def test_reconciliation_rejects_issuer_manifest_identity_mutation(tmp_path: Path) -> None:
    _write_six_issuers(tmp_path)
    sec_corpus.reconcile_sec_corpus_manifest(corpus_root=tmp_path)
    issuer_manifest = tmp_path / "AMZN" / "manifest.json"
    issuer_manifest.write_text(issuer_manifest.read_text() + "\n")

    with pytest.raises(ImmutableArtifactConflictError, match="root corpus identity changed"):
        sec_corpus.reconcile_sec_corpus_manifest(corpus_root=tmp_path)


def test_reconciliation_has_deterministic_configured_order(tmp_path: Path) -> None:
    _write_six_issuers(tmp_path)

    manifest = sec_corpus.reconcile_sec_corpus_manifest(
        corpus_root=tmp_path, tickers=tuple(reversed(_CORPUS_TICKERS))
    )

    assert [entry["ticker"] for entry in manifest["issuers"]] == list(_CORPUS_TICKERS)


def test_live_sec_corpus_builder_accepts_resolved_ticker_outside_legacy_allowlist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import qhapaq_finance.sec_corpus as sec_corpus
    from qhapaq_finance.company_resolver import (
        CompanyProvenance,
        ResolvedCompany,
    )

    class FakeResolver:
        def resolve(self, ticker: str) -> ResolvedCompany | None:
            assert ticker == "MSFT"
            return ResolvedCompany(
                "MSFT",
                "Microsoft Corporation",
                "0000789019",
                "NASDAQ",
                CompanyProvenance(
                    "https://www.sec.gov/files/company_tickers.json",
                    None,
                    None,
                    None,
                ),
            )

    submissions = {
        "cik": "0000789019",
        "tickers": ["MSFT"],
        "filings": {
            "recent": {
                "accessionNumber": [
                    "0001564590-26-000001",
                    "0001564590-26-000002",
                ],
                "form": ["10-K", "10-Q"],
                "filingDate": ["2026-07-30", "2026-04-30"],
                "reportDate": ["2026-06-30", "2026-03-31"],
                "primaryDocument": [
                    "msft-20260630.htm",
                    "msft-20260331.htm",
                ],
            }
        },
    }
    companyfacts = {
        "cik": 789019,
        "facts": {},
    }

    def fake_fetch_json(
        _client: object,
        _staging: Path,
        _issuer_root: Path,
        ticker: str,
        cik: str,
        kind: str,
        _url: str,
    ) -> tuple[dict[str, object], dict[str, object]]:
        assert ticker == "MSFT"
        assert cik == "0000789019"

        payload = submissions if kind == "submissions" else companyfacts
        return payload, {
            "artifact_kind": kind,
            "ticker": ticker,
            "cik": cik,
            "path": f"{kind}.json",
        }

    monkeypatch.setattr(sec_corpus, "_fetch_json", fake_fetch_json)
    monkeypatch.setattr(
        sec_corpus,
        "_export_filing",
        lambda *_args, **_kwargs: [],
    )

    result = sec_corpus.build_sec_corpus(
        object(),  # type: ignore[arg-type]
        corpus_root=tmp_path / "corpus",
        staging_root=tmp_path / "staging",
        tickers=("MSFT",),
        resolver=FakeResolver(),
    )

    assert result["issuers"][0]["ticker"] == "MSFT"
    assert result["issuers"][0]["cik"] == "0000789019"


def test_targeted_sec_corpus_build_preserves_existing_root_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import qhapaq_finance.sec_corpus as sec_corpus
    from qhapaq_finance.company_resolver import (
        CompanyProvenance,
        ResolvedCompany,
    )

    class FakeResolver:
        def resolve(self, ticker: str) -> ResolvedCompany | None:
            assert ticker == "MSFT"
            return ResolvedCompany(
                "MSFT",
                "Microsoft Corporation",
                "0000789019",
                "NASDAQ",
                CompanyProvenance(
                    "https://www.sec.gov/files/company_tickers.json",
                    None,
                    None,
                    None,
                ),
            )

    submissions = {
        "cik": "0000789019",
        "tickers": ["MSFT"],
        "filings": {
            "recent": {
                "accessionNumber": [
                    "0001564590-26-000001",
                    "0001564590-26-000002",
                ],
                "form": ["10-K", "10-Q"],
                "filingDate": ["2026-07-30", "2026-04-30"],
                "reportDate": ["2026-06-30", "2026-03-31"],
                "primaryDocument": [
                    "msft-20260630.htm",
                    "msft-20260331.htm",
                ],
            }
        },
    }
    companyfacts = {"cik": 789019, "facts": {}}

    def fake_fetch_json(
        _client: object,
        _staging: Path,
        _issuer_root: Path,
        ticker: str,
        cik: str,
        kind: str,
        _url: str,
    ) -> tuple[dict[str, object], dict[str, object]]:
        payload = submissions if kind == "submissions" else companyfacts
        return payload, {
            "artifact_kind": kind,
            "ticker": ticker,
            "cik": cik,
            "path": f"{kind}.json",
        }

    monkeypatch.setattr(sec_corpus, "_fetch_json", fake_fetch_json)
    monkeypatch.setattr(
        sec_corpus,
        "_export_filing",
        lambda *_args, **_kwargs: [],
    )

    root = tmp_path / "corpus"
    root.mkdir()

    root_manifest = root / "manifest.json"
    original = b'{"schema_version":"sec-corpus-v2","created_at":"frozen","issuers":[]}\n'
    root_manifest.write_bytes(original)

    result = sec_corpus.build_sec_corpus(
        object(),  # type: ignore[arg-type]
        corpus_root=root,
        staging_root=tmp_path / "staging",
        tickers=("MSFT",),
        resolver=FakeResolver(),
    )

    assert result["issuers"][0]["ticker"] == "MSFT"
    assert (root / "MSFT" / "manifest.json").is_file()
    assert root_manifest.read_bytes() == original


def test_explicit_filing_export_does_not_refetch_sec_aggregates(tmp_path: Path) -> None:
    filing = sec_corpus.Filing("0000000123-26-000003", "10-Q", "2026-07-30", "2026-06-30", "q2.htm")
    base = "https://www.sec.gov/Archives/edgar/data/123/000000012326000003"

    class RecordingClient:
        def __init__(self) -> None:
            self.urls: list[str] = []

        def get(self, url: str) -> SecResponse:
            self.urls.append(url)
            if url == f"{base}/index.json":
                body = b'{"directory":{"item":[{"name":"q2.htm"}]}}'
            elif url == f"{base}/q2.htm":
                body = b"<html><body>quarterly report</body></html>"
            else:
                raise AssertionError(f"unexpected SEC request: {url}")
            return SecResponse(200, {"Content-Type": "application/json"}, body)

    client = RecordingClient()

    records = sec_corpus.export_sec_filing(
        client,  # type: ignore[arg-type]
        staging_root=tmp_path / "staging",
        issuer_root=tmp_path / "issuer",
        ticker="ACME",
        cik="0000000123",
        filing=filing,
    )

    assert client.urls == [f"{base}/index.json", f"{base}/q2.htm"]
    assert [record["accession"] for record in records] == [filing.accession, filing.accession]


def test_explicit_filing_export_accepts_prefetched_provider_descriptor(tmp_path: Path) -> None:
    identity = CompanyIdentity("ACME", None, None, "Acme", None, None, "0000000123", None)
    base = "https://www.sec.gov/Archives/edgar/data/123/000000012326000003"

    class RecordingClient:
        def __init__(self) -> None:
            self.urls: list[str] = []

        def get(self, url: str) -> SecResponse:
            self.urls.append(url)
            if url == "https://data.sec.gov/submissions/CIK0000000123.json":
                payload: dict[str, object] = {
                    "cik": 123,
                    "tickers": ["ACME"],
                    "filings": {
                        "recent": {
                            "accessionNumber": ["0000000123-26-000003"],
                            "form": ["10-Q"],
                            "filingDate": ["2026-07-30"],
                            "reportDate": ["2026-06-30"],
                            "primaryDocument": ["q2.htm"],
                        }
                    },
                }
                body = json.dumps(payload).encode()
            elif url == "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000123.json":
                body = b'{"cik":123,"facts":{}}'
            elif url == f"{base}/index.json":
                body = b'{"directory":{"item":[{"name":"q2.htm"}]}}'
            elif url == f"{base}/q2.htm":
                body = b"<html><body>quarterly report</body></html>"
            else:
                raise AssertionError(f"unexpected SEC request: {url}")
            return SecResponse(200, {"Content-Type": "application/json"}, body)

    client = RecordingClient()
    provider = StructuredSecProvider(client, tmp_path / "staging")  # type: ignore[arg-type]
    prefetched = provider.acquire_fast_path(identity)
    filing = provider.original_filing(prefetched.submissions, "10-Q")

    records = sec_corpus.export_sec_filing(
        client,  # type: ignore[arg-type]
        staging_root=tmp_path / "staging",
        issuer_root=tmp_path / "issuer",
        ticker=identity.ticker,
        cik=identity.cik or "",
        filing=filing,
    )

    assert client.urls == [
        "https://data.sec.gov/submissions/CIK0000000123.json",
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000123.json",
        f"{base}/index.json",
        f"{base}/q2.htm",
    ]
    assert [record["accession"] for record in records] == [filing.accession, filing.accession]
