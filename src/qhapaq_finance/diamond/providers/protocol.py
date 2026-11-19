"""Provider-neutral acquisition boundary for Diamond Funnel."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from ..contracts import FundamentalRecord, SecurityRef


class FundamentalDataProvider(Protocol):
    def universe(self, universe_id: str, as_of: date) -> tuple[SecurityRef, ...]: ...

    def fundamentals(
        self,
        securities: tuple[SecurityRef, ...],
        as_of: date,
        history_years: int = 5,
    ) -> tuple[FundamentalRecord, ...]: ...
