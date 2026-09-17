"""Evidence-to-accounting normalization for the FCFF research engine.

This intentionally small boundary converts checked filing facts into one accounting
snapshot.  Company adapters provide *which* disclosed facts represent a line item;
this module owns period, unit, sign, aggregation and lineage checks.  It does not
invent a value when an input is absent.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator, model_validator

from .evidence import DerivedFact, FinancialFact, PeriodKind, reconstruct_ttm
from .financial_primitives import (
    FinancialPrimitiveError,
    calculate_effective_tax_rate,
    calculate_fcff,
    calculate_nopat,
)
from .financial_temporal import TTMWindow

if TYPE_CHECKING:
    from .analysis import CompanyIdentity
    from .local_sec_corpus import LocalSecCorpus


class AccountingError(ValueError):
    """Raised when evidence cannot support a normalized accounting input."""


class DataState(str, Enum):
    """Whether a component has an explicit source value at one endpoint."""

    REPORTED_VALUE = "REPORTED_VALUE"
    REPORTED_ZERO = "REPORTED_ZERO"
    MISSING_OR_CONSOLIDATED = "MISSING_OR_CONSOLIDATED"


class ICMethod(str, Enum):
    """The independent invested-capital identities."""

    FINANCING_IDENTITY = "FINANCING_IDENTITY"
    BOTTOM_UP = "BOTTOM_UP"


class ReconciliationStatus(str, Enum):
    """The reconciliation result for one balance-sheet endpoint."""

    ALIGNED = "ALIGNED"
    MATERIAL_GAP = "MATERIAL_GAP"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class ICComponent(BaseModel):
    """One audited capital component, never an implicit numeric default."""

    value: float | None
    state: DataState
    provenance: list[str] = Field(default_factory=list)

    @field_validator("value")
    @classmethod
    def _value_is_finite(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("invested-capital component value must be finite")
        return value

    @model_validator(mode="after")
    def _state_matches_value(self) -> ICComponent:
        if self.state is DataState.MISSING_OR_CONSOLIDATED:
            if self.value is not None:
                raise ValueError("MISSING_OR_CONSOLIDATED components must not carry a value")
        elif self.state is DataState.REPORTED_ZERO:
            if self.value != 0.0:
                raise ValueError("REPORTED_ZERO requires an explicit numeric zero")
        elif self.value is None or self.value == 0.0:
            raise ValueError("REPORTED_VALUE requires an explicit non-zero value")
        return self


class ICNode(BaseModel):
    """One method's capital result at a balance-sheet endpoint."""

    value: float | None
    as_of: date
    method: ICMethod
    components: dict[str, ICComponent]
    state: DataState
    provenance: list[str] = Field(default_factory=list)

    @field_validator("value")
    @classmethod
    def _node_value_is_finite(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("invested-capital node value must be finite")
        return value

    @model_validator(mode="after")
    def _node_state_matches_value(self) -> ICNode:
        if self.state is DataState.MISSING_OR_CONSOLIDATED:
            if self.value is not None:
                raise ValueError("missing invested-capital node must not carry a value")
        elif self.state is DataState.REPORTED_ZERO:
            if self.value != 0.0:
                raise ValueError("zero invested-capital node requires an explicit numeric zero")
        elif self.value is None or self.value == 0.0:
            raise ValueError("reported invested-capital node requires a non-zero value")
        return self


class ICReconciliation(BaseModel):
    """Top-down and bottom-up results, reconciled at one exact date."""

    as_of: date
    top_down: ICNode
    bottom_up: ICNode | None
    gap: float | None
    gap_pct: float | None
    status: ReconciliationStatus
    possible_causes: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class TtmFactSpec:
    annual: str
    prior_ytd: str
    current_ytd: str


@dataclass(frozen=True)
class AccountingEvidenceSpec:
    """A declarative mapping from evidence identifiers to FCFF accounting lines."""

    revenue: TtmFactSpec
    ebit: TtmFactSpec
    depreciation_amortization: TtmFactSpec
    capex: TtmFactSpec
    income_tax_expense: TtmFactSpec | None
    pretax_income: TtmFactSpec | None
    capex_source_sign: str
    operating_nwc_opening_assets: tuple[str, ...]
    operating_nwc_opening_liabilities: tuple[str, ...]
    operating_nwc_closing_assets: tuple[str, ...]
    operating_nwc_closing_liabilities: tuple[str, ...]
    net_operating_assets_opening: tuple[str, ...]
    net_operating_assets_closing: tuple[str, ...]
    cash: tuple[str, ...]
    marketable_securities: tuple[str, ...]
    debt: tuple[str, ...]
    valuation_shares: str
    valuation_share_basis: str
    require_ttm_endpoint_alignment: bool = False
    invested_capital_opening_components: tuple[tuple[str, tuple[str, ...]], ...] = ()
    invested_capital_closing_components: tuple[tuple[str, tuple[str, ...]], ...] = ()
    legacy_invested_capital_adapter: bool = False


_GENERIC_IC_OPENING_COMPONENTS = (
    ("common_equity", ("common_equity_opening",)),
    ("total_debt", ("total_debt_opening",)),
    ("cash_and_equivalents", ("cash_opening",)),
    ("total_marketable_securities", ("marketable_securities_opening",)),
    ("operating_lease_liabilities", ()),
    ("current_assets", ("current_assets_opening",)),
    ("short_term_investments", ("marketable_securities_current_opening",)),
    ("operating_current_liabilities", ("operating_current_liabilities_opening",)),
    ("net_ppe", ("net_ppe_opening",)),
    ("net_intangibles", ("net_intangibles_opening",)),
    ("other_noncurrent_operating_assets", ()),
    ("other_noncurrent_operating_liabilities", ()),
)

_GENERIC_IC_CLOSING_COMPONENTS = (
    ("common_equity", ("common_equity",)),
    ("total_debt", ("total_debt",)),
    ("cash_and_equivalents", ("cash",)),
    ("total_marketable_securities", ("marketable_securities",)),
    ("operating_lease_liabilities", ()),
    ("current_assets", ("current_assets",)),
    ("short_term_investments", ("marketable_securities_current",)),
    ("operating_current_liabilities", ("operating_current_liabilities_closing",)),
    ("net_ppe", ("net_ppe",)),
    ("net_intangibles", ("net_intangibles",)),
    ("other_noncurrent_operating_assets", ()),
    ("other_noncurrent_operating_liabilities", ()),
)

_GENERIC_IC_METRIC_IDS = frozenset(
    metric_id
    for _, metric_ids in _GENERIC_IC_OPENING_COMPONENTS + _GENERIC_IC_CLOSING_COMPONENTS
    for metric_id in metric_ids
)


def accounting_evidence_spec_from_promoted_facts(
    facts: Mapping[str, FinancialFact],
) -> AccountingEvidenceSpec:
    """Build the accounting contract from canonical promoted evidence."""
    from .financial_promotion import ACCOUNTING_EVIDENCE_POLICY_FIELDS

    metric_ids = set(ACCOUNTING_EVIDENCE_POLICY_FIELDS.values())
    noa_ids = {
        "net_operating_assets_opening",
        "net_operating_assets_closing",
    }
    required_ids = metric_ids - noa_ids

    missing = required_ids - set(facts)
    if missing:
        raise AccountingError(
            f"missing promoted accounting metric: {sorted(missing)[0]}"
        )

    present_noa = noa_ids & set(facts)
    if present_noa and present_noa != noa_ids:
        raise AccountingError(
            "invested capital requires both opening and closing promoted operating assets"
        )

    used_ids = required_ids | present_noa
    if len({facts[metric_id].id for metric_id in used_ids}) != len(used_ids):
        raise AccountingError("conflicting duplicate promoted accounting metric")

    def ttm(metric_id: str) -> TtmFactSpec:
        return TtmFactSpec(metric_id, metric_id, metric_id)

    has_noa = present_noa == noa_ids

    return AccountingEvidenceSpec(
        revenue=ttm("revenue"),
        ebit=ttm("ebit"),
        depreciation_amortization=ttm("depreciation_amortization"),
        capex=ttm("capex"),
        income_tax_expense=ttm("income_tax_expense"),
        pretax_income=ttm("pretax_income"),
        capex_source_sign="positive_cash_use",
        operating_nwc_opening_assets=("operating_current_assets_opening",),
        operating_nwc_opening_liabilities=("operating_current_liabilities_opening",),
        operating_nwc_closing_assets=("operating_current_assets_closing",),
        operating_nwc_closing_liabilities=("operating_current_liabilities_closing",),
        net_operating_assets_opening=(
            ("net_operating_assets_opening",) if has_noa else ()
        ),
        net_operating_assets_closing=(
            ("net_operating_assets_closing",) if has_noa else ()
        ),
        cash=("cash",),
        marketable_securities=("marketable_securities",),
        debt=("total_debt",),
        valuation_shares="valuation_shares",
        valuation_share_basis="common_shares_outstanding",
        require_ttm_endpoint_alignment=True,
        invested_capital_opening_components=_GENERIC_IC_OPENING_COMPONENTS,
        invested_capital_closing_components=_GENERIC_IC_CLOSING_COMPONENTS,
    )


def promote_local_sec_accounting_evidence(
    corpus: LocalSecCorpus, identity: CompanyIdentity
) -> tuple[dict[str, FinancialFact], AccountingEvidenceSpec]:
    """Promote validated local SEC evidence into the generic accounting contract."""

    from .financial_canonicalization import extract_company_facts
    from .financial_promotion import (
        FinancialPromotionError,
        MultiPeriodFinancialPromoter,
        accounting_evidence_policies,
        validate_accounting_evidence_policy_coverage,
    )

    evidence = corpus.evidence(identity)
    raw_facts = extract_company_facts(
        evidence.companyfacts,
        source_identity=evidence.companyfacts_identity,
    )
    promoter = MultiPeriodFinancialPromoter()

    # Revenue defines the actual TTM accounting window.
    bootstrap_policies = accounting_evidence_policies()
    revenue_policy = next(
        (
            policy
            for policy in bootstrap_policies
            if policy.metric_id == "revenue"
        ),
        None,
    )
    if revenue_policy is None:
        raise AccountingError("revenue promotion policy is missing")

    revenue = promoter.promote(raw_facts, policy=revenue_policy)
    if revenue.period_start is None:
        raise AccountingError("promoted revenue has no TTM period start")

    opening_end = revenue.period_start - timedelta(days=1)
    closing_end = revenue.period_end

    policies = accounting_evidence_policies(
        opening_end=opening_end,
        closing_end=closing_end,
    )
    coverage = validate_accounting_evidence_policy_coverage(policies)
    required = set(coverage.values())

    noa_ids = {
        "net_operating_assets_opening",
        "net_operating_assets_closing",
    }

    # Everything used by FCFF / capital structure remains mandatory.
    promoted = {
        policy.metric_id: promoter.promote(raw_facts, policy=policy)
        for policy in policies
        if policy.metric_id in required - noa_ids
    }

    # Invested capital is an optional analytical extension, but only as a
    # temporally homogeneous opening/closing pair.
    noa_policies = {
        policy.metric_id: policy
        for policy in policies
        if policy.metric_id in noa_ids
    }
    if set(noa_policies) != noa_ids:
        raise AccountingError("invested-capital promotion policies are incomplete")

    try:
        promoted_noa = {
            metric_id: promoter.promote(raw_facts, policy=noa_policies[metric_id])
            for metric_id in noa_ids
        }
    except FinancialPromotionError:
        promoted_noa = {}

    promoted.update(promoted_noa)

    component_policies = {
        policy.metric_id: policy
        for policy in policies
        if policy.metric_id in _GENERIC_IC_METRIC_IDS
    }
    if set(component_policies) != _GENERIC_IC_METRIC_IDS:
        raise AccountingError("invested-capital component promotion policies are incomplete")
    for metric_id, policy in component_policies.items():
        try:
            promoted[metric_id] = promoter.promote(raw_facts, policy=policy)
        except FinancialPromotionError:
            # A policy records unavailable evidence as missing at the component
            # boundary; it never fabricates a reported numeric zero.
            continue

    return promoted, accounting_evidence_spec_from_promoted_facts(promoted)


class InvestedCapitalPair(BaseModel):
    """A reconciling opening/closing primary-capital pair for ROIC."""

    opening: ICReconciliation
    closing: ICReconciliation
    method: ICMethod = ICMethod.FINANCING_IDENTITY

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_numeric_endpoints(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        opening = value.get("opening")
        closing = value.get("closing")
        if isinstance(opening, (int, float)) and isinstance(closing, (int, float)):
            return {
                **value,
                "opening": _legacy_reconciliation(float(opening), date.min, []),
                "closing": _legacy_reconciliation(float(closing), date.max, []),
            }
        return value

    @property
    def average(self) -> float:
        for endpoint in (self.opening, self.closing):
            if endpoint.status is ReconciliationStatus.MATERIAL_GAP:
                raise ValueError(
                    "Cannot average invested capital: unresolved material reconciliation gap."
                )
            if endpoint.top_down.value is None:
                raise ValueError(
                    "Cannot average invested capital: missing primary financing identity."
                )
        assert self.opening.top_down.value is not None
        assert self.closing.top_down.value is not None
        return (self.opening.top_down.value + self.closing.top_down.value) / 2.0

    @classmethod
    def from_optional(
        cls, opening: float | None, closing: float | None
    ) -> InvestedCapitalPair | None:
        if opening is None and closing is None:
            return None
        if opening is None or closing is None:
            raise AccountingError("PARTIAL_INVESTED_CAPITAL_PAIR")
        return cls.model_validate({"opening": opening, "closing": closing})


def component_from_source(
    value: float | None,
    *,
    provenance: list[str] | None = None,
) -> ICComponent:
    """Preserve the distinction between a reported zero and unavailable evidence."""
    if value is None:
        state = DataState.MISSING_OR_CONSOLIDATED
    elif value == 0.0:
        state = DataState.REPORTED_ZERO
    else:
        state = DataState.REPORTED_VALUE
    return ICComponent(value=value, state=state, provenance=provenance or [])


def _node_state(value: float | None) -> DataState:
    if value is None:
        return DataState.MISSING_OR_CONSOLIDATED
    if value == 0.0:
        return DataState.REPORTED_ZERO
    return DataState.REPORTED_VALUE


def _with_missing_components(
    components: Mapping[str, ICComponent], required: tuple[str, ...]
) -> dict[str, ICComponent]:
    result = dict(components)
    for name in required:
        result.setdefault(name, component_from_source(None))
    return result


def _provenance(components: Mapping[str, ICComponent]) -> list[str]:
    return [source for component in components.values() for source in component.provenance]


def _has_value(component: ICComponent) -> bool:
    return component.value is not None


def build_financing_identity_invested_capital(
    as_of: date,
    components: Mapping[str, ICComponent],
) -> ICNode:
    """Compute capital from mutually exclusive financing claim/asset representations."""
    required = (
        "common_equity",
        "total_debt",
        "short_term_debt",
        "long_term_debt",
        "cash_and_equivalents",
        "total_marketable_securities",
        "short_term_investments",
        "long_term_marketable_securities",
    )
    normalized = _with_missing_components(components, required)
    total_debt = normalized["total_debt"]
    short_debt = normalized["short_term_debt"]
    long_debt = normalized["long_term_debt"]
    total_securities = normalized["total_marketable_securities"]
    short_investments = normalized["short_term_investments"]
    long_securities = normalized["long_term_marketable_securities"]
    leases = normalized.get("operating_lease_liabilities", component_from_source(None))

    if _has_value(total_debt) and (_has_value(short_debt) or _has_value(long_debt)):
        raise AccountingError("DEBT_DOUBLE_COUNT")
    if _has_value(total_securities) and (
        _has_value(short_investments) or _has_value(long_securities)
    ):
        raise AccountingError("SECURITIES_DOUBLE_COUNT")
    if _has_value(total_debt) and _has_value(leases):
        raise AccountingError("LEASE_DOUBLE_COUNT")

    debt: float | None
    if _has_value(total_debt):
        debt = total_debt.value
    elif _has_value(short_debt) and _has_value(long_debt):
        assert short_debt.value is not None and long_debt.value is not None
        debt = short_debt.value + long_debt.value
    else:
        debt = None

    securities: float | None
    if _has_value(total_securities):
        securities = total_securities.value
    elif _has_value(short_investments) and _has_value(long_securities):
        assert short_investments.value is not None and long_securities.value is not None
        securities = short_investments.value + long_securities.value
    else:
        securities = None

    common_equity = normalized["common_equity"]
    cash = normalized["cash_and_equivalents"]
    if not (
        _has_value(common_equity)
        and _has_value(cash)
        and debt is not None
        and securities is not None
    ):
        return ICNode(
            value=None,
            as_of=as_of,
            method=ICMethod.FINANCING_IDENTITY,
            components=normalized,
            state=DataState.MISSING_OR_CONSOLIDATED,
            provenance=_provenance(normalized),
        )

    optional_additions = ("minority_interest", "other_financing_claims")
    optional_subtractions = ("other_nonoperating_financial_assets",)
    additions = 0.0
    for name in optional_additions:
        component = normalized.get(name)
        if component is not None and component.value is not None:
            additions += component.value
    subtractions = 0.0
    for name in optional_subtractions:
        component = normalized.get(name)
        if component is not None and component.value is not None:
            subtractions += component.value
    lease_value = leases.value if leases.value is not None else 0.0
    assert common_equity.value is not None and cash.value is not None
    value = (
        common_equity.value
        + debt
        + lease_value
        + additions
        - cash.value
        - securities
        - subtractions
    )
    return ICNode(
        value=value,
        as_of=as_of,
        method=ICMethod.FINANCING_IDENTITY,
        components=normalized,
        state=_node_state(value),
        provenance=_provenance(normalized),
    )


def build_bottom_up_invested_capital(
    as_of: date,
    components: Mapping[str, ICComponent],
) -> ICNode:
    """Compute the independent operating-capital reconciliation identity."""
    required = (
        "current_assets",
        "cash_and_equivalents",
        "short_term_investments",
        "operating_current_liabilities",
        "net_ppe",
        "net_intangibles",
        "other_noncurrent_operating_assets",
        "other_noncurrent_operating_liabilities",
    )
    normalized = _with_missing_components(components, required)
    if any(normalized[name].value is None for name in required):
        return ICNode(
            value=None,
            as_of=as_of,
            method=ICMethod.BOTTOM_UP,
            components=normalized,
            state=DataState.MISSING_OR_CONSOLIDATED,
            provenance=_provenance(normalized),
        )
    values: dict[str, float] = {}
    for name in required:
        component = normalized[name]
        assert component.value is not None
        values[name] = component.value
    operating_nwc = (
        values["current_assets"]
        - values["cash_and_equivalents"]
        - values["short_term_investments"]
        - values["operating_current_liabilities"]
    )
    value = (
        operating_nwc
        + values["net_ppe"]
        + values["net_intangibles"]
        + values["other_noncurrent_operating_assets"]
        - values["other_noncurrent_operating_liabilities"]
    )
    return ICNode(
        value=value,
        as_of=as_of,
        method=ICMethod.BOTTOM_UP,
        components=normalized,
        state=_node_state(value),
        provenance=_provenance(normalized),
    )


def reconcile_invested_capital(
    as_of: date,
    top_down: ICNode,
    bottom_up: ICNode | None,
) -> ICReconciliation:
    """Apply the reconciliation gate without substituting either identity."""
    if top_down.as_of != as_of or (bottom_up is not None and bottom_up.as_of != as_of):
        raise AccountingError("invested-capital reconciliation endpoints must match")
    if top_down.value is None:
        return ICReconciliation(
            as_of=as_of,
            top_down=top_down,
            bottom_up=bottom_up,
            gap=None,
            gap_pct=None,
            status=ReconciliationStatus.INSUFFICIENT_DATA,
            possible_causes=["PRIMARY_IC_REQUIRED"],
        )
    if bottom_up is None or bottom_up.value is None:
        return ICReconciliation(
            as_of=as_of,
            top_down=top_down,
            bottom_up=bottom_up,
            gap=None,
            gap_pct=None,
            status=ReconciliationStatus.INSUFFICIENT_DATA,
            possible_causes=["BOTTOM_UP_INSUFFICIENT_DATA"],
        )

    gap = bottom_up.value - top_down.value
    if top_down.value == 0.0:
        gap_pct = 0.0 if bottom_up.value == 0.0 else None
        status = (
            ReconciliationStatus.ALIGNED
            if bottom_up.value == 0.0
            else ReconciliationStatus.MATERIAL_GAP
        )
    else:
        gap_pct = abs(gap) / abs(top_down.value)
        status = (
            ReconciliationStatus.ALIGNED
            if gap_pct <= 0.05
            else ReconciliationStatus.MATERIAL_GAP
        )
    return ICReconciliation(
        as_of=as_of,
        top_down=top_down,
        bottom_up=bottom_up,
        gap=gap,
        gap_pct=gap_pct,
        status=status,
        possible_causes=(
            [] if status is ReconciliationStatus.ALIGNED else ["CAPITAL_RECONCILIATION_GAP"]
        ),
    )


@dataclass(frozen=True)
class AccountingSnapshot:
    """Normalized TTM FCFF inputs in one monetary unit, with source lineage.

    Capex and change in operating working capital are positive uses of cash.
    """

    period_label: str
    period_end: date
    unit: str
    revenue: float | None
    ebit: float | None
    tax_rate: float | None
    income_tax_expense: float | None
    pretax_income: float | None
    depreciation_amortization: float | None
    capex: float | None
    change_in_working_capital: float | None
    invested_capital: InvestedCapitalPair | None
    cash: float | None
    marketable_securities: float | None
    debt: float | None
    valuation_shares: float | None
    valuation_share_basis: str
    source_lineage: tuple[str, ...]

    def __post_init__(self) -> None:
        """Defend the canonical cash-use contract at the accounting boundary."""
        for field in (
            "revenue",
            "ebit",
            "tax_rate",
            "depreciation_amortization",
            "capex",
            "change_in_working_capital",
            "cash",
            "marketable_securities",
            "debt",
            "valuation_shares",
        ):
            value = getattr(self, field)
            if value is not None and not math.isfinite(value):
                raise AccountingError(f"{field} must be finite when supplied")
        if self.capex is not None and self.capex < 0:
            raise AccountingError("capex_cash_use must be non-negative")

    @property
    def nopat(self) -> float | None:
        if self.ebit is None or self.tax_rate is None:
            return None
        try:
            return calculate_nopat(ebit=self.ebit, tax_rate=self.tax_rate)
        except FinancialPrimitiveError as exc:
            raise AccountingError(str(exc)) from exc

    @property
    def fcff(self) -> float | None:
        nopat = self.nopat
        values = (nopat, self.depreciation_amortization, self.capex, self.change_in_working_capital)
        if any(value is None for value in values):
            return None
        assert nopat is not None
        assert self.depreciation_amortization is not None
        assert self.capex is not None
        assert self.change_in_working_capital is not None
        try:
            return calculate_fcff(
                nopat=nopat,
                depreciation_amortization=self.depreciation_amortization,
                capex=self.capex,
                change_in_working_capital=self.change_in_working_capital,
            )
        except FinancialPrimitiveError as exc:
            raise AccountingError(str(exc)) from exc


def _ttm(
    facts: Mapping[str, FinancialFact | DerivedFact], spec: TtmFactSpec, name: str
) -> DerivedFact:
    try:
        if spec.annual == spec.prior_ytd == spec.current_ytd:
            promoted = facts[spec.annual]
            if isinstance(promoted, DerivedFact):
                return promoted
        annual = facts[spec.annual]
        prior_ytd = facts[spec.prior_ytd]
        current_ytd = facts[spec.current_ytd]
        if (
            not isinstance(annual, FinancialFact)
            or not isinstance(prior_ytd, FinancialFact)
            or not isinstance(current_ytd, FinancialFact)
        ):
            raise AccountingError(f"{name} TTM inputs must be financial facts")
        return reconstruct_ttm(
            annual=annual,
            prior_ytd=prior_ytd,
            current_ytd=current_ytd,
            identifier=f"ttm_{name}",
        )
    except KeyError as exc:
        raise AccountingError(f"missing evidence for {name}: {exc.args[0]}") from exc


def _normalize_capex_cash_use(value: float, source_sign: str) -> float:
    """Convert an explicitly declared source sign to canonical positive cash use."""
    if source_sign == "negative_cash_outflow":
        if value > 0:
            raise AccountingError(
                "capex raw source must be non-positive under negative_cash_outflow"
            )
        return -value
    if source_sign == "positive_cash_use":
        if value < 0:
            raise AccountingError("capex raw source must be non-negative under positive_cash_use")
        return value
    raise AccountingError(
        "capex_source_sign must declare negative_cash_outflow or positive_cash_use"
    )


def _instant_sum(
    facts: Mapping[str, FinancialFact | DerivedFact], ids: tuple[str, ...], name: str
) -> tuple[float, date, str]:
    if not ids:
        raise AccountingError(f"{name} requires at least one evidence fact")
    try:
        selected = tuple(facts[identifier] for identifier in ids)
    except KeyError as exc:
        raise AccountingError(f"missing evidence for {name}: {exc.args[0]}") from exc
    if any(
        not isinstance(item, FinancialFact) or item.period_kind is not PeriodKind.INSTANT
        for item in selected
    ):
        raise AccountingError(f"{name} requires instant facts")
    if (
        len({item.period_end for item in selected}) != 1
        or len({item.unit for item in selected}) != 1
    ):
        raise AccountingError(f"{name} facts must share one period end and unit")
    return sum(item.value for item in selected), selected[0].period_end, selected[0].unit


def _ic_component_from_promoted_facts(
    facts: Mapping[str, FinancialFact | DerivedFact],
    identifiers: tuple[str, ...],
    *,
    as_of: date,
    unit: str,
    name: str,
) -> ICComponent:
    """Convert only compatible promoted instant facts into one auditable component."""
    if not identifiers:
        return component_from_source(None)
    if any(identifier not in facts for identifier in identifiers):
        return component_from_source(None)
    value, period_end, component_unit = _instant_sum(facts, identifiers, name)
    if period_end != as_of:
        raise AccountingError(f"{name} must end on its invested-capital endpoint")
    if component_unit != unit:
        raise AccountingError(f"{name} must use the accounting monetary unit")
    selected = tuple(facts[identifier] for identifier in identifiers)
    provenance = [
        source_id
        for item in selected
        if isinstance(item, FinancialFact)
        for source_id in (item.source_fact_ids or (item.id,))
    ]
    return component_from_source(value, provenance=provenance)


def _ic_components_from_promoted_facts(
    facts: Mapping[str, FinancialFact | DerivedFact],
    specifications: tuple[tuple[str, tuple[str, ...]], ...],
    *,
    as_of: date,
    unit: str,
) -> dict[str, ICComponent]:
    return {
        name: _ic_component_from_promoted_facts(
            facts,
            identifiers,
            as_of=as_of,
            unit=unit,
            name=f"invested-capital component {name}",
        )
        for name, identifiers in specifications
    }


_FINANCING_COMPONENT_NAMES = frozenset(
    {
        "common_equity",
        "total_debt",
        "short_term_debt",
        "long_term_debt",
        "operating_lease_liabilities",
        "minority_interest",
        "other_financing_claims",
        "cash_and_equivalents",
        "total_marketable_securities",
        "long_term_marketable_securities",
        "other_nonoperating_financial_assets",
    }
)


def _financing_components_only(
    components: Mapping[str, ICComponent],
) -> dict[str, ICComponent]:
    """Keep the audit-only current-investment component out of the primary registry."""
    return {
        name: component
        for name, component in components.items()
        if name in _FINANCING_COMPONENT_NAMES
    }


def _legacy_reconciliation(
    value: float,
    as_of: date,
    provenance: list[str],
) -> ICReconciliation:
    """Represent an established legacy pair without treating it as generic promotion."""
    bottom_up = ICNode(
        value=value,
        as_of=as_of,
        method=ICMethod.BOTTOM_UP,
        components={
            "legacy_bottom_up_invested_capital": component_from_source(
                value, provenance=provenance
            )
        },
        state=_node_state(value),
        provenance=provenance,
    )
    top_down = ICNode(
        value=value,
        as_of=as_of,
        method=ICMethod.FINANCING_IDENTITY,
        components={
            "legacy_compatibility_capital": component_from_source(
                value, provenance=provenance
            )
        },
        state=_node_state(value),
        provenance=provenance,
    )
    return reconcile_invested_capital(as_of, top_down, bottom_up)


def _legacy_invested_capital_pair(
    *,
    opening: float,
    opening_as_of: date,
    closing: float,
    closing_as_of: date,
    provenance: list[str],
) -> InvestedCapitalPair:
    """Keep frozen legacy cases explicit while generic promotion uses financing identity."""
    return InvestedCapitalPair(
        opening=_legacy_reconciliation(opening, opening_as_of, provenance),
        closing=_legacy_reconciliation(closing, closing_as_of, provenance),
    )


def _valuation_shares(
    facts: Mapping[str, FinancialFact | DerivedFact],
    identifier: str,
    basis: str,
    monetary_unit: str,
    closing_end: date,
) -> tuple[float, str]:
    """Validate the declared valuation-share semantic instead of inferring it from a label."""
    try:
        shares = facts[identifier]
    except KeyError as exc:
        raise AccountingError(f"missing evidence for valuation shares: {exc.args[0]}") from exc
    if not isinstance(shares, FinancialFact):
        raise AccountingError("valuation shares require a financial fact")
    expected_unit = {
        "USD million": "million shares",
        "USD thousands": "thousand shares",
        "USD": "shares",
    }.get(monetary_unit)
    if expected_unit is None or shares.unit != expected_unit:
        raise AccountingError(
            "valuation shares must use the share-count scale matching the monetary unit"
        )
    allowed = {
        "common_shares_outstanding": ("EntityCommonStockSharesOutstanding", PeriodKind.INSTANT),
        "diluted_weighted_average": (
            "WeightedAverageNumberOfDilutedSharesOutstanding",
            PeriodKind.DURATION,
        ),
    }
    expected = allowed.get(basis)
    if expected is None:
        raise AccountingError("valuation share basis is unsupported")
    if (shares.concept, shares.period_kind) != expected:
        raise AccountingError("valuation share evidence does not match its declared basis")
    if basis == "diluted_weighted_average" and shares.period_end != closing_end:
        raise AccountingError("diluted weighted-average shares must end with the TTM closing date")
    return shares.value, shares.unit


def normalize_accounting_snapshot(
    facts: Mapping[str, FinancialFact | DerivedFact],
    *,
    spec: AccountingEvidenceSpec,
    tax_rate: float | None,
) -> AccountingSnapshot:
    """Create a TTM accounting snapshot or fail without replacing missing data by zero."""
    if tax_rate is not None and (not math.isfinite(tax_rate) or not 0 <= tax_rate < 1):
        raise AccountingError("tax_rate must be between 0% and 100% when supplied")
    revenue, ebit, da, capex = (
        _ttm(facts, spec.revenue, "revenue"),
        _ttm(facts, spec.ebit, "ebit"),
        _ttm(facts, spec.depreciation_amortization, "depreciation_amortization"),
        _ttm(facts, spec.capex, "capex"),
    )
    tax_expense = pretax_income = None
    if tax_rate is None:
        if (spec.income_tax_expense is None) != (spec.pretax_income is None):
            raise AccountingError("effective tax rate requires both canonical duration facts")
        if spec.income_tax_expense is not None and spec.pretax_income is not None:
            tax_expense = _ttm(facts, spec.income_tax_expense, "income tax expense")
            pretax_income = _ttm(facts, spec.pretax_income, "pretax income")
            if (
                tax_expense.unit != pretax_income.unit
                or tax_expense.period_start != pretax_income.period_start
                or tax_expense.period_end != pretax_income.period_end
            ):
                raise AccountingError(
                    "effective tax rate facts must share one duration period and unit"
                )
            try:
                tax_rate = calculate_effective_tax_rate(
                    tax_expense=tax_expense.value, pretax_income=pretax_income.value
                )
            except FinancialPrimitiveError as exc:
                raise AccountingError(str(exc)) from exc
    flow_items = (revenue, ebit, da, capex)
    if (
        len({item.unit for item in flow_items}) != 1
        or len({item.period_end for item in flow_items}) != 1
    ):
        raise AccountingError("TTM flow facts must share one unit and period end")
    opening_assets, opening_end, unit = _instant_sum(
        facts, spec.operating_nwc_opening_assets, "opening NWC assets"
    )
    opening_liabilities, opening_liability_end, opening_liability_unit = _instant_sum(
        facts, spec.operating_nwc_opening_liabilities, "opening NWC liabilities"
    )
    closing_assets, closing_end, closing_unit = _instant_sum(
        facts, spec.operating_nwc_closing_assets, "closing NWC assets"
    )
    closing_liabilities, closing_liability_end, closing_liability_unit = _instant_sum(
        facts, spec.operating_nwc_closing_liabilities, "closing NWC liabilities"
    )
    has_opening_noa = bool(spec.net_operating_assets_opening)
    has_closing_noa = bool(spec.net_operating_assets_closing)
    if has_opening_noa != has_closing_noa:
        raise AccountingError(
            "invested capital requires both opening and closing operating assets"
        )

    invested_capital: InvestedCapitalPair | None = None
    noa_units: set[str] = set()

    if has_opening_noa:
        opening_noa, opening_noa_end, noa_unit = _instant_sum(
            facts, spec.net_operating_assets_opening, "opening operating assets"
        )
        closing_noa, closing_noa_end, closing_noa_unit = _instant_sum(
            facts, spec.net_operating_assets_closing, "closing operating assets"
        )

        if opening_end != opening_noa_end:
            raise AccountingError("opening operating facts must share one period end")
        if closing_end != closing_noa_end:
            raise AccountingError("closing operating and capital facts must share one period end")

        noa_units = {noa_unit, closing_noa_unit}
        if spec.legacy_invested_capital_adapter:
            invested_capital = _legacy_invested_capital_pair(
                opening=opening_assets - opening_liabilities + opening_noa,
                opening_as_of=opening_end,
                closing=closing_assets - closing_liabilities + closing_noa,
                closing_as_of=closing_end,
                provenance=list(
                    spec.operating_nwc_opening_assets
                    + spec.operating_nwc_opening_liabilities
                    + spec.operating_nwc_closing_assets
                    + spec.operating_nwc_closing_liabilities
                    + spec.net_operating_assets_opening
                    + spec.net_operating_assets_closing
                ),
            )
    has_opening_components = bool(spec.invested_capital_opening_components)
    has_closing_components = bool(spec.invested_capital_closing_components)
    if has_opening_components != has_closing_components:
        raise AccountingError("invested capital requires both component endpoints")
    if has_opening_components:
        opening_components = _ic_components_from_promoted_facts(
            facts,
            spec.invested_capital_opening_components,
            as_of=opening_end,
            unit=revenue.unit,
        )
        closing_components = _ic_components_from_promoted_facts(
            facts,
            spec.invested_capital_closing_components,
            as_of=closing_end,
            unit=revenue.unit,
        )
        invested_capital = InvestedCapitalPair(
            opening=reconcile_invested_capital(
                opening_end,
                build_financing_identity_invested_capital(
                    opening_end, _financing_components_only(opening_components)
                ),
                build_bottom_up_invested_capital(opening_end, opening_components),
            ),
            closing=reconcile_invested_capital(
                closing_end,
                build_financing_identity_invested_capital(
                    closing_end, _financing_components_only(closing_components)
                ),
                build_bottom_up_invested_capital(closing_end, closing_components),
            ),
        )
    cash, cash_end, cash_unit = _instant_sum(facts, spec.cash, "cash")
    securities, securities_end, securities_unit = _instant_sum(
        facts, spec.marketable_securities, "marketable securities"
    )
    debt, debt_end, debt_unit = _instant_sum(facts, spec.debt, "debt")
    if opening_end != opening_liability_end:
        raise AccountingError("opening operating facts must share one period end")
    if (
        closing_end != closing_liability_end
        or closing_end != cash_end
        or closing_end != securities_end
        or closing_end != debt_end
    ):
        raise AccountingError("closing operating and capital facts must share one period end")
    window = TTMWindow(revenue.period_start, revenue.period_end)
    if window.closing_balance_date != closing_end:
        raise AccountingError("TTM flow facts must end on the closing balance-sheet date")
    if spec.require_ttm_endpoint_alignment and opening_end != window.opening_balance_date:
        raise AccountingError("opening balance-sheet date must precede the TTM flow window")
    if {
        unit,
        opening_liability_unit,
        closing_unit,
        closing_liability_unit,
        cash_unit,
        securities_unit,
        debt_unit,
        *noa_units,
    } != {revenue.unit}:
        raise AccountingError("monetary facts must use one unit")
    shares, _ = _valuation_shares(
        facts, spec.valuation_shares, spec.valuation_share_basis, revenue.unit, closing_end
    )
    lineage = (
        tuple(dict.fromkeys(item for ttm in flow_items for item in ttm.inputs))
        + spec.operating_nwc_opening_assets
        + spec.operating_nwc_opening_liabilities
        + spec.operating_nwc_closing_assets
        + spec.operating_nwc_closing_liabilities
        + spec.net_operating_assets_opening
        + spec.net_operating_assets_closing
        + spec.cash
        + spec.marketable_securities
        + spec.debt
        + (spec.valuation_shares,)
        + (() if spec.income_tax_expense is None else (spec.income_tax_expense.annual,))
        + (() if spec.pretax_income is None else (spec.pretax_income.annual,))
    )
    return AccountingSnapshot(
        period_label="TTM",
        period_end=revenue.period_end,
        unit=revenue.unit,
        revenue=revenue.value,
        ebit=ebit.value,
        tax_rate=tax_rate,
        income_tax_expense=None if tax_expense is None else tax_expense.value,
        pretax_income=None if pretax_income is None else pretax_income.value,
        depreciation_amortization=da.value,
        capex=_normalize_capex_cash_use(capex.value, spec.capex_source_sign),
        change_in_working_capital=(closing_assets - closing_liabilities)
        - (opening_assets - opening_liabilities),
        invested_capital=invested_capital,
        cash=cash,
        marketable_securities=securities,
        debt=debt,
        valuation_shares=shares,
        valuation_share_basis=spec.valuation_share_basis,
        source_lineage=lineage,
    )
