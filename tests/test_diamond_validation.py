from datetime import date

import pytest

from qhapaq_finance.diamond.contracts import Methodology
from qhapaq_finance.diamond.validation import (
    DiamondValidationError,
    record_eligible_for_scoring,
    validate_dataset,
)

try:
    from tests.diamond_helpers import make_record
except ModuleNotFoundError:
    from diamond_helpers import make_record


def test_dataset_requires_one_data_as_of() -> None:
    records = (
        make_record("AAA", data_as_of=date(2026, 9, 20)),
        make_record("BBB", data_as_of=date(2026, 9, 19)),
    )
    with pytest.raises(DiamondValidationError, match="DATA_AS_OF_MISMATCH"):
        validate_dataset(records)


def test_fundamental_older_than_130_days_is_not_score_eligible() -> None:
    record = make_record(
        data_as_of=date(2026, 9, 20),
        fundamental_period_end=date(2026, 5, 12),
    )
    assert not record_eligible_for_scoring(record)


@pytest.mark.parametrize(
    "methodology",
    [
        Methodology.UNSUPPORTED_FINANCIAL,
        Methodology.UNSUPPORTED_INSURER,
        Methodology.UNSUPPORTED_REIT,
        Methodology.UNKNOWN,
    ],
)
def test_only_operating_company_is_generic_score_eligible(methodology: Methodology) -> None:
    assert not record_eligible_for_scoring(make_record(methodology=methodology))
