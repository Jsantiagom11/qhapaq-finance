"""Build the offline SEC locator sidecar for a sealed Opportunities report."""

from __future__ import annotations

import argparse
from pathlib import Path

from qhapaq_finance.sec_locator import write_sec_locator_matrix


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--opportunities", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    matrix = write_sec_locator_matrix(
        snapshot_root=args.snapshot_root,
        opportunities_path=args.opportunities,
        output_path=args.output,
    )
    summary = matrix["summary"]
    print(
        f"observations={summary['total_observations']} "
        f"exact={summary['by_status']['EXACT_FILING_MATCH']} output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
