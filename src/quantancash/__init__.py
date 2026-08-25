"""QuantAncash: small, auditable quantitative research primitives."""

from .backtest import BacktestResult, run_backtest
from .config import ResearchConfig

__all__ = ["BacktestResult", "ResearchConfig", "run_backtest"]
__version__ = "0.2.0"

