import argparse
from pathlib import Path

from .backtest import run_backtest
from .config import ResearchConfig
from .data import download_adjusted_close
from .report import build_manifest, write_manifest
from .walk_forward import run_walk_forward


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the documented QuantAncash baseline")
    parser.add_argument("--tickers", nargs="+", default=["SPY", "QQQ", "IWM", "EFA"])
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--end")
    parser.add_argument("--cost-bps", type=float, default=10.0)
    parser.add_argument("--walk-forward", action="store_true")
    parser.add_argument("--min-train-size", type=int, default=252)
    parser.add_argument("--test-size", type=int, default=63)
    parser.add_argument("--report-json", type=Path)
    args = parser.parse_args()
    prices = download_adjusted_close(args.tickers, args.start, args.end)
    config = ResearchConfig(transaction_cost_bps=args.cost_bps)
    if args.walk_forward:
        result = run_walk_forward(
            prices,
            config,
            min_train_size=args.min_train_size,
            test_size=args.test_size,
        )
        mode = "walk_forward"
    else:
        result = run_backtest(prices, config)
        mode = "full_sample"
    print(result.metrics.round(4).to_string())
    if args.report_json:
        write_manifest(args.report_json, build_manifest(prices, result, config, mode=mode))


if __name__ == "__main__":
    main()
