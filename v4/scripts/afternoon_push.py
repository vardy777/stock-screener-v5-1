#!/usr/bin/env python
"""14:50真实行情选股与推送；数据失败时严格空仓。"""

import logging
import os
import sys
from datetime import datetime, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from v4.push import build_afternoon_card, send_wechat
from v4.simulation import SimulationEngine
from v4.calendar import TradingCalendar
from v4.execution import CHINA_TZ


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("afternoon_push_v4")


def _now() -> datetime:
    return datetime.now(CHINA_TZ)


def _in_window(current: datetime) -> bool:
    return time(14, 50) <= current.timetz().replace(tzinfo=None) <= time(14, 51, 59)


def main() -> int:
    current = _now()
    current_date = current.date()
    today = current_date.strftime("%Y-%m-%d")
    calendar = TradingCalendar()
    if calendar.is_open(current_date) is not True:
        logger.info("非开放交易日，跳过尾盘推送: %s", today)
        return 0
    if not _in_window(current):
        logger.error("不在14:50-14:51:59买入确认窗口，拒绝迟到推送: %s", current.isoformat())
        return 3
    logger.info("=== V4 14:50尾盘确认 %s ===", today)

    engine = SimulationEngine()
    engine.load_state()
    candidates = engine.screen_today(stage="confirmation")
    market_state = engine._get_market_state()
    positions = engine.positions

    if any(candidate.get("is_mock") for candidate in candidates):
        logger.error("检测到模拟候选，拒绝推送")
        return 2
    if any(candidate.get("v4_candidate_origin") != "V4" for candidate in candidates):
        logger.error("检测到非V4来源候选，拒绝推送")
        return 2
    if not candidates:
        logger.warning("无真实候选或行情不可用，今日空仓")

    card = build_afternoon_card(candidates[:3], market_state, positions)
    sent = send_wechat(
        f"🎯 V4独立 14:50尾盘确认 {today}",
        card,
        message_key=f"v4-afternoon:{today}",
    )
    if sent is False:
        logger.error("推送失败")
        return 1
    logger.info("真实候选 %d 只，推送完成", len(candidates[:3]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
