"""CLI handlers for the local-first Diamond Funnel V0.1 product surface."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

from qhapaq_finance.sec_client import SecClient, SecClientError
from qhapaq_finance.sec_config import SecConfig

from .archetypes import Archetype
from .cache import DiamondCache, DiamondCacheError
from .engine import DiamondResult, evaluate_universe
from .funnel import FunnelRun, run_funnel
from .providers.benchmark import benchmark_provider_sample
from .providers.local import LocalJsonProvider
from .providers.sec import SecFirstProvider, SecFirstProviderError
from .providers.sp500 import Sp500ProviderError, Sp500UniverseProvider, WikipediaTextClient
from .providers.yahoo import YahooBatchMarketProvider, YahooClient, YahooProviderError
from .serialization import canonical_diamond_json, diamond_csv, diamond_result_dict


def _iso_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD")
    return parsed


def _load_results(
    path: Path, as_of: date | None
) -> tuple[tuple[DiamondResult, ...], LocalJsonProvider]:
    provider = LocalJsonProvider(path)
    effective = as_of or provider.data_as_of
    securities = provider.universe(provider.universe_id, effective)
    records = provider.fundamentals(securities, effective)
    return evaluate_universe(records), provider


def _ranked(results: tuple[DiamondResult, ...]) -> list[DiamondResult]:
    return sorted(
        results,
        key=lambda item: (
            item.archetypes.research_priority is None,
            -(item.archetypes.research_priority or 0.0),
            item.ticker,
        ),
    )


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:6.1f}"


def _print_screen_table(results: tuple[DiamondResult, ...]) -> None:
    print("ticker  priority  surfaced_by      quality growth capital price  diagnostics")
    for result in _ranked(results):
        surfaced = result.archetypes.surfaced_by.value if result.archetypes.surfaced_by else "-"
        print(
            f"{result.ticker:<7} {_fmt(result.archetypes.research_priority):>8}  "
            f"{surfaced:<16} {_fmt(result.scores.quality)} {_fmt(result.scores.growth)} "
            f"{_fmt(result.scores.capital)} {_fmt(result.scores.price)}  "
            f"{','.join(result.diagnostics) or 'none'}"
        )


def screen_command(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Run the offline Diamond Funnel discovery layer")
    parser.add_argument(
        "--input", type=Path, required=True, help="canonical local fundamentals JSON"
    )
    parser.add_argument("--depth", type=int, default=25)
    parser.add_argument("--sector")
    parser.add_argument("--archetype", choices=("compounder", "quality-value", "inflection"))
    parser.add_argument("--as-of", type=_iso_date)
    parser.add_argument("--format", choices=("table", "json", "csv"), default="table")
    args = parser.parse_args(arguments)
    if args.depth < 1:
        parser.error("--depth must be positive")
    results, provider = _load_results(args.input, args.as_of)
    allowed = {record.ticker for record in provider.records()}
    if args.sector:
        allowed = {
            record.ticker
            for record in provider.records()
            if record.sector and record.sector.casefold() == args.sector.casefold()
        }
    filtered = [item for item in results if item.ticker in allowed]
    if args.archetype:
        wanted = {
            "compounder": Archetype.COMPOUNDER,
            "quality-value": Archetype.QUALITY_VALUE,
            "inflection": Archetype.INFLECTION,
        }[args.archetype]
        filtered = [item for item in filtered if item.archetypes.surfaced_by is wanted]
    ranked = tuple(_ranked(tuple(filtered))[: args.depth])
    if args.format == "json":
        print(canonical_diamond_json(ranked), end="")
    elif args.format == "csv":
        print(diamond_csv(ranked), end="")
    else:
        _print_screen_table(ranked)


def inspect_command(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Explain one offline Diamond Funnel result")
    parser.add_argument("ticker")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--as-of", type=_iso_date)
    parser.add_argument("--format", choices=("table", "json"), default="table")
    args = parser.parse_args(arguments)
    ticker = args.ticker.strip().upper()
    results, _ = _load_results(args.input, args.as_of)
    result = next((item for item in results if item.ticker == ticker), None)
    if result is None:
        parser.error(f"ticker not found in input: {ticker}")
    if args.format == "json":
        print(
            json.dumps(
                diamond_result_dict(result),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n",
            end="",
        )
        return
    print(f"{result.ticker} — {result.company_name}")
    print(f"METHODOLOGY {result.methodology.value}")
    print(f"PEER {result.peer_scope} ({result.peer_count})")
    print(f"RESEARCH PRIORITY {_fmt(result.archetypes.research_priority).strip()}")
    print(
        "SURFACED BY "
        + (result.archetypes.surfaced_by.value if result.archetypes.surfaced_by else "-")
    )
    for name in ("quality", "growth", "capital", "price"):
        print(f"{name.upper()} {_fmt(getattr(result.scores, name)).strip()}")
    print("PERCENTILES")
    for name, value in sorted(result.percentiles.items()):
        print(f"  {name}={_fmt(value).strip()}")
    print(
        "COVERAGE " + " ".join(f"{key}={value}" for key, value in sorted(result.coverage.items()))
    )
    print("DIAGNOSTICS " + (" | ".join(result.diagnostics) if result.diagnostics else "none"))
    print(f"PROVIDER {result.provider} {result.provider_identity or '-'}")


def provider_benchmark_command(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Benchmark an offline structured-data candidate")
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--format", choices=("table", "json"), default="table")
    args = parser.parse_args(arguments)
    metadata: dict[str, object] | None = None
    if args.metadata is not None:
        try:
            raw = json.loads(args.metadata.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            parser.error(f"invalid metadata file: {exc}")
        if not isinstance(raw, dict):
            parser.error("metadata must be a JSON object")
        metadata = raw
    result = benchmark_provider_sample(
        reference=LocalJsonProvider(args.reference),
        candidate=LocalJsonProvider(args.candidate),
        operational_metadata=metadata,
    )
    if args.format == "json":
        print(
            json.dumps(
                result.to_dict(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n",
            end="",
        )
        return
    print(f"provider={result.provider}")
    print(f"record_count={result.record_count}")
    print(f"identity_pass_rate={result.identity_pass_rate:.3f}")
    print(f"required_family_coverage={result.required_family_coverage:.3f}")
    print(f"period_identity_pass_rate={result.period_identity_pass_rate:.3f}")
    print(f"sign_semantics_pass_rate={result.sign_semantics_pass_rate:.3f}")
    print(f"share_basis_pass_rate={result.share_basis_pass_rate:.3f}")
    print(f"canonical_parse_pass_rate={result.canonical_parse_pass_rate:.3f}")
    print(f"diagnostics={','.join(result.diagnostics) or 'none'}")


def _funnel_json(run: FunnelRun) -> str:
    payload = {
        "schema_version": "diamond-funnel-run-v1",
        "metadata": asdict(run.metadata),
        "results": [diamond_result_dict(item) for item in run.results],
    }
    return (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )


def _print_funnel_metadata(run: FunnelRun) -> None:
    metadata = run.metadata
    print(
        (
            f"universe={metadata.universe_count} "
            f"canonical={metadata.canonical_records} "
            f"ranked={metadata.ranked_records} "
            f"unranked={metadata.unranked_records}"
        ),
        file=sys.stderr,
    )
    print(
        (
            f"provider_requests={metadata.provider_requests} "
            f"cache_hits={metadata.cache_hits} "
            f"cache_misses={metadata.cache_misses}"
        ),
        file=sys.stderr,
    )
    print(
        (
            f"acquisition_seconds="
            f"{metadata.acquisition_seconds:.3f} "
            f"evaluation_seconds="
            f"{metadata.evaluation_seconds:.3f}"
        ),
        file=sys.stderr,
    )
    print(
        f"dataset_identity={metadata.dataset_identity}",
        file=sys.stderr,
    )


def _production_funnel_provider(cache_root: Path, *, refresh: bool) -> SecFirstProvider:
    try:
        sec_config = SecConfig.from_env()
    except RuntimeError as exc:
        raise SecFirstProviderError(f"SEC_CONFIG_INVALID:{exc}") from exc
    universe_provider = Sp500UniverseProvider(
        client=WikipediaTextClient(),
        cache=DiamondCache(cache_root / "universe"),
        refresh=refresh,
    )
    market_provider = YahooBatchMarketProvider(
        client=YahooClient(),
        cache=DiamondCache(cache_root / "market"),
        refresh=refresh,
    )
    return SecFirstProvider(
        universe_provider=universe_provider,
        sec_client=SecClient(sec_config),
        sec_cache=DiamondCache(cache_root / "sec"),
        market_provider=market_provider,
        refresh=refresh,
    )


def funnel_command(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(
        description=("Run the production Diamond Funnel discovery layer")
    )
    parser.add_argument(
        "--universe",
        choices=("sp500",),
        default="sp500",
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=10,
    )
    parser.add_argument(
        "--as-of",
        type=_iso_date,
        default=date.today(),
    )
    parser.add_argument(
        "--format",
        choices=("table", "json", "csv"),
        default="table",
    )
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=Path("data/cache/diamond"),
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="bypass cache and reacquire provider evidence",
    )
    args = parser.parse_args(arguments)

    if args.depth < 1:
        parser.error("--depth must be positive")

    try:
        provider = _production_funnel_provider(args.cache_root, refresh=args.refresh)
        run = run_funnel(
            provider,
            universe_id=args.universe,
            as_of=args.as_of,
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
        print(_funnel_json(run), end="")
    elif args.format == "csv":
        print(diamond_csv(run.results), end="")
    else:
        _print_screen_table(run.results)

    _print_funnel_metadata(run)
