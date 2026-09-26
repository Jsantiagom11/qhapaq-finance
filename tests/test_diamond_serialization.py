import json

from qhapaq_finance.diamond.engine import evaluate_universe
from qhapaq_finance.diamond.serialization import (
    METRIC_KEYS,
    canonical_diamond_json,
    diamond_csv,
    diamond_result_dict,
)

try:
    from tests.diamond_helpers import rich_record
except ModuleNotFoundError:
    from diamond_helpers import rich_record


def _results():
    records = tuple(
        rich_record(f"T{i:02d}", scale=1 + i * 0.05, growth=0.05 + i * 0.002) for i in range(20)
    )
    return evaluate_universe(records)


def test_public_metrics_have_exactly_fifteen_stable_keys() -> None:
    payload = diamond_result_dict(_results()[0])
    assert tuple(payload["metrics"]) == METRIC_KEYS
    assert len(payload["metrics"]) == 15


def test_canonical_json_is_deterministic_and_contains_no_nan_tokens() -> None:
    first = canonical_diamond_json(_results())
    second = canonical_diamond_json(tuple(reversed(_results())))
    assert first == second
    assert "NaN" not in first and "Infinity" not in first
    json.loads(first)


def test_csv_header_is_stable() -> None:
    rendered = diamond_csv(_results())
    header = rendered.splitlines()[0]
    assert header.startswith("ticker,company_name,data_as_of,methodology,peer_scope,peer_count")
    assert "research_priority" in header

def test_source_security_is_not_part_of_public_diamond_serialization() -> None:
    result = _results()[0]
    payload = diamond_result_dict(result)
    rendered_json = canonical_diamond_json((result,))
    csv_header = diamond_csv((result,)).splitlines()[0]

    assert result.source_security is not None
    assert "source_security" not in payload
    assert "source_security" not in rendered_json
    assert "source_security" not in csv_header
