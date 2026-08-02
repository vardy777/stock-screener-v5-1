#!/usr/bin/env python3
"""Capture real 14:50 or 09:30 quotes for forward validation.

The free historical archive cannot backfill exact 14:50 executions. Running
this script every trading day creates a clean, non-mock point-in-time archive
that can later replace the 15:00 proxy.
"""

import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ROOT = BASE.parent
sys.path.insert(0, str(ROOT))

from v3.data import DataFetcher
from phase1.overnight.quote_capture import fetch_quotes_with_retries
from v4.execution import TradingClock
from v4.snapshots import capture_frame


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("session", choices=["buy", "sell"])
    parser.add_argument(
        "--allow-outside-window",
        action="store_true",
        help="仅用于人工诊断；定时任务不应使用",
    )
    args = parser.parse_args()

    started_at = TradingClock.now()
    status = TradingClock.action_status(args.session, now=started_at)
    if not args.allow_outside_window and not status.allowed:
        print(f"拒绝采集: {status.reason}")
        return 2

    codes = sorted(
        path.stem.zfill(6)
        for path in (BASE / "data" / "daily").glob("*.csv")
        if not path.stem.startswith(("688", "8", "4"))
    )
    quotes, fetch_report = fetch_quotes_with_retries(
        DataFetcher(),
        codes,
        args.session,
        minimum_coverage=0.95,
        maximum_attempts=3,
        require_window=not args.allow_outside_window,
    )
    if quotes is None or quotes.empty:
        print("行情为空；未写入任何快照")
        return 1

    if status.allowed:
        captured_at = TradingClock.now()
        completed_status = TradingClock.action_status(args.session, now=captured_at)
        if not completed_status.allowed:
            print("行情抓取完成时已离开严格执行窗口；未写入快照")
            return 2
        output = capture_frame(
            quotes,
            args.session,
            now=captured_at,
            expected_codes=codes,
            minimum_coverage=0.95,
            capture_metadata=fetch_report,
            require_order_book=True,
        )
        if output is None:
            print("行情覆盖不足95%、时间戳不新鲜或价格无效；未写入严格快照")
            return 1
        print(
            f"严格执行窗口快照已保存: {output} | "
            f"行情覆盖率{fetch_report['quote_coverage']*100:.2f}% | "
            f"抓取{fetch_report['attempt_count']}次"
        )
        return 0

    # Manual diagnostics must never contaminate the strict execution archive.
    diagnostic = quotes.copy()
    captured_at = TradingClock.now()
    diagnostic["captured_at"] = captured_at.isoformat(timespec="seconds")
    diagnostic["session"] = f"diagnostic_{args.session}"
    diagnostic["window_valid"] = False
    output_dir = BASE / "data" / "execution_snapshots" / "diagnostic" / args.session
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{captured_at:%Y-%m-%d_%H%M%S}.csv"
    temporary = output.with_suffix(output.suffix + ".tmp")
    diagnostic.to_csv(temporary, index=False)
    temporary.replace(output)
    manifest = {
        "contract_version": "diagnostic-quote-snapshot-v1",
        "captured_at": captured_at.isoformat(timespec="seconds"),
        "strict_sample": False,
        "window_valid": False,
        "fetch": fetch_report,
    }
    manifest_path = output.with_suffix(output.suffix + ".meta.json")
    manifest_temporary = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    manifest_temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    manifest_temporary.replace(manifest_path)
    print(
        f"窗口外诊断行情已隔离保存，不计入严格样本: {output} | "
        f"接口覆盖率{fetch_report['quote_coverage']*100:.2f}%"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
