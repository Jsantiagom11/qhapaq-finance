"""CLI surface for the Executive Shortlist."""

from __future__ import annotations

import argparse
import asyncio
from datetime import date
from pathlib import Path

from qhapaq_finance.diamond.cache import DiamondCacheError
from qhapaq_finance.diamond.cli import (
    _production_funnel_provider,
)
from qhapaq_finance.diamond.providers.sec import (
    SecFirstProviderError,
)
from qhapaq_finance.diamond.providers.sp500 import (
    Sp500ProviderError,
)
from qhapaq_finance.diamond.providers.yahoo import (
    YahooProviderError,
)
from qhapaq_finance.sec_client import SecClientError

from .shortlist import (
    ExecutiveShortlistRun,
    canonical_shortlist_json,
    render_shortlist_text,
    run_shortlist,
)


def run_production_shortlist(
    *,
    universe_id: str,
    depth: int,
) -> ExecutiveShortlistRun:
    """Use the existing production Diamond provider wiring unchanged."""
    provider = _production_funnel_provider(
        Path("data/cache/diamond"),
        refresh=False,
    )

    return asyncio.run(
        run_shortlist(
            provider,
            universe_id=universe_id,
            as_of=date.today(),
            depth=depth,
            repository_root=Path("."),
        )
    )


def shortlist_command(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(
        description=("Run Diamond Top-N through bounded Executive Shortlist analysis")
    )
    parser.add_argument(
        "--universe",
        choices=("sp500",),
        default="sp500",
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=5,
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
    )
    args = parser.parse_args(arguments)

    if args.depth < 1:
        parser.error("--depth must be positive")

    try:
        run = run_production_shortlist(
            universe_id=args.universe,
            depth=args.depth,
        )
    except (
        DiamondCacheError,
        SecClientError,
        SecFirstProviderError,
        Sp500ProviderError,
        YahooProviderError,
    ) as exc:
        parser.error(str(exc))

    if args.format == "json":
        print(canonical_shortlist_json(run), end="")
    else:
        print(render_shortlist_text(run), end="")
