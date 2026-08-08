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

from overnight.pipeline import rebuild_labeled_datasets
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
        default=BASE / "data" / "execution_snapshots" / "strict",
    )
    parser.add_argument(
        "--calendar",
        type=Path,
        default=BASE / "data" / "trading_calendar_cn.csv",
    )
    parser.add_argument(
        "--strict-output",
        type=Path,
        default=BASE / "data" / "overnight" / "strict_dataset.csv.gz",
    )
    args = parser.parse_args()

    print("=== 隔夜策略时点数据集 ===")
    dataset, metadata, strict, strict_metadata = rebuild_labeled_datasets(
        BASE / "data" / "daily",
        args.output,
        strict_path=args.strict_output,
        snapshot_root=args.snapshot_root,
        calendar_path=args.calendar,
        spec=DEFAULT_SPEC,
        max_stocks=args.max_stocks,
    )
    if dataset.empty:
        print("没有生成有效样本")
        return 1
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    if metadata.get("strict_1450_rows", 0) == 0:
        print("\n[警告] 当前历史库没有14:50分钟线；成交使用15:00收盘代理，仅供研究。")
    if not metadata.get("strict_dataset_ready", False):
        print("[锁定] 买入、卖出、信号特征或交易日历尚未达到全严格口径")
    print(f"严格样本: {len(strict)} 行 | {args.strict_output}")
    print(
        "严格数据集就绪: "
        f"{bool(strict_metadata.get('strict_dataset_ready', False))}"
    )
    print(f"严格执行标签: {BASE / 'data' / 'overnight' / 'execution_labels.csv.gz'}")
    print(f"\n已保存: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
