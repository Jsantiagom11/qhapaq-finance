"""Evidence-backed cash normalization for Qhapaq underwriting.

The module deliberately does not forecast. It transforms a reported-period FCF proxy
into an analytical cash-power run rate using explicit, source-linked adjustments.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .data import file_sha256
from .research import ResearchRecord


class NormalizationError(ValueError):
    """Raised when a normalization record is incomplete or internally inconsistent."""


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
class NormalizedCashResult:
    ticker: str
    as_of: str
    period: str
    reported_period_fcf: float
    annualization_factor: float
    working_capital_current: float
    working_capital_prior: float
    working_capital_adjustment: float
    timing_adjustment: float
    sbc_adjustment: float
    normalized_period_fcf: float
    normalized_annualized_fcf: float
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


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"normalization record not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NormalizationError(f"invalid normalization record: {path}") from exc
    if not isinstance(payload, dict):
        raise NormalizationError("normalization record root must be an object")
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


def _component_map(
    raw: Any, *, field: str, source_ids: set[str]
) -> dict[str, CashInput]:
    if not isinstance(raw, list) or not raw:
        raise NormalizationError(f"{field} must be a non-empty array")
    result: dict[str, CashInput] = {}
    for index, item in enumerate(raw):
        parsed = _cash_input(item, field=f"{field}[{index}]", source_ids=source_ids)
        if parsed.id in result:
            raise NormalizationError(f"duplicate normalization component id: {parsed.id}")
        result[parsed.id] = parsed
    return result


def load_normalized_cash(
    *,
    record: ResearchRecord,
    path: str | Path,
) -> NormalizedCashResult:
    """Load and calculate a deterministic comparative-delta cash normalization."""
    source_path = Path(path).resolve()
    payload = _read(source_path)
    if payload.get("schema_version") != "0.1":
        raise NormalizationError("unsupported normalization schema_version")
    ticker = _text(payload.get("ticker"), "ticker").upper()
    if ticker != record.issuer.get("ticker"):
        raise NormalizationError("normalization ticker does not match research record")
    as_of = _text(payload.get("as_of"), "as_of")
    if as_of != record.as_of.isoformat():
        raise NormalizationError("normalization as_of does not match research record")
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
    if ocf.value <= 0 or capex.value < 0:
        raise NormalizationError("reported OCF must be positive and capex must be non-negative")
    reported_period_fcf = ocf.value - capex.value
    if reported_period_fcf <= 0:
        raise NormalizationError("reported-period FCF proxy must be positive")

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
    wc_adjustment = prior_wc - current_wc

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
    sbc_current = _cash_input(
        sbc.get("current"), field="sbc.current", source_ids=source_ids
    )
    if sbc_current.value < 0:
        raise NormalizationError("SBC expense must be non-negative")
    sbc_adjustment = -sbc_current.value

    normalized_period_fcf = (
        reported_period_fcf + wc_adjustment + timing_adjustment + sbc_adjustment
    )
    normalized_annualized_fcf = normalized_period_fcf * annualization_factor
    if normalized_period_fcf <= 0 or normalized_annualized_fcf <= 0:
        raise NormalizationError("normalized cash power must remain positive")

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
    if not isinstance(notes, list) or not notes or any(
        not isinstance(note, str) or not note.strip() for note in notes
    ):
        raise NormalizationError("policy_notes must be a non-empty array of strings")

    bridge = [
        CashBridgeItem(
            id="reported-fcf",
            label="Reported FCF proxy",
            amount=reported_period_fcf,
            rationale="Operating cash flow less reported capital expenditure for the period.",
        ),
        CashBridgeItem(
            id="working-capital-delta",
            label="Working-capital normalization",
            amount=wc_adjustment,
            rationale=(
                "Retain the prior comparable working-capital cash pattern and normalize only "
                "the incremental current-period deviation."
            ),
        ),
        *timing_bridge,
        CashBridgeItem(
            id="sbc-economic-cost",
            label="SBC economic-cost policy",
            amount=sbc_adjustment,
            rationale=(
                "Deduct reported stock-based compensation as an explicit economic-cost policy; "
                "do not apply an equivalent dilution charge again."
            ),
        ),
    ]

    return NormalizedCashResult(
        ticker=ticker,
        as_of=as_of,
        period=period,
        reported_period_fcf=reported_period_fcf,
        annualization_factor=annualization_factor,
        working_capital_current=current_wc,
        working_capital_prior=prior_wc,
        working_capital_adjustment=wc_adjustment,
        timing_adjustment=timing_adjustment,
        sbc_adjustment=sbc_adjustment,
        normalized_period_fcf=normalized_period_fcf,
        normalized_annualized_fcf=normalized_annualized_fcf,
        shares_outstanding=shares_outstanding,
        bridge=tuple(bridge),
        policy_notes=tuple(note.strip() for note in notes),
        record_sha256=file_sha256(source_path),
    )
