#!/usr/bin/env python3
"""
09:25 集合竞价后三股分析 + 微信推送
深科技(000021) / 北京君正(300223) / 中信证券(600030)

用法: python auction_analysis.py
"""
import sys, os, json, urllib.request, urllib.parse
from datetime import datetime

# ─── 配置 ───────────────────────────────────────
STOCKS = {
    "sz000021": "深科技",
    "sz300223": "北京君正",
    "sh600030": "中信证券",
}

# 从环境变量读取 PushPlus Token
PUSHPLUS_TOKEN = os.getenv("PUSHPLUS_TOKEN", "")

# ─── 数据获取 ────────────────────────────────────

def fetch_quote(code):
    """从腾讯行情API获取实时数据（含集合竞价）"""
    url = f"https://qt.gtimg.cn/q={code}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        raw = resp.read().decode("gbk", errors="ignore")
        parts = raw.split("~")
        if len(parts) < 50:
            return None
        return {
            "name": parts[1],
            "code": parts[2],
            "price": float(parts[3]) if parts[3] else 0,
            "prev_close": float(parts[4]) if parts[4] else 0,
            "open": float(parts[5]) if parts[5] else 0,
            "volume": int(parts[6]) if parts[6] else 0,
            "outer": int(parts[7]) if parts[7] else 0,   # 外盘
            "inner": int(parts[8]) if parts[8] else 0,   # 内盘
            "bid1_price": float(parts[9]) if parts[9] else 0,
            "bid1_vol": int(parts[10]) if parts[10] else 0,
            "ask1_price": float(parts[19]) if parts[19] else 0,
            "ask1_vol": int(parts[20]) if parts[20] else 0,
            "change_pct": float(parts[32]) if parts[32] else 0,
            "high": float(parts[33]) if parts[33] else 0,
            "low": float(parts[34]) if parts[34] else 0,
            "amount": float(parts[37]) if parts[37] else 0,  # 万元
            "turnover": float(parts[38]) if parts[38] else 0,
            "pe": float(parts[39]) if parts[39] else 0,
            "limit_up": float(parts[41]) if parts[41] else 0,
            "limit_down": float(parts[42]) if parts[42] else 0,
            "pb": float(parts[46]) if parts[46] else 0,
            "market_cap": float(parts[45]) if parts[45] else 0,
        }
    except Exception as e:
        print(f"  fetch error {code}: {e}")
        return None


def fetch_auction(code):
    """获取集合竞价数据 (腾讯分时API)"""
    url = f"https://web.ifzq.gtimg.cn/appstock/app/minute/query?_var=min_data&code={code}&r={int(datetime.now().timestamp()*1000)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        raw = resp.read().decode("gbk", errors="ignore")
        # 提取竞价数据
        # 腾讯分时数据格式: min_data={"code":"sz000021","data":["0925 58.86 12345"]}
        import re
        match = re.search(r'min_data\s*=\s*(\{.*?\});', raw, re.DOTALL)
        if match:
            data = json.loads(match.group(1))
            return data.get("data", {}).get(code, {}).get("data", [])
    except:
        pass
    return []


def fetch_daily_kline(code, days=30):
    """获取日K线数据"""
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{days},qfq"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        klines = data["data"][code]["qfqday"]
        closes = [float(k[2]) for k in klines]
        highs = [float(k[3]) for k in klines]
        lows = [float(k[4]) for k in klines]
        volumes = [float(k[5]) / 10000 for k in klines]  # 万手
        return {"closes": closes, "highs": highs, "lows": lows, "volumes": volumes}
    except:
        return None


# ─── 分析函数 ────────────────────────────────────

