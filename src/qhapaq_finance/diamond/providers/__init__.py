"""Diamond Funnel provider adapters."""

from .local import LocalJsonProvider
from .protocol import FundamentalDataProvider

__all__ = ["FundamentalDataProvider", "LocalJsonProvider"]
