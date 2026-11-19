"""Offline provider-feasibility benchmark over canonical samples."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ..contracts import FiscalSlot
from .local import LocalJsonProvider

REQUIRED_FAMILIES = (
    "revenue",
    "operating_income",
    "net_income",
    "operating_cash_flow",
    "capital_expenditures",
    "cash_and_equivalents",
    "marketable_securities",
    "total_debt",
    "total_equity",
    "diluted_shares",
    "shares_outstanding_latest",
    "shares_outstanding_fy1_end",
    "pretax_income",
    "income_tax_expense",
    "market_cap",
    "enterprise_value_provider",
    "price",
)


@dataclass(frozen=True, slots=True)
class ProviderBenchmarkResult:
    provider: str
    record_count: int
    identity_pass_rate: float
    required_family_coverage: float
    period_identity_pass_rate: float
    sign_semantics_pass_rate: float
    share_basis_pass_rate: float
    canonical_parse_pass_rate: float
    calls_per_ticker: float | None
    batch_size: int | None
    latency_ms: float | None
    estimated_cost_usd: float | None
    diagnostics: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "record_count": self.record_count,
            "identity_pass_rate": self.identity_pass_rate,
            "required_family_coverage": self.required_family_coverage,
            "period_identity_pass_rate": self.period_identity_pass_rate,
            "sign_semantics_pass_rate": self.sign_semantics_pass_rate,
            "share_basis_pass_rate": self.share_basis_pass_rate,
            "canonical_parse_pass_rate": self.canonical_parse_pass_rate,
            "calls_per_ticker": self.calls_per_ticker,
            "batch_size": self.batch_size,
            "latency_ms": self.latency_ms,
            "estimated_cost_usd": self.estimated_cost_usd,
            "diagnostics": list(self.diagnostics),
        }


def _rate(passed: int, total: int) -> float:
    return 1.0 if total == 0 else passed / total


def _optional_number(mapping: Mapping[str, object], name: str) -> float | None:
    value = mapping.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"OPERATIONAL_METADATA_{name.upper()}_INVALID")
    return float(value)


def _optional_int(mapping: Mapping[str, object], name: str) -> int | None:
    value = mapping.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"OPERATIONAL_METADATA_{name.upper()}_INVALID")
    return value


def benchmark_provider_sample(
    *,
    reference: LocalJsonProvider,
    candidate: LocalJsonProvider,
    operational_metadata: Mapping[str, object] | None = None,
) -> ProviderBenchmarkResult:
    reference_records = {record.ticker: record for record in reference.records()}
    candidate_records = {record.ticker: record for record in candidate.records()}
    provider = next((record.provider for record in candidate_records.values()), "unknown")
    diagnostics: set[str] = set()

    identity_total = len(reference_records)
    identity_passed = 0
    for ticker, ref in reference_records.items():
        cand = candidate_records.get(ticker)
        if (
            cand is not None
            and cand.security_id == ref.security_id
            and cand.issuer_id == ref.issuer_id
        ):
            identity_passed += 1
    identity_rate = _rate(identity_passed, identity_total)
    if identity_rate < 1.0:
        diagnostics.add("IDENTITY_GAP")

    coverage_values: list[float] = []
    period_passed = 0
    period_total = 0
    sign_passed = 0
    sign_total = 0
    share_passed = 0
    share_total = 0

    for ticker, ref in reference_records.items():
        cand = candidate_records.get(ticker)
        if cand is None:
            coverage_values.append(0.0)
            continue
        present = {item.metric_id for item in cand.observations}
        coverage_values.append(
            sum(name in present for name in REQUIRED_FAMILIES) / len(REQUIRED_FAMILIES)
        )

        ref_map = {(item.metric_id, item.fiscal_slot): item for item in ref.observations}
        cand_map = {(item.metric_id, item.fiscal_slot): item for item in cand.observations}
        for key, ref_obs in ref_map.items():
            cand_obs = cand_map.get(key)
            if cand_obs is None:
                continue
            period_total += 1
            if (
                cand_obs.period_kind is ref_obs.period_kind
                and cand_obs.period_start == ref_obs.period_start
                and cand_obs.period_end == ref_obs.period_end
            ):
                period_passed += 1
            if key[0] == "capital_expenditures":
                sign_total += 1
                if cand_obs.value >= 0:
                    sign_passed += 1

        latest = cand_map.get(("shares_outstanding_latest", FiscalSlot.LATEST))
        fy1 = cand_map.get(("shares_outstanding_fy1_end", FiscalSlot.FY1))
        if latest is not None and fy1 is not None:
            share_total += 1
            if (
                latest.share_class_id
                and latest.share_class_id == fy1.share_class_id
                and latest.adjustment_basis_id
                and latest.adjustment_basis_id == fy1.adjustment_basis_id
            ):
                share_passed += 1

    coverage = sum(coverage_values) / len(coverage_values) if coverage_values else 0.0
    period_rate = _rate(period_passed, period_total)
    sign_rate = _rate(sign_passed, sign_total)
    share_rate = _rate(share_passed, share_total)
    if coverage < 1.0:
        diagnostics.add("REQUIRED_FAMILY_COVERAGE_GAP")
    if period_rate < 1.0:
        diagnostics.add("PERIOD_IDENTITY_GAP")
    if sign_rate < 1.0:
        diagnostics.add("SIGN_SEMANTICS_GAP")
    if share_rate < 1.0:
        diagnostics.add("SHARE_BASIS_GAP")

    metadata = operational_metadata or {}
    return ProviderBenchmarkResult(
        provider=provider,
        record_count=len(candidate_records),
        identity_pass_rate=identity_rate,
        required_family_coverage=coverage,
        period_identity_pass_rate=period_rate,
        sign_semantics_pass_rate=sign_rate,
        share_basis_pass_rate=share_rate,
        canonical_parse_pass_rate=1.0,
        calls_per_ticker=_optional_number(metadata, "calls_per_ticker"),
        batch_size=_optional_int(metadata, "batch_size"),
        latency_ms=_optional_number(metadata, "latency_ms"),
        estimated_cost_usd=_optional_number(metadata, "estimated_cost_usd"),
        diagnostics=tuple(sorted(diagnostics)),
    )
