#!/usr/bin/env python
"""
push_settlement.py — 09:30运行, 结算昨日交易
读取昨日卖出记录
计算每笔盈亏
更新 win_rate_data.json
通过 PushPlus 推送结算报告
"""
import sys, os, json, csv, logging
from datetime import datetime, date, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from v2.config import DATA_DIR, JOURNAL_PATH, WIN_RATE_DATA, PUSHPLUS_TOKEN

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s %(message)s')
logger = logging.getLogger('push_settlement')


def read_journal():
    """读取交易日志"""
    if not os.path.exists(JOURNAL_PATH):
        logger.warning(f"交易日志不存在: {JOURNAL_PATH}")
        return []
    with open(JOURNAL_PATH, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader)


def calc_yesterday_settlement(trades):
    """计算昨日已结算(卖出)的交易"""
    yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    settled = []
    for t in trades:
        trade_date = t.get("date", "")
        sell_price_str = t.get("sell_price", "0")
        try:
            sell_price = float(sell_price_str) if sell_price_str else 0
        except ValueError:
            sell_price = 0

        if trade_date == yesterday and sell_price > 0:
            try:
                buy_price = float(t.get("buy_price", 0))
                profit_pct = float(t.get("profit_pct", 0)) if t.get("profit_pct") else round((sell_price - buy_price) / buy_price * 100, 2)
                settled.append({
                    "trade_id": t.get("trade_id", ""),
                    "code": t.get("code", ""),
                    "name": t.get("name", ""),
                    "buy_price": buy_price,
                    "sell_price": sell_price,
                    "profit_pct": profit_pct,
                    "sell_reason": t.get("sell_reason", ""),
                    "buy_time": t.get("buy_time", ""),
                    "sell_time": t.get("sell_time", ""),
                })
            except (ValueError, ZeroDivisionError):
                continue
    return settled


def update_win_rate(settled_trades):
    """更新 win_rate_data.json"""
    wins = [t for t in settled_trades if t["profit_pct"] > 0]
    losses = [t for t in settled_trades if t["profit_pct"] <= 0]

    total = len(settled_trades)
    win_count = len(wins)
    win_rate = round(win_count / total * 100, 1) if total > 0 else 0
    avg_profit = round(sum(t["profit_pct"] for t in settled_trades) / total, 2) if total > 0 else 0
    avg_win = round(sum(t["profit_pct"] for t in wins) / win_count, 2) if win_count > 0 else 0
    avg_loss = round(sum(t["profit_pct"] for t in losses) / len(losses), 2) if losses else 0
    max_win = max((t["profit_pct"] for t in settled_trades), default=0)
    max_loss = min((t["profit_pct"] for t in settled_trades), default=0)

    today = date.today().strftime("%Y-%m-%d")

    # 读取历史数据
    history = []
    if os.path.exists(WIN_RATE_DATA):
        try:
            with open(WIN_RATE_DATA, "r") as f:
                existing = json.load(f)
                history = existing.get("history", [])
        except Exception:
            pass

    daily_record = {
        "date": today,
        "total": total,
        "wins": win_count,
        "losses": len(losses),
        "win_rate": win_rate,
        "avg_profit": avg_profit,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "max_win": max_win,
        "max_loss": max_loss,
    }
    history.append(daily_record)
    # 只保留最近90天
    history = history[-90:]

    # 计算累计统计
    all_wins = sum(r["wins"] for r in history)
    all_losses = sum(r["losses"] for r in history)
    all_total = all_wins + all_losses
    cumulative = {
        "total_trades": all_total,
        "win_trades": all_wins,
        "loss_trades": all_losses,
        "win_rate": round(all_wins / all_total * 100, 1) if all_total > 0 else 0,
        "total_profit": round(sum(r["avg_profit"] * r["total"] for r in history), 2),
    }

    win_rate_data = {
        "today": daily_record,
        "cumulative": cumulative,
        "history": history,
        "updated_at": datetime.now().isoformat(),
    }

    with open(WIN_RATE_DATA, "w", encoding="utf-8") as f:
        json.dump(win_rate_data, f, ensure_ascii=False, indent=2)

    logger.info(f"胜率数据已更新: {win_rate_data['cumulative']}")
    return win_rate_data


def push_to_wechat(title, content):
    if not PUSHPLUS_TOKEN:
        logger.warning("PUSHPLUS_TOKEN 未设置, 跳过推送")
        return
    import urllib.request
    import urllib.parse
    data = urllib.parse.urlencode({
        "token": PUSHPLUS_TOKEN,
        "title": title,
        "content": content,
        "template": "html",
    }).encode()
    url = "https://pushplus.plus/send"
    try:
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = resp.read().decode()
            logger.info(f"PushPlus 推送结果: {result}")
    except Exception as e:
        logger.error(f"PushPlus 推送失败: {e}")


