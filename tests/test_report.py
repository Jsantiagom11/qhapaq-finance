import json

import numpy as np
import pandas as pd

from quantancash.backtest import run_backtest
from quantancash.config import ResearchConfig
from quantancash.report import build_manifest, price_checksum, write_manifest


def prices(rows: int = 80) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=rows, freq="B")
    return pd.DataFrame(
        {
            "AAA": 100 * np.cumprod(np.full(rows, 1.001)),
            "BBB": 100 * np.cumprod(np.full(rows, 0.999)),
        },
        index=index,
    )


def test_price_checksum_is_stable_and_sensitive_to_one_value() -> None:
    original = prices()
    changed = original.copy()
    changed.iloc[-1, -1] += 0.01
    assert price_checksum(original) == price_checksum(original.copy())
    assert price_checksum(original) != price_checksum(changed)


def test_manifest_records_data_config_environment_and_metrics(tmp_path) -> None:
    panel = prices()
    config = ResearchConfig(lookback_days=10, rebalance_days=5)
    result = run_backtest(panel, config)
    manifest = build_manifest(panel, result, config, mode="full_sample")
    path = tmp_path / "nested" / "report.json"
    write_manifest(path, manifest)
    loaded = json.loads(path.read_text())
    assert loaded["schema_version"] == 1
    assert loaded["data"]["sha256"] == price_checksum(panel)
    assert loaded["config"]["lookback_days"] == 10
    assert "strategy_net" in loaded["result"]["metrics"]
    assert loaded["environment"]["quantancash"]
