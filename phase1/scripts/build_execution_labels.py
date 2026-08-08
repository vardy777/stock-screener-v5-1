#!/usr/bin/env python3
"""Build strict execution labels and their data-quality manifest."""

import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ROOT = BASE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BASE))

from overnight.execution_labels import build_execution_labels, save_execution_labels
from market_universe import list_universe_codes
from strategy_spec import DEFAULT_SPEC


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--snapshot-root",
        type=Path,
        default=BASE / "data" / "execution_snapshots" / "strict",
    )
    parser.add_argument(
        "--calendar",
        type=Path,
        default=BASE / "data" / "trading_calendar_cn.csv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=BASE / "data" / "overnight" / "execution_labels.csv.gz",
    )
    args = parser.parse_args()

    universe = list_universe_codes(BASE / "data" / "daily")
    labels, metadata = build_execution_labels(
        args.snapshot_root,
        DEFAULT_SPEC,
        universe_codes=universe,
        calendar_path=args.calendar,
    )
    save_execution_labels(labels, metadata, args.output)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    if not metadata["calendar_verified"]:
        print("[锁定] 缺少经核验的交易日历，标签不得进入生产准入")
    if metadata["strict_feature_rate"] < 1.0:
        print("[锁定] 尚无14:49:59前严格特征归档，标签暂不用于模型发布")
    print(f"已保存: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