def generate_html_report(win_rate_data):
    """生成结算 HTML 报告"""
    today_data = win_rate_data.get("today", {})
    cumulative = win_rate_data.get("cumulative", {})
    history = win_rate_data.get("history", [])
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 最近5天趋势
    recent = history[-5:] if len(history) >= 5 else history
    trend_rows = ""
    for r in recent:
        emoji = "🟢" if r.get("win_rate", 0) >= 50 else "🔴"
        trend_rows += f"""
        <tr>
            <td>{r.get('date','')}</td>
            <td>{r.get('total',0)}</td>
            <td>{r.get('wins',0)}/{r.get('losses',0)}</td>
            <td>{emoji} {r.get('win_rate',0):.1f}%</td>
            <td class="{'pos' if r.get('avg_profit',0)>=0 else 'neg'}">{r.get('avg_profit',0):+.2f}%</td>
        </tr>"""

    td = today_data
    emoji_total = "🟢" if td.get("win_rate", 0) >= 50 else "🔴"
    html = f"""
    <html>
    <head><meta charset="utf-8"><style>
        body {{ font-family: 'Microsoft YaHei', sans-serif; background: #1a1a2e; color: #eee; padding: 16px; }}
        h2 {{ color: #e94560; border-bottom: 2px solid #e94560; padding-bottom: 8px; }}
        h3 {{ color: #4ecca3; }}
        table {{ width: 100%; border-collapse: collapse; margin: 12px 0; }}
        th {{ background: #16213e; color: #0f3460; padding: 8px; text-align: left; }}
        td {{ padding: 8px; border-bottom: 1px solid #333; }}
        .pos {{ color: #ff6b6b; }}
        .neg {{ color: #4ecca3; }}
        .summary {{ background: #16213e; border-radius: 8px; padding: 12px; margin: 8px 0; }}
    </style></head>
    <body>
        <h2>📊 交易结算报告</h2>
        <p>⏰ {now}</p>
        <div class="summary">
            <p><b>昨日交易:</b> {td.get('total',0)} 笔 | {emoji_total} 胜率 {td.get('win_rate',0):.1f}%</p>
            <p><b>盈利:</b> {td.get('wins',0)} 笔 | <b>亏损:</b> {td.get('losses',0)} 笔</p>
            <p><b>平均收益:</b> <span class="{'pos' if td.get('avg_profit',0)>=0 else 'neg'}">{td.get('avg_profit',0):+.2f}%</span></p>
            <p><b>平均盈利:</b> <span class="pos">{td.get('avg_win',0):+.2f}%</span> | <b>平均亏损:</b> <span class="neg">{td.get('avg_loss',0):+.2f}%</span></p>
            <p><b>最大盈利:</b> <span class="pos">{td.get('max_win',0):+.2f}%</span> | <b>最大亏损:</b> <span class="neg">{td.get('max_loss',0):+.2f}%</span></p>
        </div>
        <h3>📈 累计统计</h3>
        <div class="summary">
            <p><b>总交易:</b> {cumulative.get('total_trades',0)} 笔</p>
            <p><b>累计胜率:</b> {cumulative.get('win_rate',0):.1f}%</p>
            <p><b>累计收益:</b> <span class="{'pos' if cumulative.get('total_profit',0)>=0 else 'neg'}">{cumulative.get('total_profit',0):+.2f}%</span></p>
        </div>
        <h3>📉 近5日趋势</h3>
        <table>
            <tr><th>日期</th><th>笔数</th><th>胜/负</th><th>胜率</th><th>平均收益</th></tr>
            {trend_rows}
        </table>
    </body>
    </html>"""
    return html


def main():
    today = date.today().strftime("%Y-%m-%d")
    yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    logger.info(f"=== 结算推送 {today} (昨日: {yesterday}) ===")

    # 1. 读取交易日志
    trades = read_journal()
    if not trades:
        logger.info("无交易记录, 生成空报告")
        win_rate_data = {
            "today": {"date": today, "total": 0, "wins": 0, "losses": 0,
                      "win_rate": 0, "avg_profit": 0, "avg_win": 0, "avg_loss": 0, "max_win": 0, "max_loss": 0},
            "cumulative": {"total_trades": 0, "win_trades": 0, "loss_trades": 0, "win_rate": 0, "total_profit": 0},
            "history": [],
            "updated_at": datetime.now().isoformat(),
        }
    else:
        logger.info(f"读取 {len(trades)} 条交易记录")

        # 2. 计算昨日结算
        settled = calc_yesterday_settlement(trades)
        logger.info(f"昨日结算: {len(settled)} 笔")

        for t in settled:
            emoji = "✅" if t["profit_pct"] >= 0 else "❌"
            logger.info(f"  {emoji} {t['code']} {t['name']} 盈亏: {t['profit_pct']:+.2f}%")

        # 3. 更新胜率数据
        win_rate_data = update_win_rate(settled)

    # 4. PushPlus 推送
    html = generate_html_report(win_rate_data)
    push_to_wechat(f"📊 交易结算 {today}", html)

    logger.info("=== 结算推送完成 ===")


if __name__ == "__main__":
    main()
