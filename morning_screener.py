"""
早盘选股池筛选模块 v2.0
新增 Phase 1 因子:
  - MA 多头排列
  - MACD 金叉/方向
  - 技术面综合评分
  - 昨日涨停溢价
  - 市场情绪
"""

import pandas as pd
import logging
from datetime import datetime

from config import MORNING_FILTERS, TECHNICAL_FILTERS, CAPITAL_FILTERS, SCORING_WEIGHTS
from data_fetcher import (
    fetch_top_stocks, get_market_summary,
    fetch_limit_up_stocks, get_market_sentiment
)
from technical import (
    batch_fetch_kline, score_technical,
    check_bullish_alignment, check_macd_golden
)
from fund_flow import batch_fetch_money_flow, calculate_capital_score

logger = logging.getLogger(__name__)


def morning_screen():
    """
    早盘选股主流程 v2.0
    """
    print("=" * 60)
    print("  🔍 早盘选股池筛选 v2.0")
    print(f"  ⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    
    # 1. 大盘环境
    market = get_market_summary()
    mood = market.get("market_mood", "震荡")
    print(f"\n📊 大盘: {mood} | 上证 {market.get('sh_index','N/A')}% | 创业板 {market.get('cyb_index','N/A')}%")
    
    if mood == "危险":
        print("  🚨 大盘危险，建议空仓！")
        return None, [], market
    
    # 2. 市场情绪
    sentiment = get_market_sentiment()
    print(f"🔥 市场情绪: 涨停 {sentiment.get('zt_count',0)} 只")
    
    min_zt = TECHNICAL_FILTERS["min_zt_count"]
    if sentiment.get("zt_count", 0) < min_zt:
        print(f"  ⚠️ 涨停数 < {min_zt}，市场偏弱")
    
    # 3. 上周涨停股票
    limit_ups = fetch_limit_up_stocks()
    limit_codes = set(s["code"] for s in limit_ups)
    print(f"🏆 今日涨停(≥9.5%): {len(limit_ups)} 只")
    
    # 4. 获取全市场行情
    print(f"\n📡 获取行情数据...")
    df = fetch_top_stocks(limit=200)
    if df is None or len(df) == 0:
        print("❌ 获取行情失败")
        return None, [], market
    
    print(f"✅ 获取 {len(df)} 只股票")
    
    # 5. 基础筛选
    df = apply_morning_filters(df)
    if df is None or len(df) == 0:
        print("❌ 基础筛选后无候选股")
        return None, [], market
    
    candidate_codes = df["code"].tolist()
    print(f"📋 基础筛选: {len(candidate_codes)} 只候选")
    
    # 6. 获取 K 线 + 技术面评分
    print(f"📈 获取技术面数据 ({len(candidate_codes)} 只)...")
    klines = batch_fetch_kline(candidate_codes, days=60)
    
    # 7. 获取资金流数据 (Phase 2 NEW)
    print(f"💰 获取资金流数据 ({len(candidate_codes)} 只)...")
    money_flows = batch_fetch_money_flow(candidate_codes)
    
    # 7. 综合评分 (Phase 2: 加入资金流)
    results = []
    for _, row in df.iterrows():
        code = str(row["code"])
        kline = klines.get(code)
        mf = money_flows.get(code, {})
        
        stock = {
            "code": code,
            "name": str(row.get("name", "")),
            "price": float(row.get("price", 0)),
            "change_pct": float(row.get("change_pct", 0)),
            "amount": float(row.get("amount", 0) or 0),
            "close_position": float(row.get("close_position", 0) or 0),
        }
        
        stock["is_limit_up"] = code in limit_codes
        
        # 技术面评分
        if kline:
            tech = score_technical(kline)
            stock["tech_score"] = tech["score"]
            stock["tech_reason"] = tech["reasons"]
            ok_ma, msg_ma = check_bullish_alignment(kline)
            stock["ma_bullish"] = ok_ma
            stock["ma_msg"] = msg_ma
            macd_ok = False
            if len(kline) >= 26:
                macd_ok, msg_macd = check_macd_golden(kline)
            stock["macd_golden"] = macd_ok
        else:
            stock["tech_score"] = 0
            stock["ma_bullish"] = False
            stock["macd_golden"] = False
            stock["tech_reason"] = "无K线"
        
        # 资金流评分 (Phase 2 NEW)
        cap = calculate_capital_score(mf, kline)
        stock["capital_score"] = cap["capital_score"]
        stock["main_net"] = cap["main_net"]
        stock["main_ratio"] = cap["main_ratio"]
        stock["capital_reason"] = cap["money_flow_reason"]
        
        # 综合评分 (加权)
        w = SCORING_WEIGHTS
        stock["final_score"] = (
            stock["tech_score"] * w["tech_score"] +
            stock["capital_score"] * w["capital_score"] +
            stock["close_position"] * 100 * w["close_position"] +
            abs(stock["change_pct"]) * w["change_pct"] * 2 +
            (10 * w["macd_bonus"] if stock.get("macd_golden") else 0) +
            (10 * w["ma_bonus"] if stock.get("ma_bullish") else 0)
        )
        
        results.append(stock)
    
    # 过滤：资金流太差的剔除
    min_main = CAPITAL_FILTERS["min_main_net"]
    results = [r for r in results if r["main_net"] >= min_main]
    
    results.sort(key=lambda r: r["final_score"], reverse=True)

    # 8. 输出
    print(f"\n{'='*90}")
    print(f"  🎯 早盘观察池 (Phase 2 综合评分)")
    print(f"{'='*90}")
    print(f"{'代码':>8} {'名称':<8} {'涨幅':>7} {'技术分':>6} {'资金分':>6} {'主力万':>8} {'均线':>6} {'MACD':>6} {'总分':>7}")
    print(f"{'-'*8} {'-':-<8} {'-':-<7} {'-':-<6} {'-':-<6} {'-':-<8} {'-':-<6} {'-':-<6} {'-':-<7}")
    
    top_n = 15
    shown = 0
    for r in results:
        if shown >= top_n:
            break
        shown += 1
        ma_icon = "✅" if r["ma_bullish"] else "❌"
        macd_icon = "✅" if r.get("macd_golden", False) else "❌"
        cap_icon = "💰" if r.get("main_net", 0) > 1000 else "  "
        print(f"{r['code']:>8} {r['name']:<8} {r['change_pct']:>+7.2f}% "
              f"{r['tech_score']:>6} {r['capital_score']:>6.0f} "
              f"{r['main_net']:>8.0f} {ma_icon:>4} {macd_icon:>4} "
              f"{r['final_score']:>7.1f} {cap_icon}")
    
    print(f"{'='*90}")
    print(f"  💡 重点关注技术分>20 + 资金分高的股票，💰 = 主力净流入>1000万")
    
    # 只保留达到最低技术分的
    min_tech = TECHNICAL_FILTERS.get("tech_min_total_score", 20)
    filtered = [r for r in results if r["tech_score"] >= min_tech]
    
    # 转回 DataFrame（兼容下游）
    import pandas as pd
    result_df = pd.DataFrame(filtered) if filtered else pd.DataFrame(results[:5])
    
    return result_df, [], market


def apply_morning_filters(df):
    """基础筛选"""
    f = MORNING_FILTERS
    
    df = df[(df["change_pct"] >= f["min_change_pct"]) & (df["change_pct"] <= f["max_change_pct"])]
    df = df[(df["price"] >= f["min_price"]) & (df["price"] <= f["max_price"])]
    
    if "amount" in df.columns:
        df = df[df["amount"] >= f["min_amount"]]
    
    df = df.sort_values("change_pct", ascending=False)
    return df.head(20)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    morning_screen()
