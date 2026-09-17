"""Offline, deterministic capital-cost evidence and WACC derivation.

This module deliberately accepts already-acquired facts only.  It is the
numerical authority for canonical WACC; callers cannot substitute a bare rate
for an evidence object.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path

from .evidence_quality import Gate, GateStatus, content_identity


class CapitalCostError(ValueError):
    """Capital-cost evidence is incomplete or semantically incompatible."""


def load_legacy_assumptions(path: str | Path) -> dict[str, float]:
    """Read explicitly-labelled compatibility assumptions; never canonicalize them."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        values = raw["values"]
        if (
            raw.get("schema_version") != "capital-cost-legacy-v1"
            or raw.get("source_mode") != "legacy"
        ):
            raise ValueError
        required = (
            "risk_free_rate",
            "equity_risk_premium",
            "beta",
            "pre_tax_cost_of_debt",
            "tax_rate",
        )
        result = {key: float(values[key]) for key in required}
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise CapitalCostError("LEGACY_CAPITAL_COST_INVALID") from exc
    if any(not math.isfinite(value) for value in result.values()):
        raise CapitalCostError("LEGACY_CAPITAL_COST_INVALID")
    return result


class TaxRateSemantic(str, Enum):
    STATUTORY = "statutory"
    EFFECTIVE = "effective"
    NORMALIZED = "normalized"


@dataclass(frozen=True)
class RateEvidence:
    """A macro rate with source identity and explicit methodology."""

    identity: str
    metric: str
    value: float
    unit: str
    observed_at: date
    source_identity: str
    authority: str
    quality_identity: str
    methodology: str
    tenor: str | None = None

    def __post_init__(self) -> None:
        if self.metric not in {"risk_free_rate", "equity_risk_premium"}:
            raise CapitalCostError("CAPITAL_COST_RATE_METRIC_INVALID")
        if self.unit != "decimal_rate" or not math.isfinite(self.value) or not -1 < self.value < 1:
            raise CapitalCostError("CAPITAL_COST_RATE_UNIT_INVALID")
        if not all(
            (
                self.identity,
                self.source_identity,
                self.authority,
                self.quality_identity,
                self.methodology,
            )
        ):
            raise CapitalCostError("CAPITAL_COST_PROVENANCE_INCOMPLETE")
        if self.metric == "risk_free_rate" and not self.tenor:
            raise CapitalCostError("RISK_FREE_TENOR_REQUIRED")


@dataclass(frozen=True)
class CostOfDebtEvidence:
    """Issuer-specific pre-tax cost-of-debt rate with explicit methodology."""

    identity: str
    issuer_id: str
    value: float
    unit: str
    observed_at: date
    source_identity: str
    authority: str
    quality_identity: str
    methodology: str

    def __post_init__(self) -> None:
        if self.unit != "decimal_rate" or not math.isfinite(self.value) or not 0 <= self.value < 1:
            raise CapitalCostError("COST_OF_DEBT_RATE_INVALID")
        if not all(
            (
                self.identity,
                self.issuer_id,
                self.source_identity,
                self.authority,
                self.quality_identity,
                self.methodology,
            )
        ):
            raise CapitalCostError("COST_OF_DEBT_PROVENANCE_INCOMPLETE")


@dataclass(frozen=True)
class BetaEvidence:
    identity: str
    security_id: str
    value: float
    observed_at: date
    source_identity: str
    authority: str
    quality_identity: str
    methodology: str
    benchmark: str | None = None
    observation_start: date | None = None
    observation_end: date | None = None
    return_frequency: str | None = None
    price_adjustment: str | None = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.value) or self.value < 0:
            raise CapitalCostError("BETA_VALUE_INVALID")
        if not all(
            (
                self.identity,
                self.security_id,
                self.source_identity,
                self.authority,
                self.quality_identity,
                self.methodology,
            )
        ):
            raise CapitalCostError("BETA_PROVENANCE_INCOMPLETE")
        deterministic = self.methodology == "deterministic_regression"
        if deterministic and not all(
            (
                self.benchmark,
                self.observation_start,
                self.observation_end,
                self.return_frequency,
                self.price_adjustment,
            )
        ):
            raise CapitalCostError("BETA_METHODOLOGY_INCOMPLETE")


