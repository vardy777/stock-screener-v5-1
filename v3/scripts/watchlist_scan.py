#!/usr/bin/env python3
"""
V3 核心关注定时扫描推送
用途: 交易时段每30分钟扫描8只关注股 → PushPlus微信推送
调用: python v3/scripts/watchlist_scan.py
环境变量: PUSHPLUS_TOKEN
"""
import sys, os, logging

# 项目路径处理
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from v3.watchlist import scan_all, build_push_html, build_simple_text
from v3.push import send_wechat
from datetime import datetime, timezone, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
logger = logging.getLogger("watchlist_scan")

# A股使用北京时间 (UTC+8)
CST = timezone(timedelta(hours=8))


def is_trading_time() -> bool:
    """判断是否在A股连续竞价时段（09:28-11:30, 13:00-15:00）北京时间
    09:28起覆盖30分钟整点偏移，确保09:30附近那次触发不被跳过"""
    now = datetime.now(CST)
    if now.weekday() >= 5:  # 周六日
        return False
    t = now.hour * 100 + now.minute
    return (928 <= t <= 1130) or (1300 <= t <= 1500)


def main():
    now = datetime.now(CST)
    today_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")
    weekday = ["一", "二", "三", "四", "五", "六", "日"][now.weekday()]

    # 周末检查
    if now.weekday() >= 5:
        logger.info(f"周末休市 ({today_str} 周{weekday})，跳过")
        return

    # 交易时段检查
    if not is_trading_time():
        t = now.hour * 100 + now.minute
        logger.info(f"非交易时段 ({time_str})，跳过")
        return

    logger.info(f"=== 核心关注扫描开始 {today_str} {time_str} 周{weekday} ===")

    # 1. 扫描8股
    results = scan_all()

    # 1.5 写入缓存（看板秒读）
    from v3.watchlist_cache import save_cache
    save_cache(results)

    # 2. 构建内容
    html = build_push_html(results)
    text = build_simple_text(results)

    # 3. 发送微信推送
    title = f"📊 关注扫描 {time_str} 周{weekday}"

    # 标记时段类型
    t = now.hour * 100 + now.minute
    if t <= 930:
        title = f"🏁 开盘扫描 {time_str}"
    elif 930 <= t <= 1000:
        title = f"🌅 早盘扫描 {time_str}"
    elif 1000 <= t <= 1130:
        title = f"📊 盘中扫描 {time_str}"
    elif 1300 <= t <= 1330:
        title = f"🌤 午盘开启 {time_str}"
    elif 1430 <= t <= 1500:
        title = f"🌇 尾盘扫描 {time_str}"

    success = send_wechat(title, html)

    if success:
        logger.info("✅ 微信推送成功")
    else:
        logger.warning("❌ 推送失败，备用输出：")
        print(text)

    logger.info("=== 扫描完成 ===")


if __name__ == "__main__":
    main()
