"""Promote comparable SEC company-facts periods without valuation logic."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from enum import Enum
from pathlib import Path
from typing import cast

from .evidence import (
    DerivedFact,
    EvidenceKind,
    FilingRef,
    FinancialFact,
    PeriodKind,
    reconstruct_ttm,
)
from .financial_canonicalization import RawFact
from .financial_primitives import FinancialPrimitiveError, calculate_net_working_capital


class FinancialPromotionError(ValueError):
    """No unique compatible SEC period set can be promoted."""


class PromotionStrategy(str, Enum):
    DIRECT_DURATION = "DIRECT_DURATION"
    TTM_DURATION = "TTM_DURATION"
    DIRECT_INSTANT = "DIRECT_INSTANT"
    COMPOSITE_INSTANT = "COMPOSITE_INSTANT"
    COMPOSITE_DURATION = "COMPOSITE_DURATION"
    DERIVED_INSTANT = "DERIVED_INSTANT"
    ALTERNATIVE = "ALTERNATIVE"


@dataclass(frozen=True)
class MetricPromotionPolicy:
    metric_id: str
    concepts: tuple[str, ...]
    unit: str
    strategy: PromotionStrategy
    component_coverages: tuple[str, ...] = ()
    dependencies: tuple[MetricPromotionPolicy, ...] = ()
    alternatives: tuple[MetricPromotionPolicy, ...] = ()
    derivation: str | None = None
    target_end: date | None = None
    taxonomy: str = "us-gaap"


ACCOUNTING_EVIDENCE_EXTERNAL_FIELDS = frozenset(
    {
        "capex_source_sign",
        "valuation_share_basis",
        "require_ttm_endpoint_alignment",
        "invested_capital_opening_components",
        "invested_capital_closing_components",
        "legacy_invested_capital_adapter",
    }
)

ACCOUNTING_EVIDENCE_POLICY_FIELDS = {
    "revenue": "revenue",
    "ebit": "ebit",
    "depreciation_amortization": "depreciation_amortization",
    "capex": "capex",
    "income_tax_expense": "income_tax_expense",
    "pretax_income": "pretax_income",
    "operating_nwc_opening_assets": "operating_current_assets_opening",
    "operating_nwc_opening_liabilities": "operating_current_liabilities_opening",
    "operating_nwc_closing_assets": "operating_current_assets_closing",
    "operating_nwc_closing_liabilities": "operating_current_liabilities_closing",
    "net_operating_assets_opening": "net_operating_assets_opening",
    "net_operating_assets_closing": "net_operating_assets_closing",
    "cash": "cash",
    "marketable_securities": "marketable_securities",
    "debt": "total_debt",
    "valuation_shares": "valuation_shares",
}


def _bind_instant_target_end(
    policy: MetricPromotionPolicy,
    target_end: date | None,
) -> MetricPromotionPolicy:
    dependencies = tuple(
        _bind_instant_target_end(dependency, target_end) for dependency in policy.dependencies
    )

    instant_strategies = {
        PromotionStrategy.DIRECT_INSTANT,
        PromotionStrategy.COMPOSITE_INSTANT,
        PromotionStrategy.DERIVED_INSTANT,
    }

    if policy.strategy in instant_strategies:
        return replace(
            policy,
            dependencies=dependencies,
            target_end=target_end,
        )

    if dependencies != policy.dependencies:
        return replace(policy, dependencies=dependencies)

    return policy


def accounting_evidence_policies(
    *,
    opening_end: date | None = None,
    closing_end: date | None = None,
) -> tuple[MetricPromotionPolicy, ...]:
    """Return generic SEC promotion policies required by AccountingEvidenceSpec."""

    # Component declarations establish the authorized SEC concepts used by
    # composite policies. They are not themselves AccountingEvidenceSpec fields.
    accounts_receivable = MetricPromotionPolicy(
        "accounts_receivable",
        ("AccountsReceivableNetCurrent",),
        "USD",
        PromotionStrategy.DIRECT_INSTANT,
    )
    inventory = MetricPromotionPolicy(
        "inventory",
        ("InventoryNet",),
        "USD",
        PromotionStrategy.DIRECT_INSTANT,
    )
    accounts_payable = MetricPromotionPolicy(
        "accounts_payable",
        ("AccountsPayableCurrent",),
        "USD",
        PromotionStrategy.DIRECT_INSTANT,
    )
    net_ppe = MetricPromotionPolicy(
        "net_ppe",
        ("PropertyPlantAndEquipmentNet",),
        "USD",
        PromotionStrategy.DIRECT_INSTANT,
    )
    net_intangibles = MetricPromotionPolicy(
        "net_intangibles",
        ("IntangibleAssetsNetExcludingGoodwill",),
        "USD",
        PromotionStrategy.DIRECT_INSTANT,
    )
    current_debt = MetricPromotionPolicy(
        "current_debt",
        ("LongTermDebtCurrent",),
        "USD",
        PromotionStrategy.DIRECT_INSTANT,
    )
    noncurrent_debt = MetricPromotionPolicy(
        "noncurrent_debt",
        ("LongTermDebtNoncurrent",),
        "USD",
        PromotionStrategy.DIRECT_INSTANT,
    )
    commercial_paper = MetricPromotionPolicy(
        "commercial_paper",
        ("CommercialPaper",),
        "USD",
        PromotionStrategy.DIRECT_INSTANT,
    )
    marketable_securities_current = MetricPromotionPolicy(
        "marketable_securities_current",
        ("MarketableSecuritiesCurrent",),
        "USD",
        PromotionStrategy.DIRECT_INSTANT,
        target_end=closing_end,
    )
    marketable_securities_noncurrent = MetricPromotionPolicy(
        "marketable_securities_noncurrent",
        ("MarketableSecuritiesNoncurrent",),
        "USD",
        PromotionStrategy.DIRECT_INSTANT,
        target_end=closing_end,
    )
    common_equity = MetricPromotionPolicy(
        "common_equity",
        ("StockholdersEquity",),
        "USD",
        PromotionStrategy.DIRECT_INSTANT,
        target_end=closing_end,
    )
    current_assets = MetricPromotionPolicy(
        "current_assets",
        ("AssetsCurrent",),
        "USD",
        PromotionStrategy.DIRECT_INSTANT,
        target_end=closing_end,
    )

    policies = (
        MetricPromotionPolicy(
            "revenue",
            ("RevenueFromContractWithCustomerExcludingAssessedTax",),
            "USD",
            PromotionStrategy.TTM_DURATION,
        ),
        MetricPromotionPolicy(
            "ebit",
            ("OperatingIncomeLoss",),
            "USD",
            PromotionStrategy.TTM_DURATION,
        ),
        MetricPromotionPolicy(
            "depreciation_amortization",
            (),
            "USD",
            PromotionStrategy.ALTERNATIVE,
            alternatives=(
                MetricPromotionPolicy(
                    "depreciation_amortization",
                    ("DepreciationDepletionAndAmortization",),
                    "USD",
                    PromotionStrategy.TTM_DURATION,
                ),
                MetricPromotionPolicy(
                    "depreciation_amortization",
                    ("Depreciation", "AmortizationOfIntangibleAssets"),
                    "USD",
                    PromotionStrategy.COMPOSITE_DURATION,
                    component_coverages=(
                        "depreciation",
                        "intangible_amortization",
                    ),
                ),
            ),
        ),
        MetricPromotionPolicy(
            "capex",
            ("PaymentsToAcquirePropertyPlantAndEquipment",),
            "USD",
            PromotionStrategy.TTM_DURATION,
        ),
        MetricPromotionPolicy(
            "income_tax_expense",
            ("IncomeTaxExpenseBenefit",),
            "USD",
            PromotionStrategy.TTM_DURATION,
        ),
        MetricPromotionPolicy(
            "pretax_income",
            (
                "IncomeLossFromContinuingOperationsBeforeIncomeTaxes"
                "ExtraordinaryItemsNoncontrollingInterest",
            ),
            "USD",
            PromotionStrategy.TTM_DURATION,
        ),
        # Authorized component concepts.
        accounts_receivable,
        inventory,
        accounts_payable,
        net_ppe,
        net_intangibles,
        current_debt,
        noncurrent_debt,
        commercial_paper,
        marketable_securities_current,
        marketable_securities_noncurrent,
        common_equity,
        current_assets,
        # Opening balance-sheet context.
        MetricPromotionPolicy(
            "operating_current_assets_opening",
            ("AccountsReceivableNetCurrent", "InventoryNet"),
            "USD",
            PromotionStrategy.COMPOSITE_INSTANT,
            component_coverages=("trade-receivables", "inventory"),
            target_end=opening_end,
        ),
        MetricPromotionPolicy(
            "operating_current_liabilities_opening",
            ("AccountsPayableCurrent",),
            "USD",
            PromotionStrategy.DIRECT_INSTANT,
            target_end=opening_end,
        ),
        MetricPromotionPolicy(
            "net_operating_assets_opening",
            (
                "PropertyPlantAndEquipmentNet",
                "IntangibleAssetsNetExcludingGoodwill",
            ),
            "USD",
            PromotionStrategy.COMPOSITE_INSTANT,
            component_coverages=("net-ppe", "net-intangibles"),
            target_end=opening_end,
        ),
        MetricPromotionPolicy(
            "common_equity_opening",
            ("StockholdersEquity",),
            "USD",
            PromotionStrategy.DIRECT_INSTANT,
            target_end=opening_end,
        ),
        MetricPromotionPolicy(
            "current_assets_opening",
            ("AssetsCurrent",),
            "USD",
            PromotionStrategy.DIRECT_INSTANT,
            target_end=opening_end,
        ),
        MetricPromotionPolicy(
            "cash_opening",
            ("CashAndCashEquivalentsAtCarryingValue",),
            "USD",
            PromotionStrategy.DIRECT_INSTANT,
            target_end=opening_end,
        ),
        MetricPromotionPolicy(
            "marketable_securities_current_opening",
            ("MarketableSecuritiesCurrent",),
            "USD",
            PromotionStrategy.DIRECT_INSTANT,
            target_end=opening_end,
        ),
        MetricPromotionPolicy(
            "marketable_securities_opening",
            ("MarketableSecuritiesCurrent", "MarketableSecuritiesNoncurrent"),
            "USD",
            PromotionStrategy.COMPOSITE_INSTANT,
            component_coverages=(
                "current-marketable-securities",
                "noncurrent-marketable-securities",
            ),
            target_end=opening_end,
        ),
        MetricPromotionPolicy(
            "total_debt_opening",
            (),
            "USD",
            PromotionStrategy.ALTERNATIVE,
            alternatives=(
                MetricPromotionPolicy(
                    "total_debt_opening",
                    ("LongTermDebtCurrent", "LongTermDebtNoncurrent", "CommercialPaper"),
                    "USD",
                    PromotionStrategy.COMPOSITE_INSTANT,
                    component_coverages=(
                        "long-term-current",
                        "long-term-noncurrent",
                        "commercial-paper",
                    ),
                    target_end=opening_end,
                ),
                MetricPromotionPolicy(
                    "total_debt_opening",
                    ("LongTermDebtCurrent", "LongTermDebtNoncurrent"),
                    "USD",
                    PromotionStrategy.COMPOSITE_INSTANT,
                    component_coverages=("long-term-current", "long-term-noncurrent"),
                    target_end=opening_end,
                ),
            ),
            target_end=opening_end,
        ),
        MetricPromotionPolicy(
            "net_ppe_opening",
            ("PropertyPlantAndEquipmentNet",),
            "USD",
            PromotionStrategy.DIRECT_INSTANT,
            target_end=opening_end,
        ),
        MetricPromotionPolicy(
            "net_intangibles_opening",
            ("IntangibleAssetsNetExcludingGoodwill",),
            "USD",
            PromotionStrategy.DIRECT_INSTANT,
            target_end=opening_end,
        ),
        # Closing balance-sheet context.
        MetricPromotionPolicy(
            "operating_current_assets_closing",
            ("AccountsReceivableNetCurrent", "InventoryNet"),
            "USD",
            PromotionStrategy.COMPOSITE_INSTANT,
            component_coverages=("trade-receivables", "inventory"),
            target_end=closing_end,
        ),
        MetricPromotionPolicy(
            "operating_current_liabilities_closing",
            ("AccountsPayableCurrent",),
            "USD",
            PromotionStrategy.DIRECT_INSTANT,
            target_end=closing_end,
        ),
        MetricPromotionPolicy(
            "net_operating_assets_closing",
            (
                "PropertyPlantAndEquipmentNet",
                "IntangibleAssetsNetExcludingGoodwill",
            ),
            "USD",
            PromotionStrategy.COMPOSITE_INSTANT,
            component_coverages=("net-ppe", "net-intangibles"),
            target_end=closing_end,
        ),
        MetricPromotionPolicy(
            "cash",
            ("CashAndCashEquivalentsAtCarryingValue",),
            "USD",
            PromotionStrategy.DIRECT_INSTANT,
            target_end=closing_end,
        ),
        MetricPromotionPolicy(
            "marketable_securities",
            ("MarketableSecuritiesCurrent", "MarketableSecuritiesNoncurrent"),
            "USD",
            PromotionStrategy.COMPOSITE_INSTANT,
            component_coverages=(
                "current-marketable-securities",
                "noncurrent-marketable-securities",
            ),
            target_end=closing_end,
        ),
        MetricPromotionPolicy(
            "total_debt",
            (),
            "USD",
            PromotionStrategy.ALTERNATIVE,
            alternatives=(
                MetricPromotionPolicy(
                    "total_debt",
                    ("LongTermDebtCurrent", "LongTermDebtNoncurrent", "CommercialPaper"),
                    "USD",
                    PromotionStrategy.COMPOSITE_INSTANT,
                    component_coverages=(
                        "long-term-current",
                        "long-term-noncurrent",
                        "commercial-paper",
                    ),
                    target_end=closing_end,
                ),
                MetricPromotionPolicy(
                    "total_debt",
                    ("LongTermDebtCurrent", "LongTermDebtNoncurrent"),
                    "USD",
                    PromotionStrategy.COMPOSITE_INSTANT,
                    component_coverages=("long-term-current", "long-term-noncurrent"),
                    target_end=closing_end,
                ),
            ),
            target_end=closing_end,
        ),
        # Current common shares have their own temporal semantics.
        MetricPromotionPolicy(
            "valuation_shares",
            ("EntityCommonStockSharesOutstanding",),
            "shares",
            PromotionStrategy.DIRECT_INSTANT,
            taxonomy="dei",
        ),
    )

    return policies


def capital_cost_evidence_policies(
    *, target_end: date | None = None
) -> tuple[MetricPromotionPolicy, ...]:
    """Return SEC promotion policies required only by canonical capital cost."""
    return (
        MetricPromotionPolicy(
            "interest_expense",
            ("InterestExpense",),
            "USD",
            PromotionStrategy.TTM_DURATION,
            target_end=target_end,
        ),
    )


def validate_accounting_evidence_policy_coverage(
    policies: tuple[MetricPromotionPolicy, ...],
) -> dict[str, str]:
    """Fail closed unless every SEC-derived accounting field has one valid policy."""
    from dataclasses import fields

    from .accounting import AccountingEvidenceSpec

    required = {item.name for item in fields(AccountingEvidenceSpec)}
    required -= ACCOUNTING_EVIDENCE_EXTERNAL_FIELDS
    if set(ACCOUNTING_EVIDENCE_POLICY_FIELDS) != required:
        raise FinancialPromotionError("AccountingEvidenceSpec policy coverage is incomplete")
    metric_ids = tuple(item.metric_id for item in policies)
    if len(metric_ids) != len(set(metric_ids)):
        raise FinancialPromotionError("duplicate accounting evidence policy")
    metrics = set(metric_ids)
    if any(metric_id not in metrics for metric_id in ACCOUNTING_EVIDENCE_POLICY_FIELDS.values()):
        raise FinancialPromotionError("accounting evidence field has no declared policy")
    if any(not isinstance(item.strategy, PromotionStrategy) for item in policies):
        raise FinancialPromotionError("accounting evidence policy has unsupported strategy")
    declared_concepts = {
        (item.taxonomy, item.concepts[0])
        for item in policies
        if item.strategy is PromotionStrategy.DIRECT_INSTANT and len(item.concepts) == 1
    }
    for item in policies:
        if item.strategy is PromotionStrategy.COMPOSITE_INSTANT and any(
            (item.taxonomy, concept) not in declared_concepts for concept in item.concepts
        ):
            raise FinancialPromotionError("composite component has no declared canonical metric")
        if any(dependency.metric_id not in metrics for dependency in item.dependencies):
            raise FinancialPromotionError("policy dependency has no declared canonical metric")
    return dict(ACCOUNTING_EVIDENCE_POLICY_FIELDS)


@dataclass(frozen=True)
class InstantContextPair:
    """Explicit compatible endpoints selected from promoted instant evidence."""

    opening: FinancialFact
    closing: FinancialFact


def select_instant_context_pair(
    facts: tuple[FinancialFact, ...],
    *,
    metric_id: str,
    unit: str,
    opening_end: date,
    closing_end: date,
) -> InstantContextPair:
    """Select exactly one canonical opening and closing fact for a period pair."""
    if opening_end >= closing_end:
        raise FinancialPromotionError("opening instant must precede closing instant")
    eligible = tuple(
        item
        for item in facts
        if item.kind is EvidenceKind.FACT
        and item.period_kind is PeriodKind.INSTANT
        and item.concept == metric_id
        and item.unit == unit
    )
    opening = tuple(item for item in eligible if item.period_end == opening_end)
    closing = tuple(item for item in eligible if item.period_end == closing_end)
    if len(opening) != 1 or len(closing) != 1:
        raise FinancialPromotionError("requires one canonical fact for each instant endpoint")
    first, second = opening[0], closing[0]
    if (
        first.fiscal_period != second.fiscal_period
        or first.method != second.method
        or first.filing.filing_type != second.filing.filing_type
    ):
        raise FinancialPromotionError("instant endpoints have incompatible semantic context")
    return InstantContextPair(first, second)


class MultiPeriodFinancialPromoter:
    """Select FY and comparable YTD facts for an already-authorized concept."""

    def promote(self, facts: tuple[RawFact, ...], *, policy: MetricPromotionPolicy):
        if policy.strategy is PromotionStrategy.ALTERNATIVE:
            return self._alternative(facts, policy)
        if policy.strategy is PromotionStrategy.DIRECT_INSTANT:
            if len(policy.concepts) != 1:
                raise FinancialPromotionError("unsupported or ambiguous promotion policy")
            return self._direct_instant(facts, policy)
        if policy.strategy is PromotionStrategy.COMPOSITE_INSTANT:
            return self._composite_instant(facts, policy)
        if policy.strategy is PromotionStrategy.COMPOSITE_DURATION:
            return self._composite_duration(facts, policy)
        if policy.strategy is PromotionStrategy.DERIVED_INSTANT:
            return self._derived_instant(facts, policy)
        if policy.strategy is not PromotionStrategy.TTM_DURATION:
            raise FinancialPromotionError("unsupported promotion policy")
        if len(policy.concepts) != 1:
            raise FinancialPromotionError("unsupported or ambiguous promotion policy")
        result = self.promote_ttm(facts, concept=policy.concepts[0])
        if result.unit != policy.unit:
            raise FinancialPromotionError("policy unit mismatch")
        if policy.target_end is not None and result.period_end != policy.target_end:
            raise FinancialPromotionError("duration target end mismatch")
        return result

    def _alternative(self, facts: tuple[RawFact, ...], policy: MetricPromotionPolicy):
        if not policy.alternatives:
            raise FinancialPromotionError("alternative policy requires authorized representations")

        last_error: FinancialPromotionError | None = None
        for alternative in policy.alternatives:
            try:
                return self.promote(facts, policy=alternative)
            except FinancialPromotionError as exc:
                last_error = exc

        raise FinancialPromotionError(
            "no authorized alternative representation can be promoted"
        ) from last_error

    def _composite_duration(
        self, facts: tuple[RawFact, ...], policy: MetricPromotionPolicy
    ) -> DerivedFact:
        if (
            len(policy.concepts) < 2
            or len(set(policy.concepts)) != len(policy.concepts)
            or len(policy.component_coverages) != len(policy.concepts)
            or len(set(policy.component_coverages)) != len(policy.component_coverages)
        ):
            raise FinancialPromotionError("composite policy requires distinct covered components")

        components = tuple(self.promote_ttm(facts, concept=concept) for concept in policy.concepts)

        if any(item.unit != policy.unit for item in components):
            raise FinancialPromotionError("policy unit mismatch")

        first = components[0]

        if any(
            (item.period_start, item.period_end) != (first.period_start, first.period_end)
            for item in components[1:]
        ):
            raise FinancialPromotionError("incompatible composite duration periods")

        return DerivedFact(
            id=f"composite:{policy.metric_id}",
            concept="+".join(policy.concepts),
            value=sum(item.value for item in components),
            unit=policy.unit,
            inputs=tuple(item.id for item in components),
            formula=" + ".join(policy.concepts),
            period_start=first.period_start,
            period_end=first.period_end,
            kind=EvidenceKind.DERIVED,
        )

    def _direct_instant(
        self, facts: tuple[RawFact, ...], policy: MetricPromotionPolicy
    ) -> FinancialFact:
        candidates = [
            item
            for item in facts
            if item.taxonomy == policy.taxonomy
            and item.concept == policy.concepts[0]
            and item.unit == policy.unit
            and item.period_kind.value == "INSTANT"
            and (policy.target_end is None or item.end == policy.target_end)
            and item.consolidated
            and not item.dimensions
            and item.filing_form in {"10-K", "10-Q"}
        ]
        if not candidates:
            raise FinancialPromotionError("requires one canonical instant fact")
        rank = max((item.end, item.filing_date, item.accession) for item in candidates)
        winners = [
            item for item in candidates if (item.end, item.filing_date, item.accession) == rank
        ]
        if len(winners) != 1:
            raise FinancialPromotionError("ambiguous canonical instant facts")
        raw = winners[0]
        return FinancialFact(
            raw.fact_id,
            raw.concept,
            raw.value,
            raw.unit,
            EvidenceKind.FACT,
            PeriodKind.INSTANT,
            None,
            raw.end,
            raw.fiscal_year,
            raw.fiscal_period,
            FilingRef(
                raw.accession, raw.filing_form, raw.filing_date, Path("."), raw.source_identity
            ),
            raw.fact_id,
            "canonical SEC company facts",
            (raw.fact_id,),
            (raw.accession,),
        )

    def _composite_instant(
        self, facts: tuple[RawFact, ...], policy: MetricPromotionPolicy
    ) -> FinancialFact:
        if (
            len(policy.concepts) < 2
            or len(set(policy.concepts)) != len(policy.concepts)
            or len(policy.component_coverages) != len(policy.concepts)
            or len(set(policy.component_coverages)) != len(policy.component_coverages)
        ):
            raise FinancialPromotionError("composite policy requires distinct covered components")
        eligible = tuple(
            item
            for item in facts
            if item.taxonomy == policy.taxonomy
            and item.concept in policy.concepts
            and item.unit == policy.unit
            and item.period_kind.value == "INSTANT"
            and (policy.target_end is None or item.end == policy.target_end)
            and item.consolidated
            and not item.dimensions
            and item.filing_form in {"10-K", "10-Q"}
        )
        contexts = {
            (
                item.end,
                item.fiscal_year,
                item.fiscal_period,
                item.accession,
                item.filing_form,
                item.filing_date,
            )
            for item in eligible
        }
        complete = []
        for context in contexts:
            selected = tuple(item for item in eligible if self._context(item) == context)
            if all(
                sum(item.concept == concept for item in selected) == 1
                for concept in policy.concepts
            ):
                complete.append(selected)
        if not complete:
            raise FinancialPromotionError(
                "requires every composite component in one instant context"
            )
        latest = max(self._context(items[0]) for items in complete)
        winners = [items for items in complete if self._context(items[0]) == latest]
        if len(winners) != 1:
            raise FinancialPromotionError("ambiguous composite instant facts")
        components_by_concept = {item.concept: item for item in winners[0]}
        components = tuple(components_by_concept[concept] for concept in policy.concepts)
        first = components[0]
        return FinancialFact(
            f"composite:{policy.metric_id}",
            policy.metric_id,
            sum(item.value for item in components),
            policy.unit,
            EvidenceKind.FACT,
            PeriodKind.INSTANT,
            None,
            first.end,
            first.fiscal_year,
            first.fiscal_period,
            FilingRef(
                first.accession,
                first.filing_form,
                first.filing_date,
                Path("."),
                first.source_identity,
            ),
            ",".join(item.fact_id for item in components),
            "sum of canonical SEC company facts",
            tuple(item.fact_id for item in components),
            tuple(item.accession for item in components),
        )

    @staticmethod
    def _context(raw: RawFact) -> tuple:
        return (
            raw.end,
            raw.fiscal_year,
            raw.fiscal_period,
            raw.accession,
            raw.filing_form,
            raw.filing_date,
        )

    def _derived_instant(
        self, facts: tuple[RawFact, ...], policy: MetricPromotionPolicy
    ) -> FinancialFact:
        if (
            policy.metric_id != "net_working_capital"
            or policy.derivation != "net_working_capital"
            or tuple(item.metric_id for item in policy.dependencies)
            != ("operating_current_assets", "operating_current_liabilities")
        ):
            raise FinancialPromotionError("unsupported derived instant policy")
        dependencies = tuple(self.promote(facts, policy=item) for item in policy.dependencies)
        if (
            any(
                item.period_kind is not PeriodKind.INSTANT or item.unit != policy.unit
                for item in dependencies
            )
            or len({self._financial_context(item) for item in dependencies}) != 1
        ):
            raise FinancialPromotionError(
                "derived instant dependencies must share context and unit"
            )
        source_fact_ids = tuple(
            item for dependency in dependencies for item in dependency.source_fact_ids
        )
        source_accessions = tuple(
            item for dependency in dependencies for item in dependency.source_accessions
        )
        if len(source_fact_ids) != len(set(source_fact_ids)):
            raise FinancialPromotionError("derived instant dependencies overlap")
        if policy.target_end is not None and dependencies[0].period_end != policy.target_end:
            raise FinancialPromotionError("derived instant endpoint does not match policy")
        try:
            value = calculate_net_working_capital(
                operating_current_assets=dependencies[0].value,
                operating_current_liabilities=dependencies[1].value,
            )
        except FinancialPrimitiveError as exc:
            raise FinancialPromotionError("invalid derived instant dependencies") from exc
        first = dependencies[0]
        return FinancialFact(
            f"derived:{policy.metric_id}",
            policy.metric_id,
            value,
            policy.unit,
            EvidenceKind.FACT,
            PeriodKind.INSTANT,
            None,
            first.period_end,
            first.fiscal_year,
            first.fiscal_period,
            first.filing,
            ",".join(source_fact_ids),
            "operating current assets - operating current liabilities",
            source_fact_ids,
            source_accessions,
        )

    @staticmethod
    def _financial_context(fact: FinancialFact) -> tuple:
        return (
            fact.period_end,
            fact.fiscal_year,
            fact.fiscal_period,
            fact.filing.accession_number,
            fact.filing.filing_type,
            fact.filing.filing_date,
            fact.filing.sha256,
        )

    def promote_ttm(self, facts: tuple[RawFact, ...], *, concept: str):
        candidates = tuple(
            item
            for item in facts
            if item.taxonomy == "us-gaap"
            and item.concept == concept
            and item.period_kind.value == "DURATION"
            and item.consolidated
            and not item.dimensions
            and item.filing_form in {"10-K", "10-Q"}
        )
        selected: list[RawFact] = []
        for key in {(item.fiscal_period, item.start, item.end) for item in candidates}:
            observations = [
                item for item in candidates if (item.fiscal_period, item.start, item.end) == key
            ]
            rank = max((item.filing_date, item.accession) for item in observations)
            winners = [item for item in observations if (item.filing_date, item.accession) == rank]
            if len({item.value for item in winners}) != 1:
                raise FinancialPromotionError("ambiguous SEC duration observations")
            selected.append(winners[0])
        annuals = [item for item in selected if item.fiscal_period == "FY"]
        ytd = [item for item in selected if item.fiscal_period != "FY"]
        triples = [
            (annual, prior, current)
            for annual in annuals
            for prior in ytd
            for current in ytd
            if prior.fiscal_period == current.fiscal_period
            and prior.unit == current.unit == annual.unit
            and prior.end < annual.end < current.end
            and prior.start is not None
            and current.start is not None
            and (prior.end - prior.start) == (current.end - current.start)
        ]
        if not triples:
            if ytd:
                raise FinancialPromotionError("requires one comparable YTD pair")
            if not annuals:
                raise FinancialPromotionError("requires one canonical annual fact")

            latest_annual_end = max(item.end for item in annuals)
            latest_annual = [item for item in annuals if item.end == latest_annual_end]
            if len(latest_annual) != 1:
                raise FinancialPromotionError("ambiguous canonical annual facts")

            return self._fact(latest_annual[0])
        latest_end = max(current.end for _, _, current in triples)
        ttm_winners: list[tuple[RawFact, RawFact, RawFact]] = [
            item for item in triples if item[2].end == latest_end
        ]
        longest_current = max(
            current.end - cast(date, current.start) for _, _, current in ttm_winners
        )
        ttm_winners = [
            item
            for item in ttm_winners
            if item[2].end - cast(date, item[2].start) == longest_current
        ]
        latest_prior_end = max(prior.end for _, prior, _ in ttm_winners)
        ttm_winners = [item for item in ttm_winners if item[1].end == latest_prior_end]
        latest_annual_end = max(annual.end for annual, _, _ in ttm_winners)
        ttm_winners = [item for item in ttm_winners if item[0].end == latest_annual_end]
        if len(ttm_winners) != 1:
            raise FinancialPromotionError("ambiguous annual and comparable YTD facts")
        annual, prior, current = ttm_winners[0]

        latest_direct_end = max(item.end for item in annuals)
        latest_direct = [item for item in annuals if item.end == latest_direct_end]
        if len(latest_direct) != 1:
            raise FinancialPromotionError("ambiguous canonical annual facts")

        if latest_direct[0].end >= current.end:
            return self._fact(latest_direct[0])
        return reconstruct_ttm(
            annual=self._fact(annual),
            prior_ytd=self._fact(prior),
            current_ytd=self._fact(current),
            identifier=f"ttm:{concept}",
        )

    @staticmethod
    def _fact(raw: RawFact) -> FinancialFact:
        return FinancialFact(
            raw.fact_id,
            raw.concept,
            raw.value,
            raw.unit,
            EvidenceKind.FACT,
            PeriodKind.DURATION,
            raw.start,
            raw.end,
            raw.fiscal_year,
            raw.fiscal_period,
            FilingRef(
                raw.accession, raw.filing_form, raw.filing_date, Path("."), raw.source_identity
            ),
            raw.fact_id,
            "canonical SEC company facts",
            (raw.fact_id,),
            (raw.accession,),
        )
