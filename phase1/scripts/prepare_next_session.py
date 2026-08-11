#!/usr/bin/env python3
"""Prepare strict context and research diagnostics for the next session."""

import argparse
import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ROOT = BASE.parent
sys.path.insert(0, str(ROOT))

from v4.calendar import TradingCalendar
from v4.execution import CHINA_TZ


def _load(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, TypeError, ValueError):
        return {}


def _run(script: str, *arguments: str) -> int:
    completed = subprocess.run(
        [sys.executable, str(BASE / "scripts" / script), *arguments],
        cwd=ROOT,
        check=False,
    )
    return int(completed.returncode)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--as-of",
        default=date.today().isoformat(),
        help="local session date; primarily for deterministic diagnostics",
    )
    args = parser.parse_args()
    as_of = date.fromisoformat(args.as_of)
    calendar = TradingCalendar()
    if not calendar.verified:
        print("拒绝维护: 交易日历未核验")
        return 2
    if calendar.is_open(as_of) is not True:
        print(f"非开放交易日，跳过维护: {as_of.isoformat()}")
        return 0
    next_session = calendar.next_open(as_of)
    if next_session is None:
        print("拒绝维护: 交易日历没有覆盖下一开放交易日")
        return 2

    target = next_session.isoformat()
    print(f"准备下一交易日: {target}", flush=True)
    # The legacy per-symbol Sina archive refresh is rate-limited (HTTP 456)
    # and must not block the next session's critical context.  The gateway
    # builder uses a second provider and cross-checks against today's strict
    # V4 signal snapshot before it can publish a ready context.
    context_code = _run("build_live_feature_context_gateway.py", "--trade-date", target)
    preflight_code = _run("weekend_preflight.py", "--trade-date", target)
    labels_code = _run("build_execution_labels.py")

    overnight = BASE / "data" / "overnight"
    archive = _load(overnight / "archive_refresh_report.json")
    context_path = overnight / "live_feature_context.csv.gz"
    context = _load(context_path.with_suffix(context_path.suffix + ".meta.json"))
    preflight = _load(overnight / "weekend_preflight.json")
    labels_path = overnight / "execution_labels.csv.gz"
    labels = _load(labels_path.with_suffix(labels_path.suffix + ".meta.json"))
    passed = bool(
        context.get("expected_previous_session") == as_of.isoformat()
        and context.get("strict_context_ready", False)
        and context.get("volume_unit") == "shares"
        and context.get("volume_unit_verified", False)
        and preflight.get("trade_date") == target
        and preflight.get("strict_capture_ready", False)
        and context_code == 0
        and preflight_code == 0
        and labels_code == 0
    )
    report = {
        "contract_version": "next-session-maintenance-v2",
        "generated_at": datetime.now(CHINA_TZ).isoformat(timespec="seconds"),
        "as_of_open_session": as_of.isoformat(),
        "next_open_session": target,
        "passed": passed,
        "command_exit_codes": {
            "refresh_archive": "deferred_noncritical",
            "build_context": context_code,
            "preflight": preflight_code,
            "build_labels": labels_code,
        },
        "archive": archive,
        "historical_archive_refresh_deferred": True,
        "feature_context": context,
        "preflight": {
            "strict_capture_ready": bool(
                preflight.get("strict_capture_ready", False)
            ),
            "research_status": preflight.get("research_status"),
            "trade_enabled": bool(preflight.get("trade_enabled", False)),
        },
        "execution_labels": {
            "paired_rows": int(labels.get("paired_rows", 0)),
            "strict_dataset_ready": bool(
                labels.get("strict_dataset_ready", False)
            ),
        },
        "model_training_or_publication_performed": False,
        "trade_action_performed": False,
    }
    output = overnight / "daily_maintenance_report.json"
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"已保存: {output}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
