"""
交易日志模块
记录每笔交易并生成复盘统计
"""

import pandas as pd
import os
import logging
from datetime import datetime, date
import json

from config import JOURNAL_PATH, RISK_CONTROL

logger = logging.getLogger(__name__)


# ============================================================
# 交易记录
# ============================================================

def init_journal():
    """初始化交易日志文件，确保正确的列类型"""
    if not os.path.exists(JOURNAL_PATH):
        df = pd.DataFrame({
            "trade_id": pd.Series(dtype=str),
            "date": pd.Series(dtype=str),
            "code": pd.Series(dtype=str),
            "name": pd.Series(dtype=str),
            "buy_time": pd.Series(dtype=str),
            "buy_price": pd.Series(dtype=float),
            "buy_reason": pd.Series(dtype=str),
            "sell_time": pd.Series(dtype=str),
            "sell_price": pd.Series(dtype=float),
            "sell_reason": pd.Series(dtype=str),
            "change_pct": pd.Series(dtype=float),
            "profit_pct": pd.Series(dtype=float),
            "notes": pd.Series(dtype=str),
            "rating": pd.Series(dtype=int),
        })
        df.to_csv(JOURNAL_PATH, index=False, encoding="utf-8-sig")
        logger.info(f"新建交易日志: {JOURNAL_PATH}")
        return df
    
    df = pd.read_csv(JOURNAL_PATH, encoding="utf-8-sig",
                     dtype={"trade_id": str, "date": str, "code": str, "name": str,
                            "buy_time": str, "buy_price": float, "buy_reason": str,
                            "sell_time": str, "sell_price": float, "sell_reason": str,
                            "change_pct": float, "profit_pct": float, "notes": str,
                            "rating": int})
    # 字符串列 NaN 变空
    for col in ["trade_id", "date", "code", "name", "buy_time", "buy_reason",
                "sell_time", "sell_reason", "notes"]:
        df[col] = df[col].fillna("")
    return df


def record_buy(code, name, buy_price, buy_reason="", buy_time=None):
    """
    记录买入
    返回 trade_id
    """
    df = init_journal()
    today = date.today().strftime("%Y-%m-%d")
    if buy_time is None:
        buy_time = datetime.now().strftime("%H:%M")
    
    # 生成交易 ID
    trade_id = f"{today}_{code}_{datetime.now().strftime('%H%M%S')}"
    
    new_row = pd.DataFrame([{
        "trade_id": trade_id,
        "date": today,
        "code": code,
        "name": name,
        "buy_time": buy_time,
        "buy_price": buy_price,
        "buy_reason": buy_reason,
        "sell_time": "",
        "sell_price": 0,
        "sell_reason": "",
        "change_pct": 0,
        "profit_pct": 0,
        "notes": "",
        "rating": 0,
    }])
    
    df = pd.concat([df, new_row], ignore_index=True)
    df.to_csv(JOURNAL_PATH, index=False, encoding="utf-8-sig")
    
    print(f"  📝 已记录买入: {code} {name} @ {buy_price:.2f}")
    return trade_id


def record_sell(code, sell_price, sell_reason="", profit_pct=None):
    """
    记录卖出（根据最新一笔未卖出的记录）
    """
    df = init_journal()
    
    # 找到该股票最新一笔未卖出的记录
    mask = (df["code"].astype(str).str.strip() == str(code).strip()) & ((df["sell_price"] == 0) | df["sell_price"].isna())
    if mask.sum() == 0:
        logger.warning(f"未找到 {code} 的未卖出记录")
        return False
    
    # 取最新一笔
    idx = df[mask].index[-1]
    sell_time = datetime.now().strftime("%H:%M")
    today = date.today().strftime("%Y-%m-%d")
    
    buy_price = float(df.loc[idx, "buy_price"])
    
    # 计算盈亏
    if profit_pct is None:
        profit_pct = round((sell_price - buy_price) / buy_price * 100, 2)
    
    df.loc[idx, "sell_time"] = sell_time
    df.loc[idx, "sell_price"] = sell_price
    df.loc[idx, "sell_reason"] = sell_reason
    df.loc[idx, "profit_pct"] = profit_pct
    df.loc[idx, "date"] = today  # 更新日期为实际卖出日期
    
    df.to_csv(JOURNAL_PATH, index=False, encoding="utf-8-sig")
    
    emoji = "✅" if profit_pct >= 0 else "❌"
    print(f"  {emoji} 已记录卖出: {code} @ {sell_price:.2f} | 盈亏: {profit_pct:+.2f}%")
    return True


