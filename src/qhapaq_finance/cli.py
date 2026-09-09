import argparse
import os
import sys
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .backtest import run_backtest
from .config import ResearchConfig
from .dashboard import (
    build_company_artifact,
    build_universe_artifact,
    canonical_json,
    render_company_dashboard,
    render_universe_dashboard,
    write_artifacts,
)
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
from .valuation import ResearchResult, analyze_case, load_fixture_case


def _investigate(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(
        description="Run the provider-backed Qhapaq agent research layer"
    )
    parser.add_argument("ticker", choices=("QCOM", "VRTX", "CSCO"), type=str.upper)
    parser.add_argument(
        "--json", action="store_true", help="emit the stable agent research artifact"
    )
    parser.add_argument("--model", default="gpt-4.1-mini")
    args = parser.parse_args(arguments)
    if not os.environ.get("OPENAI_API_KEY"):
        parser.error("investigate requires OPENAI_API_KEY; deterministic commands remain offline")
    from .agents.openai_adapter import OpenAIAgentsProvider
    from .agents.orchestrator import ResearchOrchestrator

    result = ResearchOrchestrator(OpenAIAgentsProvider(model=args.model)).investigate(
        build_company_artifact(args.ticker)
    )
    if args.json:
        print(canonical_json(result.to_dict()), end="")
    else:
        print(f"ticker={result.ticker}")
        print(f"assessment={result.synthesis.assessment}")
        print(f"confidence={result.synthesis.confidence}")


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


def _research_case(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Analyze a deterministic FCFF/WACC research case")
    parser.add_argument("ticker", choices=("QCOM", "VRTX", "CSCO"), type=str.upper)
    parser.add_argument(
        "--provenance", action="store_true", help="print frozen QCOM evidence bridge"
    )
    parser.add_argument("--json", action="store_true", help="emit deterministic research JSON")
    args = parser.parse_args(arguments)
    if args.json:
        print(canonical_json(build_company_artifact(args.ticker)), end="")
        return
    result = analyze_case(load_fixture_case(args.ticker))
    _print_research_result(result)
    if args.ticker == "QCOM":
        from .qcom_case import qcom_audit

        for key, value in qcom_audit().items():
            print(f"{key}={value}")


def _print_research_result(result: ResearchResult) -> None:
    case = result.case
    print(f"ticker={case.ticker}")
    print(f"as_of={case.as_of_date.isoformat()}")
    print(f"provenance={case.provenance}")
    print(
        "case_kind=evidence-backed" if case.ticker == "QCOM" else "case_kind=illustrative fixture"
    )
    print(f"reconstructed_fcff={result.reconstructed_fcff:.0f}")
    print(f"normalized_fcff={result.normalized_fcff:.0f}")
    print(f"nopat={result.nopat:.0f}")
    print(f"roic={result.roic:.2%}")
    print(f"reinvestment_rate={case.reinvestment_rate:.2%}")
    print(f"growth_consistency={result.growth_consistency}")
    cost = case.capital_cost
    for name in (
        "risk_free_rate",
        "equity_risk_premium",
        "beta",
        "cost_of_equity",
        "pre_tax_cost_of_debt",
        "tax_rate",
        "market_equity",
        "debt",
        "equity_weight",
        "debt_weight",
        "wacc",
    ):
        value = getattr(cost, name)
        if name in {"beta", "market_equity", "debt"}:
            print(f"{name}={value:.2f}" if name == "beta" else f"{name}={value:.0f}")
        else:
            print(f"{name}={value:.2%}")
    for scenario in result.scenarios:
        prefix = f"{scenario.name}_"
        print(f"{prefix}intrinsic_value={scenario.intrinsic_value_per_share:.2f}")
        print(f"{prefix}margin_of_safety={scenario.margin_of_safety:.2%}")
        print(f"{prefix}terminal_spread={scenario.terminal_spread:.2%}")
        print(f"{prefix}terminal_value_share={scenario.terminal_value_share:.2%}")
    print(f"reverse_implied_growth={result.reverse_implied_growth:.2%}")
    print(f"fcff_implied_discount_rate={result.fcff_implied_discount_rate:.2%}")
    print(f"thesis={' | '.join(case.thesis)}")
    print(f"invalidation={' | '.join(case.invalidation_conditions)}")
    print(f"diagnostics={' | '.join(result.diagnostics) if result.diagnostics else 'none'}")


def _compare(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Compare deterministic FCFF/WACC research cases")
    parser.add_argument("tickers", nargs="+", choices=("QCOM", "VRTX", "CSCO"), type=str.upper)
    parser.add_argument("--json", action="store_true", help="emit deterministic universe JSON")
    args = parser.parse_args(arguments)
    if args.json:
        print(canonical_json(build_universe_artifact(tuple(args.tickers))), end="")
        return
    print(
        " ".join(
            (
                "ticker",
                "normalized_fcff_yield",
                "roic",
                "wacc",
                "roic_minus_wacc",
                "base_mos",
                "bear_mos",
                "fcff_implied_discount_rate",
                "terminal_value_share",
            )
        )
    )
    for ticker in args.tickers:
        result = analyze_case(load_fixture_case(ticker))
        case = result.case
        scenarios = {item.name: item for item in result.scenarios}
        yield_value = result.normalized_fcff / case.market_snapshot.enterprise_value
        print(
            f"{ticker} {yield_value:.2%} {result.roic:.2%} {case.capital_cost.wacc:.2%} "
            f"{result.roic - case.capital_cost.wacc:.2%} {scenarios['base'].margin_of_safety:.2%} "
            f"{scenarios['bear'].margin_of_safety:.2%} "
            f"{result.fcff_implied_discount_rate:.2%} "
            f"{scenarios['base'].terminal_value_share:.2%}"
        )


def _dashboard(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Generate an offline Qhapaq research dashboard")
    parser.add_argument("ticker", nargs="?", choices=("QCOM", "VRTX", "CSCO"), type=str.upper)
    parser.add_argument("--universe", nargs="+", choices=("QCOM", "VRTX", "CSCO"), type=str.upper)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts"))
    args = parser.parse_args(arguments)
    if (args.ticker is None) == (args.universe is None):
        parser.error("provide one ticker or --universe TICKER [...]")
    tickers = (args.ticker,) if args.ticker else tuple(args.universe)
    written = write_artifacts(tickers, args.output_dir)
    if args.ticker:
        output = render_company_dashboard(
            build_company_artifact(args.ticker),
            args.output_dir / f"{args.ticker.lower()}-dashboard.html",
        )
    else:
        output = render_universe_dashboard(
            build_universe_artifact(tickers), args.output_dir / "qhapaq-universe.html"
        )
    print(f"dashboard={output}")
    for name, path in sorted(written.items()):
        print(f"artifact_{name}={path}")


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
        if len(arguments) >= 2 and arguments[1].upper() in {"QCOM", "VRTX", "CSCO"}:
            _research_case(arguments[1:])
        else:
            _research(arguments[1:])
    elif arguments and arguments[0] == "compare":
        _compare(arguments[1:])
    elif arguments and arguments[0] == "dashboard":
        _dashboard(arguments[1:])
    elif arguments and arguments[0] == "market":
        _market(arguments[1:])
    elif arguments and arguments[0] == "investigate":
        _investigate(arguments[1:])
    elif arguments and arguments[0] == "reverse-dcf":
        _reverse_dcf(arguments[1:])
    elif arguments and not arguments[0].startswith("-"):
        _one(arguments)
    else:
        _baseline(arguments)


if __name__ == "__main__":
    main()
