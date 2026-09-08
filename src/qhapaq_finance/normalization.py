"""Evidence-backed analytical cash bases for Qhapaq underwriting.

The current implementation is deliberately limited to a *run-rate* cash basis. It
normalizes selected timing effects in a reported period, but it does not normalize an
industry or business cycle. The distinction is part of the product contract.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .data import file_sha256
from .research import ResearchRecord


class NormalizationError(ValueError):
    """Raised when an analytical cash-basis record is incomplete or inconsistent."""


class CashBasisKind(str, Enum):
    """Supported analytical cash-basis methods.

    Only RUN_RATE is implemented. A future through-cycle basis must have a distinct
    calculation contract rather than re-labeling the current formula.
    """

    RUN_RATE = "run_rate"


@dataclass(frozen=True)
class CashInput:
    id: str
    label: str
    value: float
    unit: str
    source_id: str
    locator: str


@dataclass(frozen=True)
class CashBridgeItem:
    id: str
    label: str
    amount: float
    rationale: str


@dataclass(frozen=True)
class RunRateCashComputation:
    """Pure result of the current-period run-rate bridge, in source units."""

    reported_period_fcf: float
    working_capital_adjustment: float
    timing_adjustment: float
    sbc_adjustment: float
    run_rate_period_cash: float
    run_rate_annualized_cash: float


@dataclass(frozen=True)
class CashBasisResult:
    ticker: str
    as_of: str
    period: str
    basis_kind: CashBasisKind
    reported_period_fcf: float
    annualization_factor: float
    working_capital_current: float
    working_capital_prior: float
    working_capital_adjustment: float
    timing_adjustment: float
    sbc_adjustment: float
    run_rate_period_cash: float
    run_rate_annualized_cash: float
    shares_outstanding: float | None
    bridge: tuple[CashBridgeItem, ...]
    policy_notes: tuple[str, ...]
    record_sha256: str


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NormalizationError(f"{field} must be numeric")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise NormalizationError(f"{field} must be finite")
    return numeric


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NormalizationError(f"{field} must be a non-empty string")
    return value.strip()


def calculate_run_rate_cash_basis(
    *,
    operating_cash_flow: float,
    capex: float,
    working_capital_current: float,
    working_capital_prior: float,
    timing_adjustment: float,
    sbc_expense: float,
    annualization_factor: float,
) -> RunRateCashComputation:
    """Calculate the explicit timing-normalized run-rate cash bridge.

    This function intentionally allows a negative result so historical stress tests can
    expose cycle failure. Product loading may reject a non-positive cash base for reverse
    DCF because the current solver requires positive starting equity cash flow.
    """
    ocf = _finite(operating_cash_flow, "operating_cash_flow")
    capex_value = _finite(capex, "capex")
    wc_current = _finite(working_capital_current, "working_capital_current")
    wc_prior = _finite(working_capital_prior, "working_capital_prior")
    timing = _finite(timing_adjustment, "timing_adjustment")
    sbc = _finite(sbc_expense, "sbc_expense")
    annualization = _finite(annualization_factor, "annualization_factor")
    if ocf <= 0:
        raise NormalizationError("operating_cash_flow must be positive")
    if capex_value < 0:
        raise NormalizationError("capex must be non-negative")
    if sbc < 0:
        raise NormalizationError("sbc_expense must be non-negative")
    if annualization <= 0:
        raise NormalizationError("annualization_factor must be positive")

    reported_fcf = ocf - capex_value
    working_capital_adjustment = wc_prior - wc_current
    sbc_adjustment = -sbc
    run_rate_period_cash = reported_fcf + working_capital_adjustment + timing + sbc_adjustment
    return RunRateCashComputation(
        reported_period_fcf=reported_fcf,
        working_capital_adjustment=working_capital_adjustment,
        timing_adjustment=timing,
        sbc_adjustment=sbc_adjustment,
        run_rate_period_cash=run_rate_period_cash,
        run_rate_annualized_cash=run_rate_period_cash * annualization,
    )


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"cash-basis record not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NormalizationError(f"invalid cash-basis record: {path}") from exc
    if not isinstance(payload, dict):
        raise NormalizationError("cash-basis record root must be an object")
    return payload


def _cash_input(
    raw: Any,
    *,
    field: str,
    source_ids: set[str],
    expected_unit: str | None = "USD million",
) -> CashInput:
    if not isinstance(raw, dict):
        raise NormalizationError(f"{field} must be an object")
    identifier = _text(raw.get("id"), f"{field}.id")
    label = _text(raw.get("label"), f"{field}.label")
    value = _finite(raw.get("value"), f"{field}.value")
    unit = _text(raw.get("unit"), f"{field}.unit")
    if expected_unit is not None and unit != expected_unit:
        raise NormalizationError(f"{field}.unit must be {expected_unit}")
    source_id = _text(raw.get("source_id"), f"{field}.source_id")
    if source_id not in source_ids:
        raise NormalizationError(f"{field} references unknown source_id: {source_id}")
    locator = _text(raw.get("locator"), f"{field}.locator")
    return CashInput(identifier, label, value, unit, source_id, locator)


def _component_map(raw: Any, *, field: str, source_ids: set[str]) -> dict[str, CashInput]:
    if not isinstance(raw, list) or not raw:
        raise NormalizationError(f"{field} must be a non-empty array")
    result: dict[str, CashInput] = {}
    for index, item in enumerate(raw):
        parsed = _cash_input(item, field=f"{field}[{index}]", source_ids=source_ids)
        if parsed.id in result:
            raise NormalizationError(f"duplicate cash-basis component id: {parsed.id}")
        result[parsed.id] = parsed
    return result


def load_cash_basis(*, record: ResearchRecord, path: str | Path) -> CashBasisResult:
    """Load an evidence-linked run-rate cash-basis record.

    Schema 0.2 requires the basis kind to be explicit. `through_cycle` is intentionally
    unsupported until a separate cycle-aware methodology passes historical stress tests.
    """
    source_path = Path(path).resolve()
    payload = _read(source_path)
    if payload.get("schema_version") != "0.2":
        raise NormalizationError("unsupported cash-basis schema_version")
    try:
        basis_kind = CashBasisKind(payload.get("basis_kind"))
    except (TypeError, ValueError) as exc:
        raise NormalizationError("unsupported basis_kind") from exc

    ticker = _text(payload.get("ticker"), "ticker").upper()
    if ticker != record.issuer.get("ticker"):
        raise NormalizationError("cash-basis ticker does not match research record")
    as_of = _text(payload.get("as_of"), "as_of")
    if as_of != record.as_of.isoformat():
        raise NormalizationError("cash-basis as_of does not match research record")
    period = _text(payload.get("period"), "period")
    annualization_factor = _finite(payload.get("annualization_factor"), "annualization_factor")
    if annualization_factor <= 0:
        raise NormalizationError("annualization_factor must be positive")

    source_ids = {source.id for source in record.sources}
    reported = payload.get("reported_fcf")
    if not isinstance(reported, dict):
        raise NormalizationError("reported_fcf must be an object")
    ocf = _cash_input(
        reported.get("operating_cash_flow"),
        field="reported_fcf.operating_cash_flow",
        source_ids=source_ids,
    )
    capex = _cash_input(
        reported.get("capex"),
        field="reported_fcf.capex",
        source_ids=source_ids,
    )

    working_capital = payload.get("working_capital")
    if not isinstance(working_capital, dict):
        raise NormalizationError("working_capital must be an object")
    if working_capital.get("policy") != "comparative_delta":
        raise NormalizationError("working_capital policy must be comparative_delta")
    wc_current = _component_map(
        working_capital.get("current"), field="working_capital.current", source_ids=source_ids
    )
    wc_prior = _component_map(
        working_capital.get("prior"), field="working_capital.prior", source_ids=source_ids
    )
    if set(wc_current) != set(wc_prior):
        raise NormalizationError("working-capital current/prior component ids must match")
    current_wc = sum(item.value for item in wc_current.values())
    prior_wc = sum(item.value for item in wc_prior.values())

    timing_adjustment = 0.0
    timing_raw = payload.get("timing_adjustments", [])
    if not isinstance(timing_raw, list):
        raise NormalizationError("timing_adjustments must be an array")
    timing_bridge: list[CashBridgeItem] = []
    for index, item in enumerate(timing_raw):
        if not isinstance(item, dict) or item.get("policy") != "comparative_delta":
            raise NormalizationError(
                f"timing_adjustments[{index}] must use comparative_delta policy"
            )
        current = _cash_input(
            item.get("current"),
            field=f"timing_adjustments[{index}].current",
            source_ids=source_ids,
        )
        prior = _cash_input(
            item.get("prior"),
            field=f"timing_adjustments[{index}].prior",
            source_ids=source_ids,
        )
        if current.id != prior.id:
            raise NormalizationError("timing current/prior ids must match")
        amount = prior.value - current.value
        timing_adjustment += amount
        timing_bridge.append(
            CashBridgeItem(
                id=f"timing:{current.id}",
                label=current.label,
                amount=amount,
                rationale="Normalize only the current-vs-prior comparable timing delta.",
            )
        )

    sbc = payload.get("sbc")
    if not isinstance(sbc, dict):
        raise NormalizationError("sbc must be an object")
    if sbc.get("policy") != "deduct_economic_cost":
        raise NormalizationError("sbc policy must be deduct_economic_cost")
    sbc_current = _cash_input(sbc.get("current"), field="sbc.current", source_ids=source_ids)

    computation = calculate_run_rate_cash_basis(
        operating_cash_flow=ocf.value,
        capex=capex.value,
        working_capital_current=current_wc,
        working_capital_prior=prior_wc,
        timing_adjustment=timing_adjustment,
        sbc_expense=sbc_current.value,
        annualization_factor=annualization_factor,
    )
    if computation.reported_period_fcf <= 0:
        raise NormalizationError("reported-period FCF proxy must be positive")
    if computation.run_rate_period_cash <= 0 or computation.run_rate_annualized_cash <= 0:
        raise NormalizationError("run-rate cash basis must remain positive for reverse DCF")

    shares_outstanding: float | None = None
    raw_shares = payload.get("shares_outstanding")
    if raw_shares is not None:
        shares = _cash_input(
            raw_shares,
            field="shares_outstanding",
            source_ids=source_ids,
            expected_unit="count",
        )
        if shares.value <= 0:
            raise NormalizationError("shares_outstanding must be positive")
        shares_outstanding = shares.value

    notes = payload.get("policy_notes")
    if (
        not isinstance(notes, list)
        or not notes
        or any(not isinstance(note, str) or not note.strip() for note in notes)
    ):
        raise NormalizationError("policy_notes must be a non-empty array of strings")

    bridge = [
        CashBridgeItem(
            id="reported-fcf",
            label="Reported FCF proxy",
            amount=computation.reported_period_fcf,
            rationale="Operating cash flow less reported capital expenditure for the period.",
        ),
        CashBridgeItem(
            id="working-capital-delta",
            label="Working-capital timing adjustment",
            amount=computation.working_capital_adjustment,
            rationale=(
                "Retain the prior comparable working-capital cash pattern and adjust only "
                "the incremental current-period deviation. This is not cycle normalization."
            ),
        ),
        *timing_bridge,
        CashBridgeItem(
            id="sbc-economic-cost",
            label="SBC economic-cost policy",
            amount=computation.sbc_adjustment,
            rationale=(
                "Deduct reported stock-based compensation as an explicit economic-cost policy; "
                "do not apply an equivalent dilution charge again."
            ),
        ),
    ]

    return CashBasisResult(
        ticker=ticker,
        as_of=as_of,
        period=period,
        basis_kind=basis_kind,
        reported_period_fcf=computation.reported_period_fcf,
        annualization_factor=annualization_factor,
        working_capital_current=current_wc,
        working_capital_prior=prior_wc,
        working_capital_adjustment=computation.working_capital_adjustment,
        timing_adjustment=computation.timing_adjustment,
        sbc_adjustment=computation.sbc_adjustment,
        run_rate_period_cash=computation.run_rate_period_cash,
        run_rate_annualized_cash=computation.run_rate_annualized_cash,
        shares_outstanding=shares_outstanding,
        bridge=tuple(bridge),
        policy_notes=tuple(note.strip() for note in notes),
        record_sha256=file_sha256(source_path),
    )