# ============================================================
# 复盘分析
# ============================================================

def review_period(days=30):
    """
    复盘分析最近 N 天的交易
    返回 统计 dict
    """
    df = init_journal()
    if len(df) == 0:
        print("📭 暂无交易记录")
        return {}
    
    # 过滤最近 N 天
    df = df[df["date"] >= (date.today() - pd.Timedelta(days=days)).strftime("%Y-%m-%d")]
    
    # 只统计已经卖出的
    closed = df[(df["sell_price"] > 0) | (df["profit_pct"] != 0)]
    
    if len(closed) == 0:
        print("📭 最近无已完结交易")
        return {}
    
    wins = closed[closed["profit_pct"] > 0]
    losses = closed[closed["profit_pct"] <= 0]
    
    stats = {
        "total_trades": len(closed),
        "win_trades": len(wins),
        "loss_trades": len(losses),
        "win_rate": round(len(wins) / len(closed) * 100, 1),
        "avg_profit": round(closed["profit_pct"].mean(), 2),
        "avg_win": round(wins["profit_pct"].mean(), 2) if len(wins) > 0 else 0,
        "avg_loss": round(losses["profit_pct"].mean(), 2) if len(losses) > 0 else 0,
        "max_win": round(closed["profit_pct"].max(), 2),
        "max_loss": round(closed["profit_pct"].min(), 2),
        "total_profit": round(closed["profit_pct"].sum(), 2),
        "days_span": days,
    }
    
    # 盈亏比
    avg_win = abs(stats["avg_win"]) if stats["avg_win"] != 0 else 0
    avg_loss = abs(stats["avg_loss"]) if stats["avg_loss"] != 0 else 1
    stats["profit_loss_ratio"] = round(avg_win / avg_loss, 2) if avg_loss > 0 else 0
    
    # 打印报告
    print(f"\n{'='*50}")
    print(f"  📊 交易复盘 ({days}天)")
    print(f"{'='*50}")
    print(f"  总交易: {stats['total_trades']} 笔")
    print(f"  盈利: {stats['win_trades']} 笔 | 亏损: {stats['loss_trades']} 笔")
    print(f"  胜率: {stats['win_rate']}%")
    print(f"  平均收益: {stats['avg_profit']:+.2f}%")
    print(f"  平均盈利: {stats['avg_win']:+.2f}% | 平均亏损: {stats['avg_loss']:+.2f}%")
    print(f"  盈亏比: {stats['profit_loss_ratio']}")
    print(f"  最大盈利: {stats['max_win']:+.2f}% | 最大亏损: {stats['max_loss']:+.2f}%")
    print(f"  累计收益: {stats['total_profit']:+.2f}%")
    print(f"{'='*50}")
    
    # 建议
    if stats["win_rate"] >= 55 and stats["profit_loss_ratio"] >= 1.5:
        print("  🎉 策略有效，继续执行！")
    elif stats["win_rate"] >= 50:
        print("  🔧 胜率尚可，但需要优化盈亏比")
    else:
        print("  ⚠️  需要调整选股条件，减少亏损单")
    
    return stats


def show_pending_trades():
    """显示当前持仓（已买入未卖出的）"""
    df = init_journal()
    pending = df[(df["sell_price"].isna()) | (df["sell_price"] == 0)]
    
    if len(pending) == 0:
        print("📭 当前无持仓")
        return pending
    
    print(f"\n📋 当前持仓: {len(pending)} 只")
    print("-" * 50)
    for _, row in pending.iterrows():
        print(f"  {row['code']} {row['name']} | 买入: {row['buy_price']:.2f} @ {row['buy_time']} | 理由: {row['buy_reason']}")
    
    return pending


def export_journal(format="csv"):
    """导出交易日志"""
    if format == "csv":
        print(f"📄 交易日志位置: {JOURNAL_PATH}")
        return JOURNAL_PATH
    return JOURNAL_PATH


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # 测试
    review_period(30)
    show_pending_trades()
