from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from qhapaq_finance.cli import main

CIK = "0000000123"
CUTOFF = "2026-09-22"
ANNUAL = "0000000123-26-000001"


def _inputs(tmp_path: Path, *, cik: int = 123) -> tuple[Path, Path]:
    filings = (
        (ANNUAL, "10-K", CUTOFF, "2025-12-31", "fy.htm"),
        ("0000000123-26-000002", "10-K", "2026-09-23", "2025-12-31", "late.htm"),
        ("0000000123-26-000003", "10-K/A", CUTOFF, "2025-12-31", "amended.htm"),
    )
    names = ("accessionNumber", "form", "filingDate", "reportDate", "primaryDocument")
    submissions = tmp_path / "submissions.json"
    submissions.write_text(
        json.dumps(
            {
                "cik": "123",
                "filings": {"recent": dict(zip(names, zip(*filings, strict=True), strict=True))},
            }
        ),
        encoding="utf-8",
    )
    companyfacts = tmp_path / "companyfacts.json"
    current = {
        "start": "2025-01-01",
        "end": "2025-12-31",
        "fy": 2025,
        "fp": "FY",
        "form": "10-K",
        "accn": ANNUAL,
        "filed": CUTOFF,
        "val": 100,
    }
    future = {**current, "accn": "0000000123-26-000002", "filed": "2026-09-23"}
    companyfacts.write_text(
        json.dumps(
            {
                "cik": cik,
                "facts": {
                    "us-gaap": {
                        "OperatingIncomeLoss": {
                            "units": {"USD": [current, future, {**future, "val": 200}]}
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return submissions, companyfacts


def _command(inputs: tuple[Path, Path], *, cutoff: str = CUTOFF) -> list[str]:
    submissions, companyfacts = inputs
    return [
        "sec",
        "plan-filings",
        CIK,
        "--as-of",
        cutoff,
        "--submissions",
        str(submissions),
        "--companyfacts",
        str(companyfacts),
    ]


def test_sec_plan_filings_is_offline_deterministic_and_cutoff_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def forbid(*args: object, **kwargs: object) -> None:
        raise AssertionError("offline SEC planning must not initialize or contact SEC")

    monkeypatch.setattr("qhapaq_finance.cli.SecConfig.from_env", forbid)
    monkeypatch.setattr("qhapaq_finance.sec_client.SecClient.get", forbid)
    inputs = _inputs(tmp_path)
    original_paths = set(tmp_path.iterdir())

    main(_command(inputs))
    first = capsys.readouterr()
    main(_command(inputs))
    assert capsys.readouterr() == first
    assert set(tmp_path.iterdir()) == original_paths

    result = json.loads(first.out)
    assert result["as_of"] == CUTOFF
    assert result["cik"] == CIK
    assert result["state"] == "GAP"
    assert result["reason"] == "MISSING_STANDARD_CONCEPT"
    assert result["eligible_facts"] == 1
    assert result["eligible_filings"] == 2
    assert [item["accession"] for item in result["fallback"]["filings"]] == [ANNUAL]
    assert result["input_sha256"] == {
        "submissions": hashlib.sha256(inputs[0].read_bytes()).hexdigest(),
        "companyfacts": hashlib.sha256(inputs[1].read_bytes()).hexdigest(),
    }

    main(_command(inputs, cutoff="2026-09-23"))
    later = json.loads(capsys.readouterr().out)
    assert later["eligible_facts"] == 3
    assert later["state"] == "BLOCKED"
    assert later["reason"] == "CANONICAL_CONFLICT"
    assert later["fallback"] is None


def test_sec_plan_filings_rejects_an_input_for_another_issuer(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as error:
        main(_command(_inputs(tmp_path, cik=456)))

    assert error.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "companyfacts CIK does not match" in captured.err


@pytest.mark.parametrize("cutoff", ["20260922", "2026-09-31"])
def test_sec_plan_filings_rejects_noncanonical_dates(
    cutoff: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as error:
        main(_command(_inputs(tmp_path), cutoff=cutoff))

    assert error.value.code == 2
    assert "expected YYYY-MM-DD" in capsys.readouterr().err
