#!/usr/bin/env python
"""结算脚本 — 读取交易日志, 计算盈亏, 更新胜率, 推送微信"""
import sys, os, json, csv, logging
from datetime import datetime, date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from v3.config import DATA_DIR, PUSHPLUS_TOKEN
from v3.push import send_wechat, build_settlement_card
from v3.settlement import SettlementEngine

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s %(message)s')
logger = logging.getLogger('daily_settlement_v3')


def read_journal():
    """读取交易日志"""
    from v3.config import JOURNAL_PATH
    path = JOURNAL_PATH
    if not os.path.exists(path):
        logger.warning(f"交易日志不存在: {path}")
        return []
    with open(path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        return list(reader)


def calc_yesterday_trades(trades):
    """计算昨日已卖出的交易"""
    yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    settled = []
    for t in trades:
        trade_date = t.get('date', '')
        sell_price_str = t.get('sell_price', '0')
        try:
            sell_price = float(sell_price_str) if sell_price_str else 0
        except ValueError:
            sell_price = 0

        if trade_date == yesterday and sell_price > 0:
            try:
                buy_price = float(t.get('buy_price', 0))
                profit = round((sell_price - buy_price) / buy_price * 100, 2)
                settled.append({
                    'date': trade_date,
                    'code': t.get('code', ''),
                    'name': t.get('name', ''),
                    'buy_price': buy_price,
                    'sell_price': sell_price,
                    'profit': profit,
                })
            except (ValueError, ZeroDivisionError):
                continue
    return settled


def main():
    today = date.today().strftime("%Y-%m-%d")
    yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    logger.info(f"=== V3 每日结算 {today} (结算日: {yesterday}) ===")

    # 1. 读取交易日志
    trades = read_journal()
    if not trades:
        logger.info("无交易记录")
        engine = SettlementEngine()
        summary = engine.summary()
        card = build_settlement_card(summary)
        send_wechat(f"💰 V3 结算 {today}", card)
        logger.info("=== V3 结算完成 (空) ===")
        return

    logger.info(f"读取 {len(trades)} 条交易记录")

    # 2. 计算昨日结算
    settled = calc_yesterday_trades(trades)
    logger.info(f"昨日交易: {len(settled)} 笔")

    if not settled:
        logger.info("昨日无结算交易")
        engine = SettlementEngine()
        summary = engine.summary()
        card = build_settlement_card(summary)
        send_wechat(f"💰 V3 结算 {today}", card)
        logger.info("=== V3 结算完成 (无新交易) ===")
        return

    for t in settled:
        emoji = "✅" if t['profit'] >= 0 else "❌"
        logger.info(f"  {emoji} {t['code']} {t.get('name','')} 盈亏: {t['profit']:+.2f}%")

    # 3. 记录到 SettlementEngine
    engine = SettlementEngine()
    for t in settled:
        engine.record(
            t['code'],
            t['buy_price'],
            t['sell_price'],
            settled_on=t.get('date'),
        )

    # 4. 汇总推送
    summary = engine.summary()
    logger.info(f"累计: 交易{summary['trades']}笔 胜率{summary['win_rate']*100:.0f}% 总盈亏{summary['total_return']:+.2f}%")

    card = build_settlement_card(summary)
    send_wechat(f"💰 V3 结算 {today}", card)

    logger.info("=== V3 每日结算完成 ===")


if __name__ == "__main__":
    main()
