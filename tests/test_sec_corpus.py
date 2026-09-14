from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

import qhapaq_finance.sec_corpus as sec_corpus
from qhapaq_finance.sec_acquisition import ImmutableArtifactConflictError

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
                "accessionNumber": [], "form": [], "filingDate": [], "reportDate": [],
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
