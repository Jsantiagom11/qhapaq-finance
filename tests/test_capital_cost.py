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


def _result():
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
        interest_expense=_issuer("interest", "interest_expense", 4, "interest_expense"),
        average_debt=_issuer("average-debt", "debt", 100, "total_interest_bearing_debt"),
        tax_rate=tax,
        market_equity=_issuer("equity", "market_equity", 900, "canonical_market_equity"),
        debt=_issuer("debt", "debt", 100, "total_interest_bearing_debt"),
    )


def test_canonical_wacc_is_deterministic_lineaged_and_adapts_to_valuation() -> None:
    first, second = _result(), _result()
    assert first.cost_of_equity == pytest.approx(0.10)
    assert first.wacc == pytest.approx(0.0932)
    assert first.equity_weight + first.debt_weight == pytest.approx(1)
    assert first.provenance.content_identity == second.provenance.content_identity
    assert dict(first.provenance.inputs)["beta"] == "beta"
    assert CapitalCost.from_determination(first).source_mode == "canonical"


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
