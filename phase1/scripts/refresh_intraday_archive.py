#!/usr/bin/env python3
"""Refresh existing 60-minute files without replacing them on bad responses."""

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ROOT = BASE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BASE))

import pandas as pd

from overnight.archive_refresh import merge_archive, save_archive_atomic, validate_archive
from overnight.dataset import is_eligible_code
from v4.data import DataFetcher
from v4.calendar import TradingCalendar


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trade-date", default=date.today().isoformat())
    parser.add_argument("--max-stocks", type=int, default=None)
    parser.add_argument("--bars", type=int, default=120)
    parser.add_argument("--delay", type=float, default=0.15)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--report",
        type=Path,
        default=BASE / "data" / "overnight" / "archive_refresh_report.json",
    )
    args = parser.parse_args()

    calendar = TradingCalendar()
    trade_date = date.fromisoformat(args.trade_date)
    expected = calendar.previous_open(trade_date)
    if expected is None:
        print("拒绝刷新: 交易日历未核验或未覆盖")
        return 2

    paths = [
        path for path in sorted((BASE / "data" / "daily").glob("*.csv"))
        if is_eligible_code(path.stem)
    ]
    if args.max_stocks is not None:
        paths = paths[: max(0, args.max_stocks)]
    fetcher = DataFetcher()
    reasons = {}
    updated = 0
    failed = 0
    for index, path in enumerate(paths, start=1):
        reason = "unknown"
        try:
            recent = fetcher.fetch_kline(path.stem, days=max(40, args.bars), scale=60)
            valid_recent, reason = validate_archive(recent, expected.isoformat())
            if not valid_recent:
                failed += 1
            else:
                existing = pd.read_csv(path, low_memory=False)
                merged = merge_archive(existing, recent)
                valid_merged, reason = validate_archive(merged, expected.isoformat())
                if not valid_merged or len(merged) < len(existing):
                    failed += 1
                    reason = reason if not valid_merged else "row_count_regression"
                else:
                    if not args.dry_run:
                        save_archive_atomic(merged, path)
                    updated += 1
                    reason = "dry_run_ok" if args.dry_run else "updated"
        except Exception as exc:
            failed += 1
            reason = f"exception:{type(exc).__name__}"
        reasons[reason] = reasons.get(reason, 0) + 1
        if index % 100 == 0 or index == len(paths):
            print(f"  archive refresh: {index}/{len(paths)} updated={updated} failed={failed}", flush=True)
        if args.delay > 0 and index < len(paths):
            time.sleep(args.delay)

    report = {
        "trade_date": trade_date.isoformat(),
        "expected_previous_session": expected.isoformat(),
        "files_considered": len(paths),
        "updated": updated,
        "failed": failed,
        "success_rate": updated / len(paths) if paths else 0.0,
        "dry_run": bool(args.dry_run),
        "reasons": reasons,
        "strict_archive_ready": bool(paths and updated / len(paths) >= 0.95),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.report.with_suffix(args.report.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(args.report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["strict_archive_ready"]:
        print("[锁定] 完整归档覆盖不足95%，周一不得发布严格实时特征")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