def analyze_stock(quote, kline, name):
    """单股综合分析"""
    if not quote:
        return f"❌ {name}: 数据获取失败"
    
    p = quote
    lines = []
    
    # 1. 基本行情
    chg_sign = "🔴" if p["change_pct"] > 0 else "🟢" if p["change_pct"] < 0 else "⚪"
    limit_tag = ""
    if p["change_pct"] >= 9.9:
        limit_tag = " 🚀涨停!"
    elif p["change_pct"] >= 19:
        limit_tag = " 🚀涨停!(创业板20%)"
    elif p["change_pct"] <= -9.9:
        limit_tag = " 💥跌停!"
    
    lines.append(f"<b>{name}</b> {chg_sign} {p['price']:.2f} | {p['change_pct']:+.2f}%{limit_tag}")
    lines.append(f"昨收:{p['prev_close']:.2f} 今开:{p['open']:.2f} 高:{p['high']:.2f} 低:{p['low']:.2f}")
    lines.append(f"量:{p['volume']/10000:.1f}万手 额:{p['amount']/10000:.1f}亿 换手:{p['turnover']:.2f}%")
    lines.append(f"PE:{p['pe']:.1f} PB:{p['pb']:.2f} 市值:{p['market_cap']:.0f}亿")
    
    # 2. 盘口分析
    bid_total = p["bid1_vol"]
    ask_total = p["ask1_vol"]
    if p["limit_up"] > 0 and abs(p["price"] - p["limit_up"]) < 0.01:
        # 涨停板
        lines.append(f"封单: {bid_total}手 ≈ {bid_total*p['price']/10000:.0f}万元")
        # 今天竞价阶段的推断
        if p["volume"] < 100000:  # 还在集合竞价阶段，量很小
            lines.append(f"📊 竞价阶段 — 封单{bid_total}手")
    elif p["bid1_price"] > 0 and p["ask1_price"] > 0:
        spread = (p["ask1_price"] - p["bid1_price"]) / p["bid1_price"] * 100
        lines.append(f"买一 {p['bid1_price']:.2f}({bid_total}手) | 卖一 {p['ask1_price']:.2f}({ask_total}手) | 价差 {spread:.3f}%")
    
    # 3. 资金博弈
    if p["outer"] > 0 and p["inner"] > 0:
        ratio = p["outer"] / (p["outer"] + p["inner"]) * 100
        flow_tag = "✅ 主动买入占优" if ratio > 55 else "⚠️ 主动卖出占优" if ratio < 45 else "⚖️ 买卖均衡"
        lines.append(f"外盘:{p['outer']/10000:.1f}万 内盘:{p['inner']/10000:.1f}万 → {flow_tag} (主动买入{ratio:.0f}%)")
    
    # 4. 技术分析
    if kline and len(kline["closes"]) >= 5:
        c = kline["closes"]
        ma5 = sum(c[-5:]) / 5
        ma10 = sum(c[-10:]) / 10
        ma20 = sum(c[-20:]) / 20
        vs_ma5 = (p["price"] / ma5 - 1) * 100
        vs_ma20 = (p["price"] / ma20 - 1) * 100
        
        ma_warn = ""
        if vs_ma20 > 30:
            ma_warn = " ⚠️严重偏离MA20"
        elif vs_ma20 > 15:
            ma_warn = " ⚠️偏离MA20较多"
        elif vs_ma20 < -10:
            ma_warn = " ⚠️跌破MA20"
        
        lines.append(f"MA5:{ma5:.2f}({vs_ma5:+.1f}%) MA20:{ma20:.2f}({vs_ma20:+.1f}%){ma_warn}")
    
    # 5. 综合判断
    signals = []
    if p["change_pct"] >= 9.9:
        if p["bid1_vol"] > 50000:  # 封单>5万手
            signals.append("🟢 涨停封板强，封单充足")
        else:
            signals.append("🟡 涨停封板中，但封单偏弱")
    elif p["change_pct"] > 5:
        signals.append("🟡 大幅高开，关注是否冲击涨停")
    elif p["change_pct"] > 0:
        signals.append("🟢 温和高开")
    elif p["change_pct"] < -3:
        signals.append("🔴 低开，需警惕")
    elif p["change_pct"] < 0:
        signals.append("🟡 小幅低开")
    
    if p["turnover"] > 10:
        bad_turnover = True
    else:
        bad_turnover = False
    
    if signals:
        lines.append("综合: " + " | ".join(signals))
    
    return "<br>".join(lines)


# ─── 推送函数 ────────────────────────────────────

def send_pushplus(title, content):
    """通过PushPlus发送微信推送"""
    if not PUSHPLUS_TOKEN:
        print("❌ PUSHPLUS_TOKEN未设置")
        print(f"\n{'='*60}")
        print(title)
        print('='*60)
        print(content)
        return False
    
    url = "https://pushplus.plus/send"
    data = urllib.parse.urlencode({
        "token": PUSHPLUS_TOKEN,
        "title": title,
        "content": content,
        "template": "html",
    }).encode("utf-8")
    
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        result = resp.read().decode()
        print(f"PushPlus: {result[:200]}")
        return True
    except Exception as e:
        print(f"PushPlus error: {e}")
        return False


