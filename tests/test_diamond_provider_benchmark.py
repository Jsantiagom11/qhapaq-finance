from pathlib import Path

from qhapaq_finance.diamond.providers.benchmark import benchmark_provider_sample
from qhapaq_finance.diamond.providers.local import LocalJsonProvider

ROOT = Path(__file__).parents[1]
REFERENCE = ROOT / "tests/fixtures/diamond/provider-reference.json"
CANDIDATE = ROOT / "tests/fixtures/diamond/provider-candidate.json"


def test_benchmark_surfaces_semantic_coverage_period_sign_and_share_basis_gaps() -> None:
    result = benchmark_provider_sample(
        reference=LocalJsonProvider(REFERENCE),
        candidate=LocalJsonProvider(CANDIDATE),
        operational_metadata={"calls_per_ticker": 3.0, "batch_size": 1, "latency_ms": 125.0},
    )
    assert result.identity_pass_rate == 1.0
    assert result.required_family_coverage < 1.0
    assert result.period_identity_pass_rate < 1.0
    assert result.sign_semantics_pass_rate < 1.0
    assert result.share_basis_pass_rate < 1.0
    assert "REQUIRED_FAMILY_COVERAGE_GAP" in result.diagnostics
    assert "PERIOD_IDENTITY_GAP" in result.diagnostics
    assert "SIGN_SEMANTICS_GAP" in result.diagnostics
    assert "SHARE_BASIS_GAP" in result.diagnostics
