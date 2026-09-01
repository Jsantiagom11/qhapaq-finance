from pathlib import Path

from qhapaq_finance.data import file_sha256


def test_file_sha256_identifies_exact_artifact_bytes(tmp_path: Path) -> None:
    artifact = tmp_path / "prices.csv"
    artifact.write_bytes(b"abc")

    original = file_sha256(artifact)
    assert original == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"

    artifact.write_bytes(b"abc\n")
    assert file_sha256(artifact) != original
