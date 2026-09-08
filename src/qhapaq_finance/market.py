"""Time-aware market observations kept separate from frozen research evidence."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class MarketDataError(ValueError):
    """Raised when a market observation violates the snapshot contract."""


class MarketState(str, Enum):
    PRE = "pre"
    REGULAR = "regular"
    POST = "post"
    CLOSED = "closed"
    UNKNOWN = "unknown"


class Freshness(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    FUTURE = "future"


@dataclass(frozen=True)
class MarketSnapshot:
    """One provider observation with explicit event and retrieval timestamps."""

    ticker: str
    price: float
    currency: str
    observed_at: datetime
    retrieved_at: datetime
    source: str
    market_state: MarketState = MarketState.UNKNOWN
    previous_close: float | None = None
    market_cap: float | None = None

    @property
    def change_from_previous_close(self) -> float | None:
        if self.previous_close is None:
            return None
        return self.price / self.previous_close - 1.0


@dataclass(frozen=True)
class FreshnessPolicy:
    """Caller-owned policy; market data itself does not decide how fresh it must be."""

    max_age: timedelta
    future_tolerance: timedelta = timedelta(minutes=2)

    def __post_init__(self) -> None:
        if self.max_age <= timedelta(0):
            raise MarketDataError("max_age must be positive")
        if self.future_tolerance < timedelta(0):
            raise MarketDataError("future_tolerance cannot be negative")


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise MarketDataError(f"{field} must be timezone-aware")
    return value


def _ticker(value: str) -> str:
    normalized = value.strip().upper()
    if (
        not normalized
        or len(normalized) > 32
        or any(character.isspace() for character in normalized)
    ):
        raise MarketDataError("ticker must be a non-empty symbol without whitespace")
    return normalized


def _positive_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MarketDataError(f"{field} must be numeric")
    numeric = float(value)
    if not math.isfinite(numeric) or numeric <= 0:
        raise MarketDataError(f"{field} must be finite and positive")
    return numeric


def _metadata_get(metadata: Any, key: str) -> Any:
    try:
        return metadata.get(key)
    except (AttributeError, KeyError, TypeError):
        return None


def _market_cap_from_provider_metadata(
    *, price: float, fast_info: Any = None, info: Any = None
) -> float | None:
    """Resolve equity value from provider metadata without making it research evidence."""
    for metadata, key in ((fast_info, "market_cap"), (info, "marketCap")):
        raw = _metadata_get(metadata, key)
        if raw is None:
            continue
        try:
            return _positive_number(raw, "market_cap")
        except MarketDataError:
            continue

    raw_shares = _metadata_get(info, "sharesOutstanding")
    if raw_shares is None:
        return None
    try:
        shares = _positive_number(raw_shares, "shares_outstanding")
        return shares * _positive_number(price, "price")
    except MarketDataError:
        return None


def _validate_snapshot(snapshot: MarketSnapshot) -> MarketSnapshot:
    _ticker(snapshot.ticker)
    _positive_number(snapshot.price, "price")
    if snapshot.previous_close is not None:
        _positive_number(snapshot.previous_close, "previous_close")
    if snapshot.market_cap is not None:
        _positive_number(snapshot.market_cap, "market_cap")
    if not snapshot.currency.strip():
        raise MarketDataError("currency must be non-empty")
    if not snapshot.source.strip():
        raise MarketDataError("source must be non-empty")
    observed = _aware(snapshot.observed_at, "observed_at")
    retrieved = _aware(snapshot.retrieved_at, "retrieved_at")
    if retrieved < observed - timedelta(days=7):
        raise MarketDataError("retrieved_at is implausibly earlier than observed_at")
    return snapshot


def classify_freshness(
    snapshot: MarketSnapshot, *, policy: FreshnessPolicy, now: datetime | None = None
) -> Freshness:
    """Classify age relative to a caller-defined use case."""
    _validate_snapshot(snapshot)
    reference = _aware(now or datetime.now(timezone.utc), "now")
    age = reference.astimezone(timezone.utc) - snapshot.observed_at.astimezone(timezone.utc)
    if age < -policy.future_tolerance:
        return Freshness.FUTURE
    if age <= policy.max_age:
        return Freshness.FRESH
    return Freshness.STALE


def snapshot_age(snapshot: MarketSnapshot, *, now: datetime | None = None) -> timedelta:
    _validate_snapshot(snapshot)
    reference = _aware(now or datetime.now(timezone.utc), "now")
    return reference.astimezone(timezone.utc) - snapshot.observed_at.astimezone(timezone.utc)


def _market_state(value: Any) -> MarketState:
    if not isinstance(value, str):
        return MarketState.UNKNOWN
    normalized = value.strip().upper()
    return {
        "PRE": MarketState.PRE,
        "PREPRE": MarketState.PRE,
        "REGULAR": MarketState.REGULAR,
        "POST": MarketState.POST,
        "POSTPOST": MarketState.POST,
        "CLOSED": MarketState.CLOSED,
    }.get(normalized, MarketState.UNKNOWN)


def fetch_yfinance_snapshot(ticker: str, *, now: datetime | None = None) -> MarketSnapshot:
    """Fetch the latest observable quote through the optional yfinance provider.

    Network access is isolated here. The returned object is an observation, not frozen evidence.
    """
    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("Install Qhapaq Finance with the 'data' extra") from exc

    symbol = _ticker(ticker)
    retrieved_at = _aware(now or datetime.now(timezone.utc), "now").astimezone(timezone.utc)
    instrument = yf.Ticker(symbol)
    try:
        history = instrument.history(
            period="5d", interval="1m", prepost=True, auto_adjust=False, actions=False
        )
    except Exception as exc:  # pragma: no cover - provider/network behavior
        raise RuntimeError(f"market provider failed for {symbol}") from exc
    if history.empty or "Close" not in history:
        raise RuntimeError(f"market provider returned no observations for {symbol}")
    closes = history["Close"].dropna()
    if closes.empty:
        raise RuntimeError(f"market provider returned no usable close for {symbol}")
    observed_raw = closes.index[-1].to_pydatetime()
    if observed_raw.tzinfo is None or observed_raw.utcoffset() is None:
        raise RuntimeError("market provider returned a timezone-naive observation")
    price = _positive_number(closes.iloc[-1], "price")

    currency = "UNKNOWN"
    previous_close: float | None = None
    market_cap: float | None = None
    fast_info: Any = None
    try:
        fast_info = instrument.fast_info
        raw_currency = _metadata_get(fast_info, "currency")
        if isinstance(raw_currency, str) and raw_currency.strip():
            currency = raw_currency.strip().upper()
        raw_previous = _metadata_get(fast_info, "previous_close")
        if raw_previous is not None:
            previous_close = _positive_number(raw_previous, "previous_close")
        market_cap = _market_cap_from_provider_metadata(price=price, fast_info=fast_info)
    except Exception:  # pragma: no cover - optional provider metadata
        pass

    if market_cap is None:
        try:
            info = instrument.info
            market_cap = _market_cap_from_provider_metadata(
                price=price,
                fast_info=fast_info,
                info=info,
            )
            if currency == "UNKNOWN":
                raw_currency = _metadata_get(info, "currency")
                if isinstance(raw_currency, str) and raw_currency.strip():
                    currency = raw_currency.strip().upper()
            if previous_close is None:
                raw_previous = _metadata_get(info, "previousClose")
                if raw_previous is not None:
                    previous_close = _positive_number(raw_previous, "previous_close")
        except Exception:  # pragma: no cover - optional provider metadata
            pass

    state = MarketState.UNKNOWN
    try:
        metadata = instrument.get_history_metadata()
        state = _market_state(metadata.get("marketState"))
    except Exception:  # pragma: no cover - optional provider metadata
        pass

    snapshot = MarketSnapshot(
        ticker=symbol,
        price=price,
        currency=currency,
        observed_at=observed_raw,
        retrieved_at=retrieved_at,
        source="yfinance",
        market_state=state,
        previous_close=previous_close,
        market_cap=market_cap,
    )
    return _validate_snapshot(snapshot)


def snapshot_payload(snapshot: MarketSnapshot) -> dict[str, object]:
    """Return the stable serialization used to freeze a live observation."""
    validated = _validate_snapshot(snapshot)
    return {
        "schema_version": "1.0",
        "ticker": _ticker(validated.ticker),
        "price": validated.price,
        "currency": validated.currency,
        "observed_at": validated.observed_at.isoformat(),
        "retrieved_at": validated.retrieved_at.isoformat(),
        "source": validated.source,
        "market_state": validated.market_state.value,
        "previous_close": validated.previous_close,
        "market_cap": validated.market_cap,
    }


def write_market_snapshot(snapshot: MarketSnapshot, path: str | Path) -> Path:
    """Freeze an observation without changing its timestamps or semantics."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(snapshot_payload(snapshot), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output


