"""Evidence-to-accounting normalization for the FCFF research engine.

This intentionally small boundary converts checked filing facts into one accounting
snapshot.  Company adapters provide *which* disclosed facts represent a line item;
this module owns period, unit, sign, aggregation and lineage checks.  It does not
invent a value when an input is absent.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

from .evidence import DerivedFact, FinancialFact, PeriodKind, reconstruct_ttm


class AccountingError(ValueError):
    """Raised when evidence cannot support a normalized accounting input."""


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


@dataclass(frozen=True)
class AccountingSnapshot:
    """Normalized TTM FCFF inputs in one monetary unit, with source lineage.

    Capex and change in operating working capital are positive uses of cash.  Tax is
    an explicit analyst assumption here because the committed QCOM filing evidence
    does not provide a normalized operating tax basis.
    """

    period_label: str
    period_end: date
    unit: str
    revenue: float | None
    ebit: float | None
    tax_rate: float | None
    depreciation_amortization: float | None
    capex: float | None
    change_in_working_capital: float | None
    invested_capital: float | None
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
            "invested_capital",
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
        return self.ebit * (1 - self.tax_rate)

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
        return nopat + self.depreciation_amortization - self.capex - self.change_in_working_capital


def _ttm(facts: dict[str, FinancialFact], spec: TtmFactSpec, name: str) -> DerivedFact:
    try:
        return reconstruct_ttm(
            annual=facts[spec.annual],
            prior_ytd=facts[spec.prior_ytd],
            current_ytd=facts[spec.current_ytd],
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
    facts: dict[str, FinancialFact], ids: tuple[str, ...], name: str
) -> tuple[float, date, str]:
    if not ids:
        raise AccountingError(f"{name} requires at least one evidence fact")
    try:
        selected = tuple(facts[identifier] for identifier in ids)
    except KeyError as exc:
        raise AccountingError(f"missing evidence for {name}: {exc.args[0]}") from exc
    if any(item.period_kind is not PeriodKind.INSTANT for item in selected):
        raise AccountingError(f"{name} requires instant facts")
    if (
        len({item.period_end for item in selected}) != 1
        or len({item.unit for item in selected}) != 1
    ):
        raise AccountingError(f"{name} facts must share one period end and unit")
    return sum(item.value for item in selected), selected[0].period_end, selected[0].unit


def _valuation_shares(
    facts: dict[str, FinancialFact],
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
    facts: dict[str, FinancialFact], *, spec: AccountingEvidenceSpec, tax_rate: float | None
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
    opening_noa, opening_noa_end, noa_unit = _instant_sum(
        facts, spec.net_operating_assets_opening, "opening operating assets"
    )
    closing_noa, closing_noa_end, closing_noa_unit = _instant_sum(
        facts, spec.net_operating_assets_closing, "closing operating assets"
    )
    cash, cash_end, cash_unit = _instant_sum(facts, spec.cash, "cash")
    securities, securities_end, securities_unit = _instant_sum(
        facts, spec.marketable_securities, "marketable securities"
    )
    debt, debt_end, debt_unit = _instant_sum(facts, spec.debt, "debt")
    if opening_end != opening_liability_end or opening_end != opening_noa_end:
        raise AccountingError("opening operating facts must share one period end")
    if (
        closing_end != closing_liability_end
        or closing_end != closing_noa_end
        or closing_end != cash_end
        or closing_end != securities_end
        or closing_end != debt_end
    ):
        raise AccountingError("closing operating and capital facts must share one period end")
    if revenue.period_end != closing_end:
        raise AccountingError("TTM flow facts must end on the closing balance-sheet date")
    if spec.require_ttm_endpoint_alignment and opening_end != revenue.period_start - timedelta(
        days=1
    ):
        raise AccountingError("opening balance-sheet date must precede the TTM flow window")
    if {
        unit,
        opening_liability_unit,
        closing_unit,
        closing_liability_unit,
        noa_unit,
        closing_noa_unit,
        cash_unit,
        securities_unit,
        debt_unit,
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
    )
    return AccountingSnapshot(
        period_label="TTM",
        period_end=revenue.period_end,
        unit=revenue.unit,
        revenue=revenue.value,
        ebit=ebit.value,
        tax_rate=tax_rate,
        depreciation_amortization=da.value,
        capex=_normalize_capex_cash_use(capex.value, spec.capex_source_sign),
        change_in_working_capital=(closing_assets - closing_liabilities)
        - (opening_assets - opening_liabilities),
        invested_capital=(
            (opening_assets - opening_liabilities + opening_noa)
            + (closing_assets - closing_liabilities + closing_noa)
        )
        / 2,
        cash=cash,
        marketable_securities=securities,
        debt=debt,
        valuation_shares=shares,
        valuation_share_basis=spec.valuation_share_basis,
        source_lineage=lineage,
    )
