#!/usr/bin/env python
"""14:50真实行情选股与推送；数据失败时严格空仓。"""

import logging
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from v3.push import build_afternoon_card, send_wechat
from v3.simulation import SimulationEngine
from v4.calendar import TradingCalendar


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("afternoon_push_v3")


def main() -> int:
    current_date = date.today()
    today = current_date.strftime("%Y-%m-%d")
    calendar = TradingCalendar()
    if calendar.is_open(current_date) is not True:
        logger.info("非开放交易日，跳过尾盘推送: %s", today)
        return 2
    logger.info("=== V4 14:50尾盘确认 %s ===", today)

    engine = SimulationEngine()
    engine.load_state()
    candidates = engine.screen_today()
    market_state = engine._get_market_state()
    positions = engine.positions

    if any(candidate.get("is_mock") for candidate in candidates):
        logger.error("检测到模拟候选，拒绝推送")
        return 2
    if not candidates:
        logger.warning("无真实候选或行情不可用，今日空仓")

    card = build_afternoon_card(candidates[:3], market_state, positions)
    sent = send_wechat(f"🎯 V4 14:50尾盘确认 {today}", card)
    if sent is False:
        logger.error("推送失败")
        return 1
    logger.info("真实候选 %d 只，推送完成", len(candidates[:3]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
