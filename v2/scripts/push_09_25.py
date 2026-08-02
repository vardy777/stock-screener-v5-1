#!/usr/bin/env python
"""
push_09_25.py — 09:25运行, 早盘候选推送
读取市场快照
运行21因子计算 + 行业中性化 + IC加权
运行三大策略 + 市场自适应配额
输出Top 5候选
通过 PushPlus 推送到微信
"""
import sys, os, json, sqlite3, logging, math
from datetime import datetime, date
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from v2.config import (
    DATA_DIR, MARKET_DB, FACTOR_IC_FILE, PUSHPLUS_TOKEN,
    FACTOR_21, STRATEGIES, RISK,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s %(message)s')
logger = logging.getLogger('push_09_25')


# ── 因子计算辅助函数 ──

def calc_factors(stock):
    """对单只股票计算21个因子值"""
    factors = {}
    price = stock.get("price", 0)
    prev_close = stock.get("prev_close", 0)
    high = stock.get("high", 0)
    low = stock.get("low", 0)
    amount = stock.get("amount", 0)
    volume = stock.get("volume", 0)

    # 动量因子
    factors["momentum_1d"] = stock.get("change_pct", 0)
    # 下面几个需要历史数据, 从 snapshot 拿不到时用默认值
    factors["momentum_5d"] = stock.get("change_pct_5d", stock.get("change_pct", 0))
    factors["momentum_10d"] = stock.get("change_pct_10d", factors["momentum_5d"])
    factors["momentum_20d"] = stock.get("change_pct_20d", factors["momentum_10d"])

    # 技术因子
    factors["ma_bullish"] = 1 if stock.get("ma_bullish", False) else 0
    factors["macd_golden"] = 1 if stock.get("macd_golden", False) else 0
    factors["rsi_6"] = stock.get("rsi_6", 50)
    factors["rsi_14"] = stock.get("rsi_14", 50)
    factors["volume_ratio"] = stock.get("volume_ratio", 1.0)
    factors["close_position"] = stock.get("close_position", 0.5)

    # 资金因子
    factors["main_net"] = stock.get("main_net", 0)
    factors["main_ratio"] = stock.get("main_ratio", 0)
    factors["super_large_net"] = stock.get("super_large_net", 0)

    # 估值因子
    factors["pe_ttm"] = stock.get("pe_ttm", 30)
    factors["pb"] = stock.get("pb", 3)
    factors["market_cap"] = stock.get("circulating_market_cap", 5e9)

    # 量价因子
    if price > 0 and prev_close > 0:
        factors["vwap_position"] = abs(price - prev_close) / prev_close
    else:
        factors["vwap_position"] = 0.02
    factors["candle_body_pct"] = stock.get("candle_body_pct", 0)
    factors["high_low_spread"] = (high - low) / price if price > 0 else 0

    # 综合
    factors["tech_score"] = stock.get("tech_score", 0)
    factors["cap_score"] = stock.get("capital_score", 0)

    return factors


def normalize_factor(values):
    """百分位归一化 (0~1)"""
    if not values:
        return values
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    rank_map = {v: i / (n - 1) if n > 1 else 0.5 for i, v in enumerate(sorted_vals)}
    return [rank_map[v] for v in values]


def industry_neutralize(stocks_with_factors):
    """行业中性化: 对每个行业内的因子值做内部归一化"""
    # 按行业分组
    by_industry = defaultdict(list)
    for s in stocks_with_factors:
        ind = s.get("industry_desc", "未知") or "未知"
        by_industry[ind].append(s)

    neutralized = []
    for ind, group in by_industry.items():
        if len(group) < 2:
            neutralized.extend(group)
            continue
        # 对每个因子做行业内归一化
        factor_names = list(FACTOR_21.keys())
        for fname in factor_names:
            vals = [s.get("factor_" + fname, 0) for s in group]
            norm_vals = normalize_factor(vals)
            for i, s in enumerate(group):
                s["factor_norm_" + fname] = norm_vals[i]
        neutralized.extend(group)
    return neutralized


def load_ic_weights():
    """加载 IC 权重文件，若无则使用默认权重"""
    if os.path.exists(FACTOR_IC_FILE):
        try:
            with open(FACTOR_IC_FILE, "r") as f:
                data = json.load(f)
            return data.get("ic_weights", {})
        except Exception:
            pass
    # 默认权重
    return {name: info["weight"] for name, info in FACTOR_21.items()}


def compute_composite_score(stock, ic_weights):
    """用 IC 加权计算综合得分"""
    score = 0
    for fname, weight in ic_weights.items():
        norm_val = stock.get("factor_norm_" + fname, 0.5)
        score += norm_val * weight
    return round(score * 100, 2)


def run_strategies(stocks):
    """三大策略评分"""
    results = []
    for s in stocks:
        total = 0
        # 动量策略
        momentum_score = (
            s.get("factor_norm_momentum_1d", 0.5) * 0.3 +
            s.get("factor_norm_momentum_5d", 0.5) * 0.3 +
            s.get("factor_norm_volume_ratio", 0.5) * 0.2 +
            s.get("factor_norm_close_position", 0.5) * 0.2
        )
        # 资金驱动策略
        capital_score = (
            s.get("factor_norm_main_net", 0.5) * 0.4 +
            s.get("factor_norm_main_ratio", 0.5) * 0.3 +
            s.get("factor_norm_super_large_net", 0.5) * 0.3
        )
        # 技术反转策略
        tech_score = (
            s.get("factor_norm_ma_bullish", 0.5) * 0.3 +
            s.get("factor_norm_macd_golden", 0.5) * 0.25 +
            s.get("factor_norm_tech_score", 0.5) * 0.25 +
            s.get("factor_norm_rsi_14", 0.5) * 0.2
        )

        total = (
            momentum_score * STRATEGIES["momentum"]["weight"] +
            capital_score * STRATEGIES["capital_flow"]["weight"] +
            tech_score * STRATEGIES["tech_reversal"]["weight"]
        )

        s["momentum_score"] = round(momentum_score * 100, 2)
        s["capital_score"] = round(capital_score * 100, 2)
        s["tech_reversal_score"] = round(tech_score * 100, 2)
        s["strategy_total"] = round(total * 100, 2)
        results.append(s)

    results.sort(key=lambda x: x["strategy_total"], reverse=True)
    return results


def market_adaptive_quota(stocks, top_n=15):
    """市场自适应配额: 根据市场情绪调整候选数量"""
    if not stocks:
        return []
    # 简单实现: 如果平均得分高则多选, 否则收紧
    avg_score = sum(s.get("strategy_total", 0) for s in stocks[:30]) / max(len(stocks[:30]), 1)
    if avg_score > 60:
        quota = min(top_n + 5, len(stocks))
    elif avg_score > 40:
        quota = min(top_n, len(stocks))
    else:
        quota = min(max(top_n - 5, 3), len(stocks))
    return stocks[:quota]


# ── PushPlus 推送 ──

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


def generate_html_report(top5, market_info=None):
    """生成 HTML 推送报告"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows_html = ""
    for i, s in enumerate(top5[:5]):
        rows_html += f"""
        <tr>
            <td>{i+1}</td>
            <td><b>{s.get('code','')}</b></td>
            <td>{s.get('name','')}</td>
            <td>{s.get('change_pct',0):+.2f}%</td>
            <td>{s.get('strategy_total',0):.1f}</td>
            <td>{s.get('momentum_score',0):.1f}</td>
            <td>{s.get('capital_score',0):.1f}</td>
            <td>{s.get('tech_reversal_score',0):.1f}</td>
        </tr>"""

    html = f"""
    <html>
    <head><meta charset="utf-8"><style>
        body {{ font-family: 'Microsoft YaHei', sans-serif; background: #1a1a2e; color: #eee; padding: 16px; }}
        h2 {{ color: #e94560; border-bottom: 2px solid #e94560; padding-bottom: 8px; }}
        table {{ width: 100%; border-collapse: collapse; margin: 12px 0; }}
        th {{ background: #16213e; color: #0f3460; padding: 8px; text-align: left; }}
        td {{ padding: 8px; border-bottom: 1px solid #333; }}
        .score {{ color: #4ecca3; }}
        .pos {{ color: #ff6b6b; }}
    </style></head>
    <body>
        <h2>📈 早盘候选推送</h2>
        <p>⏰ {now}</p>
        <table>
            <tr><th>#</th><th>代码</th><th>名称</th><th>涨幅</th><th>综合</th><th>动量</th><th>资金</th><th>技术</th></tr>
            {rows_html}
        </table>
        <p style="color:#888;">💡 14:45运行验证脚本确认买入信号</p>
    </body>
    </html>"""
    return html


# ── 主流程 ──

def main():
    today = date.today().strftime("%Y-%m-%d")
    logger.info(f"=== 早盘候选推送 {today} ===")

    # 1. 从 market.db 读取今日快照
    if not os.path.exists(MARKET_DB):
        logger.error(f"market.db 不存在, 请先运行 save_daily_snapshot.py")
        return

    conn = sqlite3.connect(MARKET_DB)
    c = conn.cursor()
    c.execute("SELECT * FROM daily_snapshot WHERE date=?", (today,))
    columns = [col[0] for col in c.description]
    rows = c.fetchall()
    conn.close()

    if not rows:
        logger.error(f"今日 {today} 尚无快照数据")
        return

    stocks = [dict(zip(columns, row)) for row in rows]
    logger.info(f"读取 {len(stocks)} 条快照")

    # 2. 基础筛选: 去除ST/停牌/价格过低
    filtered = []
    for s in stocks:
        name = s.get("name", "") or ""
        price = s.get("price", 0) or 0
        if "ST" in name or "退" in name:
            continue
        if price < 3 or price > 200:
            continue
        change_pct = s.get("change_pct", 0) or 0
        if change_pct < -5 or change_pct > 10:
            continue
        amount = s.get("amount", 0) or 0
        if amount < 3e7:
            continue
        filtered.append(s)

    logger.info(f"基础筛选后: {len(filtered)} 只")

    # 3. 计算21因子
    for s in filtered:
        factors = calc_factors(s)
        for k, v in factors.items():
            s["factor_" + k] = v

    # 4. 行业中性化
    neutralized = industry_neutralize(filtered)
    logger.info(f"行业中性化完成: {len(neutralized)} 只")

    # 5. IC 加权综合评分
    ic_weights = load_ic_weights()
    for s in neutralized:
        s["composite_score"] = compute_composite_score(s, ic_weights)

    # 6. 三大策略评分
    scored = run_strategies(neutralized)

    # 7. 市场自适应配额
    candidates = market_adaptive_quota(scored, top_n=15)
    top5 = candidates[:5]

    logger.info(f"Top 5 候选:")
    for i, s in enumerate(top5):
        logger.info(f"  {i+1}. {s['code']} {s['name']} 综合{s.get('composite_score',0)} 策略{s.get('strategy_total',0)}")

    # 8. 保存候选到 dashboard_data.json
    dashboard_path = os.path.join(DATA_DIR, "dashboard_data.json")
    dashboard = {"candidates": [], "time": datetime.now().strftime("%H:%M"), "date": today}
    for s in top5:
        dashboard["candidates"].append({
            "code": s.get("code", ""),
            "name": s.get("name", ""),
            "price": s.get("price", 0),
            "change_pct": s.get("change_pct", 0),
            "strategy_total": s.get("strategy_total", 0),
            "momentum_score": s.get("momentum_score", 0),
            "capital_score": s.get("capital_score", 0),
            "tech_reversal_score": s.get("tech_reversal_score", 0),
            "industry": s.get("industry_desc", ""),
        })

    # 保留已有 morning 字段
    if os.path.exists(dashboard_path):
        try:
            existing = json.load(open(dashboard_path, "r"))
            if isinstance(existing, dict):
                existing["morning"] = dashboard
                dashboard = existing
        except Exception:
            pass

    with open(dashboard_path, "w", encoding="utf-8") as f:
        json.dump(dashboard, f, ensure_ascii=False, indent=2)

    # 9. PushPlus 推送
    html = generate_html_report(top5)
    push_to_wechat(f"📈 早盘候选 {today}", html)

    logger.info("=== 早盘候选推送完成 ===")


if __name__ == "__main__":
    main()
