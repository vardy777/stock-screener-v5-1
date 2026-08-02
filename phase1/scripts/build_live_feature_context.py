#!/usr/bin/env python3
"""Precompute previous-session feature context before the 14:49 job."""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ROOT = BASE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BASE))

from overnight.live_features import build_live_feature_context, save_live_feature_context
from v4.calendar import TradingCalendar


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trade-date", default=date.today().isoformat())
    parser.add_argument("--max-stocks", type=int, default=None)
    parser.add_argument(
        "--output",
        type=Path,
        default=BASE / "data" / "overnight" / "live_feature_context.csv.gz",
    )
    args = parser.parse_args()
    calendar = TradingCalendar()
    trade_date = date.fromisoformat(args.trade_date)
    previous = calendar.previous_open(trade_date)
    if previous is None:
        print("拒绝构建: 交易日历未核验或未覆盖")
        return 2
    context, metadata = build_live_feature_context(
        BASE / "data" / "daily",
        previous.isoformat(),
        max_stocks=args.max_stocks,
    )
    save_live_feature_context(context, metadata, args.output)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    if not metadata["strict_context_ready"]:
        print("[锁定] 上一交易日完整历史覆盖不足95%，不得发布严格实时特征")
    print(f"已保存: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

