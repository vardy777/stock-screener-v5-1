#!/usr/bin/env python
"""09:25早盘观察候选；尾盘前必须重新确认，绝不在早盘买入。"""

import logging
import os
import sys
from datetime import datetime, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from v3.push import build_morning_card, send_wechat
from v3.simulation import SimulationEngine
from v4.calendar import TradingCalendar
from v4.execution import CHINA_TZ


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("morning_push_v3")


def _now() -> datetime:
    return datetime.now(CHINA_TZ)


def _in_window(current: datetime) -> bool:
    return time(9, 20) <= current.timetz().replace(tzinfo=None) <= time(9, 29, 59)


def main() -> int:
    current = _now()
    current_date = current.date()
    today = current_date.strftime("%Y-%m-%d")
    calendar = TradingCalendar()
    if calendar.is_open(current_date) is not True:
        logger.info("非开放交易日，跳过早盘推送: %s", today)
        return 0
    if not _in_window(current):
        logger.error("不在09:20-09:29早盘推送有效窗口，拒绝迟到推送: %s", current.isoformat())
        return 3
    engine = SimulationEngine()
    engine.load_state()
    candidates = engine.screen_today()
    market_state = engine._get_market_state()
    positions = engine.positions
    if any(candidate.get("is_mock") for candidate in candidates):
        logger.error("检测到模拟候选，拒绝推送")
        return 2
    card = build_morning_card(candidates[:5], market_state, positions)
    sent = send_wechat(
        f"🌅 V4 早盘观察池 {today}",
        card,
        message_key=f"v4-morning:{today}",
    )
    logger.info("早盘候选 %d 只，待卖持仓 %d 只", len(candidates[:5]), len(positions))
    return 0 if sent is not False else 1


if __name__ == "__main__":
    raise SystemExit(main())
