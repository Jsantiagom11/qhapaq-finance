from datetime import date
from pathlib import Path

import pytest

from qhapaq_finance.diamond.contracts import FiscalSlot
from qhapaq_finance.diamond.metrics import observation
from qhapaq_finance.diamond.providers.local import LocalJsonProvider, LocalProviderError

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tests/fixtures/diamond/minimal-universe.json"


def test_local_provider_rejects_unknown_schema(tmp_path: Path) -> None:
    path = tmp_path / "fundamentals.json"
    path.write_text('{"schema_version":"wrong","records":[]}', encoding="utf-8")
    with pytest.raises(LocalProviderError, match="SCHEMA_VERSION_UNSUPPORTED"):
        LocalJsonProvider(path)


def test_local_provider_preserves_missing_metric_as_missing() -> None:
    provider = LocalJsonProvider(FIXTURE)
    record = provider.records()[0]
    assert observation(record, "nonexistent_metric", FiscalSlot.LATEST) is None


def test_local_provider_returns_identity_bound_universe() -> None:
    provider = LocalJsonProvider(FIXTURE)
    securities = provider.universe("test-operating", date(2026, 9, 20))
    records = provider.fundamentals(securities, date(2026, 9, 20))
    assert len(securities) == len(records) == 22
    assert securities[0].ticker == records[0].ticker
