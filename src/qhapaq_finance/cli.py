import argparse
import sys
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .backtest import run_backtest
from .config import ResearchConfig
from .data import download_adjusted_close, file_sha256
from .expectations import ReverseDcfInputs, solve_implied_fcf_growth
from .market import (
    FreshnessPolicy,
    classify_freshness,
    fetch_yfinance_snapshot,
    load_market_snapshot,
    snapshot_age,
    write_market_snapshot,
)
from .one import build_one_model, render_one_html
from .research import load_research_record
from .research_report import render_research_report
from .tearsheet import build_tearsheet_model, png_dimensions, render_tearsheet


def _baseline(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Run the documented Qhapaq Finance baseline")
    parser.add_argument("--tickers", nargs="+", default=["SPY", "QQQ", "IWM", "EFA"])
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--end")
    parser.add_argument("--cost-bps", type=float, default=10.0)
    args = parser.parse_args(arguments)
    prices = download_adjusted_close(args.tickers, args.start, args.end)
    result = run_backtest(prices, ResearchConfig(transaction_cost_bps=args.cost_bps))
    print(result.metrics.round(4).to_string())


def _tearsheet(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Render the verified frozen ECB FX tear sheet")
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--as-of", type=lambda value: datetime.strptime(value, "%Y-%m-%d").date())
    args = parser.parse_args(arguments)
    output = render_tearsheet(
        data_path=args.data,
        manifest_path=args.manifest,
        output_path=args.output,
        as_of=args.as_of,
    )
    model = build_tearsheet_model(
        data_path=args.data, manifest_path=args.manifest, as_of=args.as_of
    )
    width, height = png_dimensions(output)
    print(f"output={output}")
    print(f"dimensions={width}x{height}")
    print(f"effective_as_of={model.snapshot.effective_as_of}")
    print(f"observation_window={model.rates.index[0].date()}/{model.rates.index[-1].date()}")
    print(f"observation_count={len(model.rates)}")
    print(f"png_sha256={file_sha256(output)}")


def _research(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(
        description="Render a verified offline company research report"
    )
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--result-manifest", type=Path)
    parser.add_argument(
        "--as-of", type=lambda value: datetime.strptime(value, "%Y-%m-%d").date(), required=True
    )
    args = parser.parse_args(arguments)
    record = load_research_record(
        record_path=args.record,
        manifest_path=args.manifest,
        repository_root=Path("."),
        as_of=args.as_of,
    )
    output = render_research_report(
        record_path=args.record,
        manifest_path=args.manifest,
        output_path=args.output,
        result_manifest_path=args.result_manifest,
        as_of=args.as_of,
    )
    issuer = record.issuer
    coverage = "; ".join(f"{source.title} [{source.reporting_period}]" for source in record.sources)
    print(f"output={output}")
    print(f"cutoff={args.as_of}")
    print(f"issuer={issuer['name']} ({issuer['ticker']})")
    print(f"evidence_coverage={coverage}")
    print(f"html_sha256={file_sha256(output)}")


def _market(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(
        description="Inspect a timestamped market observation without changing frozen research"
    )
    parser.add_argument("ticker", nargs="?")
    parser.add_argument("--snapshot", type=Path, help="load a previously frozen market snapshot")
    parser.add_argument("--output", type=Path, help="freeze the observation as deterministic JSON")
    parser.add_argument("--max-age-minutes", type=float, default=30.0)
    args = parser.parse_args(arguments)
    if (args.ticker is None) == (args.snapshot is None):
        parser.error("provide exactly one of ticker or --snapshot")
    if args.max_age_minutes <= 0:
        parser.error("--max-age-minutes must be positive")

    now = datetime.now(timezone.utc)
    snapshot = (
        load_market_snapshot(args.snapshot)
        if args.snapshot is not None
        else fetch_yfinance_snapshot(args.ticker, now=now)
    )
    policy = FreshnessPolicy(max_age=timedelta(minutes=args.max_age_minutes))
    freshness = classify_freshness(snapshot, policy=policy, now=now)
    age_seconds = snapshot_age(snapshot, now=now).total_seconds()
    if args.output is not None:
        write_market_snapshot(snapshot, args.output)

    print(f"ticker={snapshot.ticker}")
    print(f"price={snapshot.price:.8g}")
    print(f"currency={snapshot.currency}")
    print(f"observed_at={snapshot.observed_at.isoformat()}")
    print(f"retrieved_at={snapshot.retrieved_at.isoformat()}")
    print(f"source={snapshot.source}")
    print(f"market_state={snapshot.market_state.value}")
    print(f"age_seconds={age_seconds:.0f}")
    print(f"freshness={freshness.value}")
    if snapshot.market_cap is not None:
        print(f"market_cap={snapshot.market_cap:.12g}")
    if snapshot.previous_close is not None:
        print(f"previous_close={snapshot.previous_close:.8g}")
        change = snapshot.change_from_previous_close
        if change is not None:
            print(f"change_from_previous_close={change:.8f}")
    if args.output is not None:
        print(f"snapshot_output={args.output}")


def _reverse_dcf(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Solve constant equity-FCF growth implied by an observed equity value; "
            "--discount-rate is cost of equity, not WACC"
        )
    )
    parser.add_argument("--equity-value", type=float, required=True)
    parser.add_argument("--starting-fcf", type=float, required=True)
    parser.add_argument(
        "--discount-rate",
        type=float,
        required=True,
        help="cost of equity for the equity-FCF / equity-value model",
    )
    parser.add_argument("--terminal-growth", type=float, required=True)
    parser.add_argument("--years", type=int, default=10)
    args = parser.parse_args(arguments)
    result = solve_implied_fcf_growth(
        ReverseDcfInputs(
            equity_value=args.equity_value,
            starting_fcf=args.starting_fcf,
            discount_rate=args.discount_rate,
            terminal_growth=args.terminal_growth,
            years=args.years,
        )
    )
    print(f"equity_value={result.equity_value:.12g}")
    print(f"starting_fcf={result.starting_fcf:.12g}")
    print(f"years={result.years}")
    print(f"cost_of_equity={result.discount_rate:.8f}")
    print(f"terminal_growth={result.terminal_growth:.8f}")
    print(f"implied_fcf_growth={result.implied_fcf_growth:.8f}")
    print(f"implied_fcf_growth_pct={result.implied_fcf_growth * 100:.4f}")
    print(f"solved_present_value={result.solved_present_value:.12g}")


def _one(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(
        description="Render Qhapaq One: analytical run-rate cash basis and market expectations"
    )
    parser.add_argument("ticker")
    parser.add_argument("--snapshot", type=Path, help="use a previously frozen market snapshot")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--market-snapshot-output", type=Path)
    parser.add_argument("--max-age-minutes", type=float, default=30.0)
    parser.add_argument(
        "--discount-rate",
        type=float,
        default=0.09,
        help="cost of equity for the equity-FCF reverse DCF",
    )
    parser.add_argument("--terminal-growth", type=float, default=0.03)
    parser.add_argument("--years", type=int, default=10)
    parser.add_argument("--no-open", action="store_true", help="render without opening a browser")
    args = parser.parse_args(arguments)
    if args.max_age_minutes <= 0:
        parser.error("--max-age-minutes must be positive")

    ticker = args.ticker.strip().upper()
    now = datetime.now(timezone.utc)
    snapshot = (
        load_market_snapshot(args.snapshot)
        if args.snapshot is not None
        else fetch_yfinance_snapshot(ticker, now=now)
    )
    if snapshot.ticker != ticker:
        parser.error(f"snapshot ticker {snapshot.ticker} does not match requested ticker {ticker}")

    output = args.output or Path("output/qhapaq-one") / f"{ticker.lower()}.html"
    snapshot_output = (
        args.market_snapshot_output or Path("output/qhapaq-one") / f"{ticker.lower()}.market.json"
    )
    write_market_snapshot(snapshot, snapshot_output)
    model = build_one_model(
        snapshot=snapshot,
        repository_root=Path("."),
        max_age=timedelta(minutes=args.max_age_minutes),
        now=now,
        discount_rate=args.discount_rate,
        terminal_growth=args.terminal_growth,
        years=args.years,
    )
    rendered = render_one_html(model, output)

    print(f"ticker={model.ticker}")
    print(f"status={model.status}")
    print(f"freshness={model.freshness.value}")
    if model.cash_basis_value is not None:
        print(f"cash_basis_value={model.cash_basis_value:.12g}")
    if model.implied_fcf_growth is not None:
        print(f"implied_fcf_growth_pct={model.implied_fcf_growth * 100:.4f}")
    print(f"market_snapshot={snapshot_output}")
    print(f"output={rendered}")
    if not args.no_open:
        webbrowser.open(rendered.resolve().as_uri())


def main(argv: list[str] | None = None) -> None:
    arguments = sys.argv[1:] if argv is None else argv
    if arguments and arguments[0] == "tearsheet":
        _tearsheet(arguments[1:])
    elif arguments and arguments[0] == "research":
        _research(arguments[1:])
    elif arguments and arguments[0] == "market":
        _market(arguments[1:])
    elif arguments and arguments[0] == "reverse-dcf":
        _reverse_dcf(arguments[1:])
    elif arguments and not arguments[0].startswith("-"):
        _one(arguments)
    else:
        _baseline(arguments)


if __name__ == "__main__":
    main()
