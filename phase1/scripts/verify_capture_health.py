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
from v4.push import send_wechat
from v4.calendar import TradingCalendar
from v4.execution import CHINA_TZ
from v4.snapshot_compat import build_daily_quality_report
from v4.p2_acceptance import validate_p2_session
from v4.candidate_journal import CandidateJournal


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trade-date", default=date.today().isoformat())
    parser.add_argument("--sessions", default="signal,buy,sell")
    parser.add_argument("--notify-failure", action="store_true")
    args = parser.parse_args()
    sessions = [value.strip() for value in args.sessions.split(",") if value.strip()]
    if not sessions or any(value not in {"signal", "buy", "sell"} for value in sessions):
        print("sessions 必须是 signal、buy、sell 的组合")
        return 2
    try:
        trade_day = date.fromisoformat(args.trade_date)
    except ValueError:
        print("trade-date 必须是YYYY-MM-DD")
        return 2
    if TradingCalendar().is_open(trade_day) is not True:
        print(f"非开放交易日，跳过采集健康检查: {args.trade_date}")
        return 0
    root = BASE / "data" / "execution_snapshots"
    chain=CandidateJournal().load(args.trade_date)
    morning_count=len(chain.get("morning",{}).get("candidates",[]))
    checks=[]
    for session in sessions:
        if session=="buy" and morning_count==0:
            checks.append({"session":"buy","trade_date":args.trade_date,"passed":True,
                           "status":"NOT_APPLICABLE_EMPTY_MORNING_POOL","files_found":0,"best":{},"candidates":[]})
        else:
            checks.append(evaluate_capture_session(root,session,args.trade_date))
    p2_acceptance = None
    if {"signal", "buy"}.issubset(sessions):
        p2_acceptance = validate_p2_session(
            args.trade_date,
            journal_dir=ROOT / "v4" / "data" / "candidate_journal",
            log_dir=BASE / "data" / "logs",
        )
    overall_passed = bool(
        all(check["passed"] for check in checks)
        and (p2_acceptance is None or p2_acceptance["passed"])
    )
    report = {
        "contract_version": "strict-capture-health-v1",
        "generated_at": datetime.now(CHINA_TZ).isoformat(timespec="seconds"),
        "trade_date": args.trade_date,
        "sessions": sessions,
        "passed": overall_passed,
        "checks": checks,
        "capture_quality": build_daily_quality_report(
            args.trade_date, root=root
        ),
        "p2_decision_acceptance": p2_acceptance,
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
    if not report["passed"] and args.notify_failure:
        failed = [check for check in checks if not check.get("passed")]
        def failure_reason(check):
            if not check.get("files_found"):
                return "未找到快照"
            best = check.get("best", {})
            failed_fields = [
                key
                for key in (
                    "schema_ok", "causal", "window_ok", "codes_ok", "names_ok",
                    "manifest_ok", "artifact_hash_ok", "order_book_ok",
                )
                if best.get(key) is False
            ]
            coverage = float(best.get("coverage", 0.0) or 0.0)
            if coverage < 0.95:
                failed_fields.append(f"coverage={coverage*100:.1f}%")
            return "、".join(failed_fields) or "产物未通过审计"
        details = "<br>".join(
            f'{check.get("session", "?")}: {failure_reason(check)}'
            for check in failed
        )
        if p2_acceptance is not None and not p2_acceptance.get("passed"):
            failed_p2 = [
                key for key, passed in p2_acceptance.get("checks", {}).items()
                if not passed
            ]
            details += (
                ("<br>" if details else "")
                + "P2决策链: " + "、".join(failed_p2)
            )
        send_wechat(
            f"⚠️ V4严格快照异常 {args.trade_date}",
            (
                "<h3>V4采集健康检查未通过</h3>"
                f"<p>日期: {args.trade_date} | 会话: {suffix}</p>"
                f"<p>{details}</p><p>系统继续保持研究锁定/空仓，不会补造样本。</p>"
            ),
            message_key=f"v4-capture-alert:{args.trade_date}:{suffix}",
        )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
