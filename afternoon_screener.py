"""
尾盘买入候选模块 v2.0
新增 Phase 1 因子:
  - 尾盘时再次确认技术面
  - 重点看当日走势是否符合预期
"""

import pandas as pd
import logging
from datetime import datetime

from config import AFTERNOON_FILTERS, RISK_CONTROL, TECHNICAL_FILTERS, CAPITAL_FILTERS, SCORING_WEIGHTS
from data_fetcher import (
    fetch_top_stocks, batch_fetch_quotes,
    get_market_summary, fetch_limit_up_stocks
)
from technical import (
    batch_fetch_kline, score_technical,
    check_bullish_alignment, check_macd_golden
)
from fund_flow import batch_fetch_money_flow, calculate_capital_score

logger = logging.getLogger(__name__)


def afternoon_confirm(morning_candidates=None):
    """
    尾盘买入确认 v2.0
    """
    print("=" * 60)
    print("  🎯 尾盘买入候选确认 v2.0")
    print(f"  ⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    
    # 1. 大盘
    market = get_market_summary()
    sh_pct = market.get("sh_index", 0) or 0
    print(f"\n📊 大盘: {market.get('market_mood','?')} (上证 {sh_pct:+.2f}%)")
    
    if sh_pct < -1.5:
        print("  🚨 大盘跌幅超1.5%，建议空仓！")
        return []
    
    # 2. 获取实时行情
    if morning_candidates is not None and len(morning_candidates) > 0:
        codes = morning_candidates["code"].tolist() if "code" in morning_candidates.columns else []
        codes = [str(c).strip() for c in codes if str(c).strip()]
        print(f"📋 跟踪 {len(codes)} 只候选股...")
        df = batch_fetch_quotes(codes)
        if df is None:
            return []
        print(f"✅ 获取 {len(df)} 只行情")
    else:
        print("📋 全市场尾盘筛选...")
        df = fetch_top_stocks(limit=200)
        if df is None:
            return []
    
    # 3. 基础尾盘筛选
    df = apply_afternoon_base_filters(df)
    if df is None or len(df) == 0:
        print("❌ 尾盘基础筛选无候选")
        return []
    
    # 4. 获取技术面
    codes = df["code"].tolist()
    print(f"📈 获取技术面数据 ({len(codes)} 只)...")
    klines = batch_fetch_kline(codes, days=60)
    
    # 5. 获取资金流 (Phase 2 NEW)
    print(f"💰 获取资金流数据 ({len(codes)} 只)...")
    money_flows = batch_fetch_money_flow(codes)
    
    # 6. 综合评估
    results = []
    for _, row in df.iterrows():
        code = str(row["code"])
        kline = klines.get(code)
        mf = money_flows.get(code, {})
        
        item = {
            "code": code,
            "name": str(row.get("name", "")),
            "price": float(row.get("price", 0)),
            "change_pct": float(row.get("change_pct", 0)),
            "close_position": float(row.get("close_position", 0) or 0),
            "candle_body_pct": float(row.get("candle_body_pct", 0) or 0),
            "amount": float(row.get("amount", 0) or 0),
        }
        
        # 技术面
        if kline:
            tech = score_technical(kline)
            item["tech_score"] = tech["score"]
            ok_ma, _ = check_bullish_alignment(kline)
            item["ma_ok"] = ok_ma
            macd_ok = False
            if len(kline) >= 26:
                macd_ok, _ = check_macd_golden(kline)
            item["macd_ok"] = macd_ok
        else:
            item["tech_score"] = 0
            item["ma_ok"] = False
            item["macd_ok"] = False
        
        # 资金流 (Phase 2 NEW)
        cap = calculate_capital_score(mf, kline)
        item["capital_score"] = cap["capital_score"]
        item["main_net"] = cap["main_net"]
        item["cap_reason"] = cap["money_flow_reason"]
        
        # 综合评分
        w = SCORING_WEIGHTS
        item["final_score"] = (
            item["close_position"] * 30 +
            min(item["candle_body_pct"], 5) * 5 +
            item["tech_score"] * w["tech_score"] +
            item["capital_score"] * w["capital_score"] * 2 +
            (10 if item["ma_ok"] else 0) +
            (8 if item["macd_ok"] else 0)
        )
        
        results.append(item)
    
    # 资金流过滤
    results = [r for r in results if r["main_net"] >= CAPITAL_FILTERS["min_main_net"]]
    results.sort(key=lambda r: r["final_score"], reverse=True)
    
    # 6. 输出
    print(f"\n{'='*90}")
    print(f"  ⭐ 尾盘买入候选 (Phase 2)")
    print(f"{'='*90}")
    print(f"{'代码':>8} {'名称':<8} {'涨幅':>7} {'位置':>6} {'阳线':>6} {'技术':>5} {'资金':>6} {'主力万':>8} {'总分':>7}")
    print(f"{'-'*8} {'-':-<8} {'-':-<7} {'-':-<6} {'-':-<6} {'-':-<5} {'-':-<6} {'-':-<8} {'-':-<7}")
    
    for i, r in enumerate(results[:8]):
        cap_icon = "💰" if r.get("main_net", 0) > 500 else "  "
        pos = r["close_position"]
        candle = r["candle_body_pct"]
        print(f"{r['code']:>8} {r['name']:<8} {r['change_pct']:>+7.2f}% "
              f"{pos*100:>5.0f}% {candle:>+5.2f}% "
              f"{r['tech_score']:>5} {r['capital_score']:>6.0f} "
              f"{r['main_net']:>8.0f} {r['final_score']:>7.1f} {cap_icon}")
    
    print(f"{'='*80}")
    
    # 取前 5 只作为最终候选
    final = results[:5]
    
    if final:
        target = RISK_CONTROL["target_profit_pct"]
        stop = RISK_CONTROL["stop_loss_pct"]
        print(f"\n  💡 买入策略:")
        for i, r in enumerate(final):
            print(f"    {i+1}. {r['code']} {r['name']} @ {r['price']:.2f} "
                  f"(技术{r['tech_score']}分 MA:{r.get('ma_msg','')})")
        print(f"    最多{RISK_CONTROL['max_positions']}只，分2-3笔 14:50-14:55买入")
        print(f"    目标: {target}% 止损: {stop}%")
    else:
        print("  ❌ 无符合条件的买入标的")
    
    # 转 DataFrame 返回
    return pd.DataFrame(final) if final else pd.DataFrame()


def apply_afternoon_base_filters(df):
    """基础尾盘筛选"""
    f = AFTERNOON_FILTERS
    
    df = df[(df["change_pct"] >= f["min_change_pct"]) & (df["change_pct"] <= f["max_change_pct"])]
    df = df[df["change_pct"] < 9.8]  # 去掉涨停
    
    if "close_position" in df.columns:
        df = df[df["close_position"] >= f["min_close_position"]]
    
    if "candle_body_pct" in df.columns:
        df = df[df["candle_body_pct"] >= f["min_candle_body"]]
    
    df = df[df["price"] >= 5.0]
    
    if "amount" in df.columns:
        df = df[df["amount"] >= f["min_amount"]]
    
    return df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    afternoon_confirm()
