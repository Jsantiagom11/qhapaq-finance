import hashlib
import json
import math
import platform
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pandas as pd

from .backtest import BacktestResult
from .config import ResearchConfig


def price_checksum(prices: pd.DataFrame) -> str:
    payload = prices.to_csv(index=True, date_format="%Y-%m-%dT%H:%M:%S%z", float_format="%.12g")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_manifest(
    prices: pd.DataFrame,
    result: BacktestResult,
    config: ResearchConfig,
    *,
    mode: str,
) -> dict[str, Any]:
    metrics = {
        series_name: {
            metric: value if math.isfinite(float(value)) else None
            for metric, value in values.items()
        }
        for series_name, values in result.metrics.to_dict(orient="index").items()
    }
    return {
        "schema_version": 1,
        "mode": mode,
        "data": {
            "sha256": price_checksum(prices),
            "rows": len(prices),
            "assets": list(prices.columns),
            "start": prices.index[0].isoformat(),
            "end": prices.index[-1].isoformat(),
        },
        "config": asdict(config),
        "result": {
            "test_rows": len(result.returns),
            "start": result.returns.index[0].isoformat(),
            "end": result.returns.index[-1].isoformat(),
            "metrics": metrics,
        },
        "environment": {
            "python": platform.python_version(),
            "quantancash": version("quantancash"),
            "pandas": pd.__version__,
        },
    }


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n")
