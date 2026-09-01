import argparse
import sys
from datetime import datetime
from pathlib import Path

from .backtest import run_backtest
from .config import ResearchConfig
from .data import download_adjusted_close, file_sha256
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


def main(argv: list[str] | None = None) -> None:
    arguments = sys.argv[1:] if argv is None else argv
    if arguments and arguments[0] == "tearsheet":
        _tearsheet(arguments[1:])
    else:
        _baseline(arguments)


if __name__ == "__main__":
    main()
