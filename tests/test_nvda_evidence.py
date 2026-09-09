import json
from dataclasses import replace
from pathlib import Path

import pytest

from qhapaq_finance.accounting import AccountingError
from qhapaq_finance.evidence import load_facts
from qhapaq_finance.nvda_case import NVDA_AS_OF, _accounting_snapshot, load_nvda_case, nvda_audit
from qhapaq_finance.valuation import (
    _pv_fcff,
    analyze_case,
    price_value_classification,
)

ROOT = Path(__file__).parents[1]
EVIDENCE = ROOT / "data/research/nvda/financial-evidence.json"
GOLDEN = ROOT / "data/research/nvda/empirical-golden.json"


def test_nvda_empirical_evidence_normalizes_to_complete_ttm_snapshot() -> None:
    snapshot = _accounting_snapshot(load_facts(EVIDENCE, ROOT, as_of=NVDA_AS_OF))
    assert snapshot.period_end.isoformat() == "2026-07-26"
    assert snapshot.revenue == 302_970
    assert snapshot.ebit == 197_579
    assert snapshot.nopat == pytest.approx(162_014.78)
    assert snapshot.depreciation_amortization == 3_687
    assert snapshot.capex == 7_354
    assert snapshot.change_in_working_capital == 34_102
    assert snapshot.fcff == pytest.approx(124_245.78)
    assert snapshot.invested_capital == pytest.approx(49_153.5)
    assert snapshot.cash == 22_443
    assert snapshot.marketable_securities == 76_926
    assert snapshot.debt == 33_366
    assert snapshot.valuation_shares == 24_338
    assert snapshot.valuation_share_basis == "diluted_weighted_average"
    assert "ebit_fy26" in snapshot.source_lineage


def test_nvda_golden_replay_bridges_and_market_expectations() -> None:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    first, second = analyze_case(load_nvda_case(ROOT)), analyze_case(load_nvda_case(ROOT))
    values = {item.name: item for item in first.scenarios}
    assert first == second
    assert first.reconstructed_fcff == pytest.approx(golden["accounting"]["fcff"])
    assert first.roic == pytest.approx(golden["valuation"]["roic"])
    assert first.roic_minus_wacc == pytest.approx(golden["valuation"]["roic_minus_wacc"])
    assert first.case.capital_cost.wacc == pytest.approx(golden["valuation"]["wacc"])
    assert values["bear"].intrinsic_value_per_share < values["base"].intrinsic_value_per_share
    assert values["base"].intrinsic_value_per_share < values["bull"].intrinsic_value_per_share
    for name in ("bear", "base", "bull"):
        value = values[name]
        assert value.equity_value == pytest.approx(
            value.enterprise_value
            + first.case.market_snapshot.liquid_assets
            - first.case.market_snapshot.debt
        )
        assert value.terminal_growth < first.case.capital_cost.wacc
    base = values["base"]
    assert values["bear"].intrinsic_value_per_share == pytest.approx(
        golden["valuation"]["bear_intrinsic_value_per_share"]
    )
    assert base.intrinsic_value_per_share == pytest.approx(
        golden["valuation"]["base_intrinsic_value_per_share"]
    )
    assert values["bull"].intrinsic_value_per_share == pytest.approx(
        golden["valuation"]["bull_intrinsic_value_per_share"]
    )
    assert (
        price_value_classification(first.case.market_snapshot.price, base.intrinsic_value_per_share)
        == "ABOVE FAIR VALUE"
    )
    implied_ev = _pv_fcff(
        first.normalized_fcff,
        first.reverse_implied_growth,
        base.terminal_growth,
        first.case.capital_cost.wacc,
        8,
    )
    assert implied_ev == pytest.approx(first.case.market_snapshot.enterprise_value, rel=1e-9)
    assert first.reverse_implied_growth == pytest.approx(
        golden["valuation"]["reverse_implied_growth"]
    )


def test_nvda_missing_mandatory_evidence_and_period_mismatch_fail_closed() -> None:
    facts = load_facts(EVIDENCE, ROOT, as_of=NVDA_AS_OF)
    missing = dict(facts)
    missing.pop("capex_h1fy27")
    with pytest.raises(AccountingError, match="missing evidence for capex"):
        _accounting_snapshot(missing)
    mismatched = dict(facts)
    mismatched["cash_q2fy27"] = replace(mismatched["cash_q2fy27"], period_end=NVDA_AS_OF)
    with pytest.raises(AccountingError, match="closing operating"):
        _accounting_snapshot(mismatched)


def test_nvda_audit_keeps_tax_and_market_provenance_explicit() -> None:
    audit = nvda_audit(ROOT)
    assert audit["ttm_revenue_bridge"] == "215,938 - 90,805 + 177,837 = 302,970"
    assert audit["change_operating_nwc"] == 34_102
    assert "ASSUMPTION" in str(audit["operating_tax_basis"])


def test_nvda_audit_uses_ttm_matched_capital_and_diluted_share_semantics() -> None:
    audit = nvda_audit(ROOT)
    nwc = audit["operating_nwc"]
    capital = audit["invested_capital"]
    assert isinstance(nwc, dict) and isinstance(capital, dict)
    assert nwc["opening"] == 18_513
    assert nwc["closing"] == 52_615
    assert nwc["change"] == 34_102
    assert nwc["ttm_compatible"] is True
    assert capital["reported_average"] == 49_153.5
    assert capital["ttm_compatible"] is True
    assert audit["golden_case_status"] == "READY"
    assert audit["share_count"]["basis"] == "diluted_weighted_average"


def test_nvda_reverse_dcf_growth_replays_market_enterprise_value_in_forward_engine() -> None:
    result = analyze_case(load_nvda_case(ROOT))
    base = next(item for item in result.case.scenarios if item.name == "base")
    implied = replace(base, explicit_growth=result.reverse_implied_growth)
    implied_ev = _pv_fcff(
        result.normalized_fcff,
        implied.explicit_growth,
        implied.terminal_growth,
        result.case.capital_cost.wacc,
        implied.years,
    )
    assert implied_ev == pytest.approx(result.case.market_snapshot.enterprise_value, rel=1e-9)