@dataclass(frozen=True)
class IssuerValueEvidence:
    identity: str
    issuer_id: str
    metric: str
    semantic_type: str
    value: float
    unit: str
    observed_at: date
    source_identity: str
    authority: str
    quality_identity: str

    def __post_init__(self) -> None:
        if self.metric not in {
            "debt",
            "market_equity",
            "interest_expense",
            "tax_expense",
            "pretax_income",
        }:
            raise CapitalCostError("ISSUER_VALUE_METRIC_INVALID")
        if self.unit != "USD million" or not math.isfinite(self.value):
            raise CapitalCostError("ISSUER_VALUE_UNIT_INVALID")
        if not all(
            (
                self.identity,
                self.issuer_id,
                self.semantic_type,
                self.source_identity,
                self.authority,
                self.quality_identity,
            )
        ):
            raise CapitalCostError("ISSUER_VALUE_PROVENANCE_INCOMPLETE")


@dataclass(frozen=True)
class TaxRateEvidence:
    identity: str
    semantic_type: TaxRateSemantic
    value: float
    observed_at: date
    source_identity: str
    authority: str
    quality_identity: str
    inputs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not math.isfinite(self.value) or not 0 <= self.value < 1:
            raise CapitalCostError("TAX_RATE_INVALID")
        if not all((self.identity, self.source_identity, self.authority, self.quality_identity)):
            raise CapitalCostError("TAX_RATE_PROVENANCE_INCOMPLETE")
        if self.semantic_type is TaxRateSemantic.EFFECTIVE and len(self.inputs) != 2:
            raise CapitalCostError("TAX_RATE_INPUTS_INCOMPLETE")


def derive_effective_tax_rate(
    *,
    tax_expense: IssuerValueEvidence,
    pretax_income: IssuerValueEvidence,
    identity: str,
    quality_identity: str,
) -> TaxRateEvidence:
    if tax_expense.metric != "tax_expense" or pretax_income.metric != "pretax_income":
        raise CapitalCostError("TAX_RATE_SEMANTICS_INVALID")
    if pretax_income.value <= 0:
        raise CapitalCostError("TAX_RATE_DENOMINATOR_INVALID")
    if tax_expense.observed_at != pretax_income.observed_at:
        raise CapitalCostError("TAX_RATE_PERIOD_MISMATCH")
    return TaxRateEvidence(
        identity,
        TaxRateSemantic.EFFECTIVE,
        tax_expense.value / pretax_income.value,
        tax_expense.observed_at,
        "derived:tax_expense/pretax_income",
        tax_expense.authority,
        quality_identity,
        (tax_expense.identity, pretax_income.identity),
    )


@dataclass(frozen=True)
class CapitalCostRequirements:
    methodology_id: str
    risk_free_tenor: str
    erp_methodology: str
    beta_methodologies: tuple[str, ...]
    debt_semantics: tuple[str, ...]
    tax_semantics: tuple[TaxRateSemantic, ...]
    max_age_days: int
    cost_of_debt_methodology: str = "interest_expense_over_average_debt"


@dataclass(frozen=True)
class CapitalCostProvenance:
    research_as_of: date
    source_mode: str
    methodology_id: str
    inputs: tuple[tuple[str, str], ...]
    gates: tuple[Gate, ...]
    content_identity: str


@dataclass(frozen=True)
class CapitalCostResult:
    risk_free_rate: float
    equity_risk_premium: float
    beta: float
    cost_of_equity: float
    pre_tax_cost_of_debt: float
    after_tax_cost_of_debt: float
    tax_rate: float
    market_equity: float
    debt: float
    equity_weight: float
    debt_weight: float
    wacc: float
    provenance: CapitalCostProvenance


def _gate(identifier: str, passed: bool, *references: str) -> Gate:
    return Gate(
        identifier,
        GateStatus.PASS if passed else GateStatus.FAIL,
        True,
        () if passed else (identifier,),
        references,
    )