def _parse_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise MarketDataError(f"{field} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise MarketDataError(f"{field} must be a valid ISO timestamp") from exc
    return _aware(parsed, field)


def load_market_snapshot(path: str | Path) -> MarketSnapshot:
    """Load a previously frozen market observation for deterministic analysis."""
    source_path = Path(path)
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MarketDataError(f"invalid market snapshot: {source_path}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        raise MarketDataError("unsupported market snapshot schema_version")
    raw_state = payload.get("market_state")
    try:
        state = MarketState(raw_state)
    except (TypeError, ValueError) as exc:
        raise MarketDataError("invalid market_state") from exc
    previous = payload.get("previous_close")
    market_cap = payload.get("market_cap")
    snapshot = MarketSnapshot(
        ticker=_ticker(str(payload.get("ticker", ""))),
        price=_positive_number(payload.get("price"), "price"),
        currency=str(payload.get("currency", "")).strip().upper(),
        observed_at=_parse_timestamp(payload.get("observed_at"), "observed_at"),
        retrieved_at=_parse_timestamp(payload.get("retrieved_at"), "retrieved_at"),
        source=str(payload.get("source", "")).strip(),
        market_state=state,
        previous_close=None if previous is None else _positive_number(previous, "previous_close"),
        market_cap=None if market_cap is None else _positive_number(market_cap, "market_cap"),
    )
    return _validate_snapshot(snapshot)