# ─── 主程序 ──────────────────────────────────────

def main():
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")
    weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()]
    
    print(f"=== 集合竞价分析 {today_str} {time_str} {weekday} ===")
    
    # 周六日不运行
    if now.weekday() >= 5:
        print("周末休市，跳过")
        return
    
    # 获取三股数据
    results = {}
    klines = {}
    for code, name in STOCKS.items():
        print(f"获取 {name}({code})...")
        quote = fetch_quote(code)
        if quote:
            quote["_fetch_time"] = time_str
        results[code] = quote
        klines[code] = fetch_daily_kline(code, 30)
    
    # 构建推送内容
    html_parts = []
    html_parts.append(f'<h3>📊 09:25 集合竞价速报</h3>')
    html_parts.append(f'<p>{today_str} {time_str} {weekday} | 上证4073 | 深成15812</p>')
    html_parts.append('<hr>')
    
    for code, name in STOCKS.items():
        analysis = analyze_stock(results.get(code), klines.get(code), name)
        html_parts.append(f'<div style="margin:12px 0;padding:10px;background:#1a1a2e;border-radius:8px;border-left:4px solid #e94560;">')
        html_parts.append(analysis)
        html_parts.append('</div>')
    
    # 操作建议
    html_parts.append('<hr>')
    html_parts.append('<h4>🎯 今日操作建议</h4>')
    
    sd = results.get("sz000021")
    bj = results.get("sz300223")
    zx = results.get("sh600030")
    
    suggestions = []
    
    # 深科技
    if sd:
        if sd["change_pct"] >= 9.9:
            if sd["bid1_vol"] > 50000:
                suggestions.append("深科技: 🟢 封板强，持有观望；封单<5万手则减仓")
            else:
                suggestions.append("深科技: 🟡 封单偏弱！建议减仓50%，涨停板出货信号")
        elif sd["change_pct"] > 5:
            suggestions.append("深科技: 🟡 高开<8%，关注是否冲击涨停；若冲板失败则减仓")
        elif sd["change_pct"] > 0:
            suggestions.append("深科技: 🟢 温和开盘，按计划执行")
        else:
            suggestions.append("深科技: 🔴 低开！跌破53.51减半仓，跌破49.60全清")
    
    # 北京君正
    if bj:
        if bj["change_pct"] >= 10:
            suggestions.append("北京君正: 🟡 大幅高开，不建议追；已持有者设好止损")
        elif bj["change_pct"] < -5:
            suggestions.append("北京君正: 🔴 大幅低开，纯观察不参与")
        else:
            suggestions.append("北京君正: ⚪ 正常开盘，观察不参与，PE 188x风险极高")
    
    # 中信证券
    if zx:
        if zx["change_pct"] > 3:
            suggestions.append("中信证券: 🟢 强势高开，持有；放量突破29.31可加仓")
        elif zx["change_pct"] > 0:
            suggestions.append("中信证券: 🟢 温和上涨，持股不动；回踩27.5-27.8可加仓")
        elif zx["change_pct"] < -2:
            suggestions.append("中信证券: 🟡 回调中，关注27.5-27.8支撑；跌破26.59减仓")
        else:
            suggestions.append("中信证券: ⚪ 平开附近，按计划持有")
    
    for s in suggestions:
        html_parts.append(f'<p>{s}</p>')
    
    html_parts.append('<hr>')
    html_parts.append(f'<p style="color:#888;font-size:11px;">🤖 自动分析 {time_str} | 深科技目标75 | 仅供参考不构成投资建议</p>')
    
    html_content = "".join(html_parts)
    
    # 输出并推送
    print("\n" + "="*60)
    print("分析结果已生成")
    print("="*60)
    
    title = f"📈 竞价速报 {today_str} {time_str}"
    success = send_pushplus(title, html_content)
    
    if success:
        print("✅ 微信推送成功")
    else:
        print("❌ 微信推送失败，内容已打印在控制台")
        print(html_content)

if __name__ == "__main__":
    main()