def _calculate_wacc_components(
    *,
    risk_free_rate: float,
    equity_risk_premium: float,
    beta: float,
    pre_tax_cost_of_debt: float,
    tax_rate: float,
    market_equity: float,
    debt: float,
) -> tuple[float, float, float, float]:
    """Calculate CAPM cost of equity, capital weights, and WACC from validated inputs."""
    total = market_equity + debt
    if debt < 0 or total <= 0:
        raise CapitalCostError("CAPITAL_STRUCTURE_DENOMINATOR_INVALID")
    equity_weight, debt_weight = market_equity / total, debt / total
    cost_of_equity = risk_free_rate + beta * equity_risk_premium
    wacc = equity_weight * cost_of_equity + debt_weight * pre_tax_cost_of_debt * (1 - tax_rate)
    return cost_of_equity, equity_weight, debt_weight, wacc


def derive_wacc(
    *,
    research_as_of: date,
    security_id: str,
    requirements: CapitalCostRequirements,
    risk_free: RateEvidence,
    equity_risk_premium: RateEvidence,
    beta: BetaEvidence,
    interest_expense: IssuerValueEvidence | None,
    average_debt: IssuerValueEvidence | None,
    cost_of_debt: CostOfDebtEvidence | None = None,
    tax_rate: TaxRateEvidence,
    market_equity: IssuerValueEvidence,
    debt: IssuerValueEvidence | None,
) -> CapitalCostResult:
    """Derive CAPM/WACC with explicit inputs, gates, and stable lineage."""
    if debt is None:
        raise CapitalCostError("DEBT_EVIDENCE_REQUIRED")
    if debt.value < 0:
        raise CapitalCostError("CAPITAL_STRUCTURE_DENOMINATOR_INVALID")
    debt_is_zero = debt.value == 0
    cost_of_debt_methodology = requirements.cost_of_debt_methodology
    debt_cost_inputs: tuple[IssuerValueEvidence | CostOfDebtEvidence, ...]
    if cost_of_debt_methodology == "interest_expense_over_average_debt":
        debt_cost_inputs = tuple(
            item for item in (interest_expense, average_debt) if item is not None
        )
    elif cost_of_debt_methodology == "market_debt_yield":
        debt_cost_inputs = () if cost_of_debt is None else (cost_of_debt,)
    else:
        raise CapitalCostError("COST_OF_DEBT_METHODOLOGY_UNSUPPORTED")
    temporal_inputs = (
        risk_free,
        equity_risk_premium,
        beta,
        tax_rate,
        market_equity,
        debt,
    ) + (() if debt_is_zero else debt_cost_inputs)
    gates = (
        _gate("provenance", True, risk_free.identity, equity_risk_premium.identity, beta.identity),
        _gate(
            "risk_free_tenor_compatibility",
            risk_free.tenor == requirements.risk_free_tenor,
            risk_free.identity,
        ),
        _gate(
            "ERP_methodology",
            equity_risk_premium.methodology == requirements.erp_methodology,
            equity_risk_premium.identity,
        ),
        _gate(
            "beta_methodology", beta.methodology in requirements.beta_methodologies, beta.identity
        ),
        _gate("beta_security", beta.security_id == security_id, beta.identity),
        _gate(
            "debt_semantics",
            debt.semantic_type in requirements.debt_semantics
            and (
                debt_is_zero
                or cost_of_debt_methodology == "market_debt_yield"
                or (
                    average_debt is not None
                    and average_debt.semantic_type in requirements.debt_semantics
                )
            ),
            debt.identity,
            *(() if average_debt is None else (average_debt.identity,)),
        ),
        _gate(
            "tax_semantics", tax_rate.semantic_type in requirements.tax_semantics, tax_rate.identity
        ),
        _gate(
            "market_equity_quality",
            market_equity.metric == "market_equity" and market_equity.value > 0,
            market_equity.identity,
        ),
        _gate(
            "cost_of_debt_input_completeness",
            debt_is_zero
            or (
                cost_of_debt_methodology == "interest_expense_over_average_debt"
                and interest_expense is not None
                and average_debt is not None
                and interest_expense.metric == "interest_expense"
                and average_debt.value > 0
            )
            or (
                cost_of_debt_methodology == "market_debt_yield"
                and cost_of_debt is not None
                and cost_of_debt.issuer_id == security_id
                and cost_of_debt.methodology == cost_of_debt_methodology
            ),
            debt.identity,
            *(item.identity for item in debt_cost_inputs),
        ),
        _gate(
            "temporal_compatibility",
            all(
                (research_as_of - item.observed_at).days >= 0
                and (research_as_of - item.observed_at).days <= requirements.max_age_days
                for item in temporal_inputs
            ),
            *(
                item.identity for item in temporal_inputs
            ),
        ),
    )
    if any(gate.status is GateStatus.FAIL for gate in gates):
        failures = ",".join(gate.identifier for gate in gates if gate.status is GateStatus.FAIL)
        if "cost_of_debt_input_completeness" in failures:
            raise CapitalCostError("COST_OF_DEBT_UNAVAILABLE")
        raise CapitalCostError(f"CAPITAL_COST_GATE_FAILED:{failures}")
    if debt_is_zero:
        pre_tax_cost_of_debt = 0.0
    elif cost_of_debt_methodology == "market_debt_yield":
        if cost_of_debt is None:
            raise CapitalCostError("COST_OF_DEBT_UNAVAILABLE")
        pre_tax_cost_of_debt = cost_of_debt.value
    else:
        if interest_expense is None or average_debt is None:
            raise CapitalCostError("COST_OF_DEBT_UNAVAILABLE")
        pre_tax_cost_of_debt = interest_expense.value / average_debt.value
    after_tax_cost_of_debt = pre_tax_cost_of_debt * (1 - tax_rate.value)
    cost_of_equity, equity_weight, debt_weight, wacc = _calculate_wacc_components(
        risk_free_rate=risk_free.value,
        equity_risk_premium=equity_risk_premium.value,
        beta=beta.value,
        pre_tax_cost_of_debt=pre_tax_cost_of_debt,
        tax_rate=tax_rate.value,
        market_equity=market_equity.value,
        debt=debt.value,
    )
    input_items: tuple[
        tuple[
            str,
            RateEvidence
            | CostOfDebtEvidence
            | BetaEvidence
            | TaxRateEvidence
            | IssuerValueEvidence,
        ],
        ...
    ] = (
        ("risk_free", risk_free),
        ("equity_risk_premium", equity_risk_premium),
        ("beta", beta),
        ("tax_rate", tax_rate),
        ("market_equity", market_equity),
        ("debt", debt),
    )
    if not debt_is_zero:
        if cost_of_debt_methodology == "market_debt_yield":
            if cost_of_debt is None:
                raise CapitalCostError("COST_OF_DEBT_UNAVAILABLE")
            input_items += (("cost_of_debt", cost_of_debt),)
        else:
            if interest_expense is None or average_debt is None:
                raise CapitalCostError("COST_OF_DEBT_UNAVAILABLE")
            input_items += (
                ("interest_expense", interest_expense),
                ("average_debt", average_debt),
            )
    inputs = tuple(
        (name, item.identity) for name, item in input_items
    )
    payload = {
        "research_as_of": research_as_of.isoformat(),
        "methodology": requirements.methodology_id,
        "inputs": inputs,
        "values": [
            cost_of_equity,
            pre_tax_cost_of_debt,
            after_tax_cost_of_debt,
            equity_weight,
            debt_weight,
            wacc,
        ],
    }
    provenance = CapitalCostProvenance(
        research_as_of,
        "canonical",
        requirements.methodology_id,
        inputs,
        gates + (Gate("derivation_reproducibility", GateStatus.PASS, True),),
        content_identity(payload),
    )
    return CapitalCostResult(
        risk_free.value,
        equity_risk_premium.value,
        beta.value,
        cost_of_equity,
        pre_tax_cost_of_debt,
        after_tax_cost_of_debt,
        tax_rate.value,
        market_equity.value,
        debt.value,
        equity_weight,
        debt_weight,
        wacc,
        provenance,
    )
