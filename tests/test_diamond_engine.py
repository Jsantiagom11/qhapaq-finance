from __future__ import annotations

from dataclasses import replace

from qhapaq_finance.diamond.contracts import FiscalSlot, Methodology, SecurityRef
from qhapaq_finance.diamond.engine import evaluate_universe
from qhapaq_finance.diamond.serialization import canonical_diamond_json

try:
    from tests.diamond_helpers import rich_record
except ModuleNotFoundError:
    from diamond_helpers import rich_record


def _universe() -> tuple:
    return tuple(
        rich_record(
            f"T{i:02d}",
            scale=1.0 + i * 0.03,
            growth=0.04 + i * 0.003,
            op_margin=0.15 + i * 0.004,
            fcf_margin=0.10 + i * 0.003,
            dilution=-0.005 + i * 0.0004,
            recent_share_change=-0.01 + i * 0.001,
        )
        for i in range(20)
    )


def test_unsupported_methodology_remains_visible_but_unranked() -> None:
    records = _universe() + (
        rich_record(
            "JPM",
            methodology=Methodology.UNSUPPORTED_FINANCIAL,
            peer_group_id="Financials",
        ),
        rich_record("O", methodology=Methodology.UNSUPPORTED_REIT, peer_group_id="Real Estate"),
    )
    results = {item.ticker: item for item in evaluate_universe(records)}
    assert results["JPM"].archetypes.research_priority is None
    assert results["O"].archetypes.research_priority is None
    assert "UNSUPPORTED_METHODOLOGY" in results["JPM"].diagnostics


def test_input_order_does_not_affect_canonical_output() -> None:
    records = _universe()
    first = canonical_diamond_json(evaluate_universe(records))
    second = canonical_diamond_json(evaluate_universe(tuple(reversed(records))))
    assert first == second


def test_cyclical_peak_diagnostic_does_not_automatically_block_ranking() -> None:
    records = list(_universe())
    target = records[0]
    items = []
    for item in target.observations:
        if item.metric_id == "operating_cash_flow" and item.fiscal_slot is FiscalSlot.TTM:
            items.append(replace(item, value=item.value * 3.0))
        else:
            items.append(item)
    records[0] = replace(target, observations=tuple(items))
    result = {item.ticker: item for item in evaluate_universe(tuple(records))}["T00"]
    assert "CYCLICAL_PEAK_RISK" in result.diagnostics
    assert result.archetypes.research_priority is not None


def test_stale_market_data_nulls_price_without_erasing_other_categories() -> None:
    records = list(_universe())
    records[0] = replace(records[0], market_age_trading_days=4)
    result = {item.ticker: item for item in evaluate_universe(tuple(records))}["T00"]
    assert result.scores.price is None
    assert result.scores.quality is not None
    assert result.scores.growth is not None
    assert result.scores.capital is not None
    assert "MARKET_DATA_STALE" in result.diagnostics


def test_evidence_diagnostic_reaches_result() -> None:
    record = replace(
        rich_record("AAA"),
        evidence_diagnostics=("MARKET_CAP_SPLIT_UNVERIFIED",),
    )

    result = evaluate_universe((record,))[0]

    assert "MARKET_CAP_SPLIT_UNVERIFIED" in result.diagnostics


def test_missing_market_cap_preserves_null_aware_compounder_ranking() -> None:
    records = list(_universe())
    records[0] = replace(
        records[0],
        observations=tuple(
            observation
            for observation in records[0].observations
            if observation.metric_id != "market_cap"
        ),
    )

    results = evaluate_universe(tuple(records))
    candidate = next(item for item in results if item.ticker == "T00")

    assert len(results) == len(records)
    assert candidate.scores.price is None
    assert candidate.archetypes.compounder is not None
    assert candidate.archetypes.research_priority is not None


def test_evaluate_universe_preserves_exact_source_security() -> None:
    record = rich_record("ACME")
    result = evaluate_universe((record,))[0]

    assert result.source_security == SecurityRef(
        ticker=record.ticker,
        security_id=record.security_id,
        issuer_id=record.issuer_id,
    )
