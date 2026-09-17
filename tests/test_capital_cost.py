from datetime import date

import pytest

from qhapaq_finance.capital_cost import (
    BetaEvidence,
    CapitalCostError,
    CapitalCostRequirements,
    IssuerValueEvidence,
    RateEvidence,
    TaxRateSemantic,
    derive_effective_tax_rate,
    derive_wacc,
)
from qhapaq_finance.valuation import CapitalCost

AS_OF = date(2026, 9, 8)


def _rate(identity: str, metric: str, value: float, *, tenor: str | None = None) -> RateEvidence:
    return RateEvidence(
        identity,
        metric,
        value,
        "decimal_rate",
        AS_OF,
        "source",
        "primary",
        "quality",
        "implied_erp" if metric == "equity_risk_premium" else "treasury_observation",
        tenor,
    )


def _issuer(identity: str, metric: str, value: float, semantic: str) -> IssuerValueEvidence:
    return IssuerValueEvidence(
        identity,
        "issuer",
        metric,
        semantic,
        value,
        "USD million",
        AS_OF,
        "filing",
        "primary",
        "quality",
    )


def _requirements() -> CapitalCostRequirements:
    return CapitalCostRequirements(
        "capm_wacc_v1",
        "10Y",
        "implied_erp",
        ("deterministic_regression",),
        ("total_interest_bearing_debt",),
        (TaxRateSemantic.EFFECTIVE,),
        365,
    )


def _result(
    *,
    debt_value: float | None = 100,
    interest_expense_value: float = 4,
    average_debt_value: float = 100,
):
    tax = derive_effective_tax_rate(
        tax_expense=_issuer("tax", "tax_expense", 20, "income_tax_expense"),
        pretax_income=_issuer("pretax", "pretax_income", 100, "pretax_income"),
        identity="effective-tax",
        quality_identity="quality",
    )
    return derive_wacc(
        research_as_of=AS_OF,
        security_id="issuer:ABC",
        requirements=_requirements(),
        risk_free=_rate("rf", "risk_free_rate", 0.04, tenor="10Y"),
        equity_risk_premium=_rate("erp", "equity_risk_premium", 0.05),
        beta=BetaEvidence(
            "beta",
            "issuer:ABC",
            1.2,
            AS_OF,
            "source",
            "primary",
            "quality",
            "deterministic_regression",
            "SP500",
            date(2021, 9, 8),
            AS_OF,
            "weekly",
            "adjusted_close",
        ),
        interest_expense=_issuer(
            "interest", "interest_expense", interest_expense_value, "interest_expense"
        ),
        average_debt=_issuer(
            "average-debt", "debt", average_debt_value, "total_interest_bearing_debt"
        ),
        tax_rate=tax,
        market_equity=_issuer("equity", "market_equity", 900, "canonical_market_equity"),
        debt=(
            None
            if debt_value is None
            else _issuer("debt", "debt", debt_value, "total_interest_bearing_debt")
        ),
    )


def test_canonical_wacc_is_deterministic_lineaged_and_adapts_to_valuation() -> None:
    first, second = _result(), _result()
    assert first.cost_of_equity == pytest.approx(0.10)
    assert first.pre_tax_cost_of_debt == pytest.approx(0.04)
    assert first.after_tax_cost_of_debt == pytest.approx(0.032)
    assert first.wacc == pytest.approx(0.0932)
    assert first.equity_weight + first.debt_weight == pytest.approx(1)
    assert first.provenance.content_identity == second.provenance.content_identity
    assert dict(first.provenance.inputs)["beta"] == "beta"
    assert CapitalCost.from_determination(first).source_mode == "canonical"


