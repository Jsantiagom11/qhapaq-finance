import argparse

from .backtest import run_backtest
from .config import ResearchConfig
from .data import download_adjusted_close


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the documented QuantAncash baseline")
    parser.add_argument("--tickers", nargs="+", default=["SPY", "QQQ", "IWM", "EFA"])
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--end")
    parser.add_argument("--cost-bps", type=float, default=10.0)
    args = parser.parse_args()
    prices = download_adjusted_close(args.tickers, args.start, args.end)
    result = run_backtest(prices, ResearchConfig(transaction_cost_bps=args.cost_bps))
    print(result.metrics.round(4).to_string())


if __name__ == "__main__":
    main()

