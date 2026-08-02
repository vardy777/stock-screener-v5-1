#!/usr/bin/env python3
"""Build the point-in-time overnight research dataset."""

import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ROOT = BASE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BASE))

from overnight.dataset import build_dataset, save_dataset
from overnight.execution_labels import build_execution_labels, save_execution_labels
from strategy_spec import DEFAULT_SPEC


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-stocks", type=int, default=None)
    parser.add_argument(
        "--output",
        type=Path,
        default=BASE / "data" / "overnight" / "dataset.csv.gz",
    )
    parser.add_argument(
        "--snapshot-root",
        type=Path,
        default=BASE / "data" / "execution_snapshots",
    )
    parser.add_argument(
        "--calendar",
        type=Path,
        default=BASE / "data" / "trading_calendar_cn.csv",
    )
    args = parser.parse_args()

    print("=== 隔夜策略时点数据集 ===")
    universe = sorted(path.stem.zfill(6) for path in (BASE / "data" / "daily").glob("*.csv"))
    execution_labels, execution_metadata = build_execution_labels(
        args.snapshot_root,
        DEFAULT_SPEC,
        universe_codes=universe,
        calendar_path=args.calendar,
    )
    execution_output = BASE / "data" / "overnight" / "execution_labels.csv.gz"
    save_execution_labels(execution_labels, execution_metadata, execution_output)
    dataset, metadata = build_dataset(
        BASE / "data" / "daily",
        DEFAULT_SPEC,
        max_stocks=args.max_stocks,
        execution_labels=execution_labels,
        execution_metadata=execution_metadata,
    )
    if dataset.empty:
        print("没有生成有效样本")
        return 1
    save_dataset(dataset, metadata, args.output)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    if metadata.get("strict_1450_rows", 0) == 0:
        print("\n[警告] 当前历史库没有14:50分钟线；成交使用15:00收盘代理，仅供研究。")
    if not metadata.get("strict_dataset_ready", False):
        print("[锁定] 买入、卖出、信号特征或交易日历尚未达到全严格口径")
    print(f"严格执行标签: {execution_output}")
    print(f"\n已保存: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