def test_legacy_valuation_capital_cost_uses_central_wacc_calculation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy inputs remain compatible, but their WACC comes from capital_cost."""
    import qhapaq_finance.capital_cost as capital_cost

    expected = (0.123, 0.88, 0.12, 0.1198)
    monkeypatch.setattr(
        capital_cost,
        "_calculate_wacc_components",
        lambda **_: expected,
        raising=False,
    )

    result = CapitalCost.from_assumptions(
        risk_free_rate=0.04,
        equity_risk_premium=0.05,
        beta=1.2,
        pre_tax_cost_of_debt=0.04,
        tax_rate=0.2,
        market_equity=900,
        debt=100,
    )

    assert (
        result.cost_of_equity,
        result.equity_weight,
        result.debt_weight,
        result.wacc,
    ) == expected


def test_canonical_zero_debt_does_not_require_cost_of_debt() -> None:
    result = _result(debt_value=0, interest_expense_value=0, average_debt_value=0)

    assert result.debt_weight == 0
    assert result.equity_weight == 1
    assert result.wacc == result.cost_of_equity
    assert "interest_expense" not in dict(result.provenance.inputs)
    assert "average_debt" not in dict(result.provenance.inputs)


def test_missing_canonical_debt_fails_closed() -> None:
    with pytest.raises(CapitalCostError, match="DEBT_EVIDENCE_REQUIRED"):
        _result(debt_value=None)


def test_positive_debt_without_cost_of_debt_still_fails_closed() -> None:
    with pytest.raises(CapitalCostError, match="COST_OF_DEBT_UNAVAILABLE"):
        _result(debt_value=100, interest_expense_value=0, average_debt_value=0)


def test_security_temporal_and_cost_of_debt_gates_fail_closed() -> None:
    with pytest.raises(CapitalCostError, match="BETA_PROVENANCE"):
        BetaEvidence("beta", "", 1, AS_OF, "s", "a", "q", "externally_reported")
    args = _result().__dict__.copy()
    assert args["wacc"] > 0
    with pytest.raises(CapitalCostError, match="TAX_RATE_DENOMINATOR"):
        derive_effective_tax_rate(
            tax_expense=_issuer("tax", "tax_expense", 1, "income_tax_expense"),
            pretax_income=_issuer("pretax", "pretax_income", 0, "pretax_income"),
            identity="bad-tax",
            quality_identity="q",
        )


def test_incompatible_tenor_and_security_are_rejected() -> None:
    tax = derive_effective_tax_rate(
        tax_expense=_issuer("tax", "tax_expense", 20, "income_tax_expense"),
        pretax_income=_issuer("pretax", "pretax_income", 100, "pretax_income"),
        identity="effective-tax",
        quality_identity="quality",
    )
    with pytest.raises(CapitalCostError, match="risk_free_tenor_compatibility"):
        derive_wacc(
            research_as_of=AS_OF,
            security_id="issuer:ABC",
            requirements=_requirements(),
            risk_free=_rate("rf", "risk_free_rate", 0.04, tenor="2Y"),
            equity_risk_premium=_rate("erp", "equity_risk_premium", 0.05),
            beta=BetaEvidence(
                "beta",
                "issuer:OTHER",
                1,
                AS_OF,
                "source",
                "primary",
                "quality",
                "externally_reported",
            ),
            interest_expense=_issuer("interest", "interest_expense", 4, "interest_expense"),
            average_debt=_issuer("average-debt", "debt", 100, "total_interest_bearing_debt"),
            tax_rate=tax,
            market_equity=_issuer("equity", "market_equity", 900, "canonical_market_equity"),
            debt=_issuer("debt", "debt", 100, "total_interest_bearing_debt"),
        )


def test_market_debt_yield_can_supply_cost_of_debt() -> None:
    import qhapaq_finance.capital_cost as capital_cost

    tax = derive_effective_tax_rate(
        tax_expense=_issuer("tax", "tax_expense", 20, "income_tax_expense"),
        pretax_income=_issuer("pretax", "pretax_income", 100, "pretax_income"),
        identity="effective-tax",
        quality_identity="quality",
    )

    requirements = CapitalCostRequirements(
        "capm_wacc_v1",
        "10Y",
        "implied_erp",
        ("deterministic_regression",),
        ("total_interest_bearing_debt",),
        (TaxRateSemantic.EFFECTIVE,),
        365,
        cost_of_debt_methodology="market_debt_yield",
    )

    cost_of_debt = capital_cost.CostOfDebtEvidence(
        "market-debt-yield",
        "issuer:ABC",
        0.045,
        "decimal_rate",
        AS_OF,
        "market-debt-source",
        "primary",
        "quality",
        "market_debt_yield",
    )

    result = derive_wacc(
        research_as_of=AS_OF,
        security_id="issuer:ABC",
        requirements=requirements,
        risk_free=_rate("rf", "risk_free_rate", 0.04, tenor="10Y"),
        equity_risk_premium=_rate("erp", "equity_risk_premium", 0.05),
        beta=BetaEvidence(
            "beta",
            "issuer:ABC",
            1.2,
            AS_OF,
            "source",
            "primary",
            "quality",
            "deterministic_regression",
            "SP500",
            date(2021, 9, 8),
            AS_OF,
            "weekly",
            "adjusted_close",
        ),
        interest_expense=None,
        average_debt=None,
        cost_of_debt=cost_of_debt,
        tax_rate=tax,
        market_equity=_issuer(
            "equity",
            "market_equity",
            900,
            "canonical_market_equity",
        ),
        debt=_issuer(
            "debt",
            "debt",
            100,
            "total_interest_bearing_debt",
        ),
    )

    assert result.pre_tax_cost_of_debt == pytest.approx(0.045)
    assert result.after_tax_cost_of_debt == pytest.approx(0.036)
    assert result.wacc == pytest.approx(0.0936)
    assert dict(result.provenance.inputs)["cost_of_debt"] == "market-debt-yield"
    assert "interest_expense" not in dict(result.provenance.inputs)
    assert "average_debt" not in dict(result.provenance.inputs)
