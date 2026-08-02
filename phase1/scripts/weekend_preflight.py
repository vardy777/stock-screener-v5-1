#!/usr/bin/env python3
"""Offline preflight for the next strict forward-data collection session."""

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ROOT = BASE.parent
sys.path.insert(0, str(ROOT))

from v4.calendar import TradingCalendar
from v4.execution import CHINA_TZ
from v4.readiness import ResearchReadiness


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trade-date", default=None)
    parser.add_argument(
        "--output",
        type=Path,
        default=BASE / "data" / "overnight" / "weekend_preflight.json",
    )
    args = parser.parse_args()

    calendar = TradingCalendar()
    today = date.today()
    if args.trade_date:
        trade_date = date.fromisoformat(args.trade_date)
    elif calendar.is_open(today):
        trade_date = today
    else:
        trade_date = calendar.next_open(today)
    previous = calendar.previous_open(trade_date) if trade_date else None

    context_path = BASE / "data" / "overnight" / "live_feature_context.csv.gz"
    context_meta = _load(context_path.with_suffix(context_path.suffix + ".meta.json"))
    archive_meta = _load(BASE / "data" / "overnight" / "archive_refresh_report.json")
    labels_path = BASE / "data" / "overnight" / "execution_labels.csv.gz"
    labels_meta = _load(labels_path.with_suffix(labels_path.suffix + ".meta.json"))
    readiness = ResearchReadiness().evaluate()

    trade_date_open = bool(trade_date and calendar.is_open(trade_date) is True)
    context_matches = bool(
        previous
        and context_meta.get("expected_previous_session") == previous.isoformat()
    )
    volume_unit_verified = bool(
        context_meta.get("volume_unit") == "shares"
        and context_meta.get("volume_unit_verified", False)
    )
    context_ready = bool(
        context_meta.get("strict_context_ready")
        and context_matches
        and volume_unit_verified
    )
    capture_ready = bool(trade_date_open and calendar.verified and context_ready)
    report = {
        "generated_at": datetime.now(CHINA_TZ).isoformat(timespec="seconds"),
        "trade_date": trade_date.isoformat() if trade_date else None,
        "previous_open_session": previous.isoformat() if previous else None,
        "calendar_verified": bool(calendar.verified),
        "trade_date_open": trade_date_open,
        "archive": archive_meta,
        "feature_context": context_meta,
        "context_matches_previous_session": context_matches,
        "volume_unit_verified": volume_unit_verified,
        "strict_capture_ready": capture_ready,
        "strict_execution_samples": {
            "paired_rows": int(labels_meta.get("paired_rows", 0)),
            "strict_feature_rate": float(labels_meta.get("strict_feature_rate", 0.0)),
            "order_book_verified_rate": float(
                labels_meta.get("order_book_verified_rate", 0.0)
            ),
            "order_book_liquidity_rate": float(
                labels_meta.get("order_book_liquidity_rate", 0.0)
            ),
            "strict_dataset_ready": bool(labels_meta.get("strict_dataset_ready", False)),
        },
        "research_status": readiness.get("status", "research_locked"),
        "trade_enabled": bool(readiness.get("trade_enabled", False)),
        "required_collection_windows": {
            "signal": "14:49:00-14:49:59",
            "buy": "14:50:00-14:51:59",
            "sell_next_open_session": "09:30:00-09:35:00",
        },
        "required_capture_contracts": {
            "minimum_full_market_coverage": 0.95,
            "maximum_quote_age_seconds": 30,
            "causal_quote_time": True,
            "buy_price_source": "ask1",
            "sell_price_source": "bid1",
            "level1_queue_must_cover_planned_shares": True,
        },
        "scheduled_health_checks": {
            "sell": "09:36",
            "signal_and_buy": "14:53",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if capture_ready:
        print("[可采集] 下一交易日严格快照链路已通过离线预检")
    else:
        print("[锁定] 下一交易日严格快照链路尚未通过离线预检")
    print("[研究门禁] 模型准入仍以 trade_enabled=false 为预期，不得自动交易")
    return 0 if capture_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
