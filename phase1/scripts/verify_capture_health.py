#!/usr/bin/env python3
"""Verify that scheduled strict captures produced auditable artifacts."""

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ROOT = BASE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BASE))

from overnight.capture_health import evaluate_capture_session
from v4.execution import CHINA_TZ


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trade-date", default=date.today().isoformat())
    parser.add_argument("--sessions", default="signal,buy,sell")
    args = parser.parse_args()
    sessions = [value.strip() for value in args.sessions.split(",") if value.strip()]
    if not sessions or any(value not in {"signal", "buy", "sell"} for value in sessions):
        print("sessions 必须是 signal、buy、sell 的组合")
        return 2
    root = BASE / "data" / "execution_snapshots"
    checks = [
        evaluate_capture_session(root, session, args.trade_date)
        for session in sessions
    ]
    report = {
        "contract_version": "strict-capture-health-v1",
        "generated_at": datetime.now(CHINA_TZ).isoformat(timespec="seconds"),
        "trade_date": args.trade_date,
        "sessions": sessions,
        "passed": all(check["passed"] for check in checks),
        "checks": checks,
    }
    output_dir = root / "health"
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = "_".join(sessions)
    output = output_dir / f"{args.trade_date}_{suffix}.json"
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"已保存: {output}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
