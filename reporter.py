"""
报告生成模块
生成简洁的每日报告 + 看板 dashboard
"""

import os
import json
import logging
from datetime import datetime, date

from config import REPORT_DIR, RISK_CONTROL, DATA_DIR, JOURNAL_PATH

logger = logging.getLogger(__name__)

# 看板数据缓存文件
DASHBOARD_DATA = os.path.join(DATA_DIR, "dashboard_data.json")
DASHBOARD_HTML = os.path.join(os.path.expanduser("~"), "Desktop", "选股看板.html")


def _save_dashboard_data(key, data):
    """保存看板数据到 JSON"""
    cache = {}
    if os.path.exists(DASHBOARD_DATA):
        try:
            with open(DASHBOARD_DATA, "r", encoding="utf-8") as f:
                cache = json.load(f)
            if not isinstance(cache, dict):
                cache = {}
        except:
            cache = {}
    
    cache[key] = data
    cache["_updated"] = datetime.now().strftime("%H:%M")
    cache["_date"] = date.today().strftime("%Y-%m-%d")
    
    with open(DASHBOARD_DATA, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    
    _generate_dashboard()


def _load_dashboard_data():
    """加载看板数据"""
    if not os.path.exists(DASHBOARD_DATA):
        return {"_date": "", "_updated": ""}
    try:
        with open(DASHBOARD_DATA, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"_date": "", "_updated": ""}

logger = logging.getLogger(__name__)


def generate_morning_report(candidates, hot_sectors, market):
    """
    生成早盘观察池 HTML 报告 + 更新看板
    """
    today = date.today().strftime("%Y-%m-%d")
    now = datetime.now().strftime("%H:%M")
    
    # 保存看板数据
    candidates_data = []
    if candidates is not None and len(candidates) > 0:
        for _, row in candidates.iterrows():
            candidates_data.append({
                "code": str(row.get("code", "")),
                "name": str(row.get("name", ""))[:6],
                "price": round(float(row.get("price", 0) or 0), 2),
                "change_pct": round(float(row.get("change_pct", 0) or 0), 2),
                "amount": round(float(row.get("amount", 0) or 0) / 1e8, 2),
            })
    
    _save_dashboard_data("morning", {
        "count": len(candidates_data),
        "candidates": candidates_data[:10],
        "time": now,
        "market": {
            "mood": market.get("market_mood", "未知"),
            "sh": market.get("sh_index", ""),
            "sz": market.get("sz_index", ""),
            "cyb": market.get("cyb_index", ""),
        }
    })
    
    mood = market.get("market_mood", "未知")
    mood_color = {"强势": "#ff4444", "震荡": "#ffd700", 
                  "弱势": "#4fc3f7", "危险": "#ff0000"}.get(mood, "#ccc")
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>选股报告 - 早盘 {today}</title>
<style>
  body {{ font-family: 'Microsoft YaHei', sans-serif; max-width: 900px; margin: 20px auto; padding: 20px; background: #0f1923; color: #e0e0e0; }}
  h1 {{ color: #ffd700; border-bottom: 2px solid #ffd700; padding-bottom: 10px; }}
  .mood {{ color: {mood_color}; font-weight: bold; }}
  table {{ border-collapse: collapse; width: 100%; margin: 15px 0; }}
  th {{ background: #1a3a5c; color: #ffd700; padding: 10px 8px; text-align: center; }}
  td {{ padding: 8px; text-align: center; border-bottom: 1px solid #2a3a4a; }}
  tr:hover {{ background: #1a2a3a; }}
  .up {{ color: #ff4444; }}
  .down {{ color: #4caf50; }}
  .tip {{ background: #1a2a3a; border-left: 4px solid #ffd700; padding: 12px; margin: 15px 0; }}
  .empty {{ color: #666; text-align: center; padding: 30px; }}
  .footer {{ text-align: center; color: #444; margin-top: 30px; font-size: 12px; }}
</style>
</head>
<body>
<h1>📈 早盘观察池</h1>
<p>📅 {today} {now} | 大盘: <span class="mood">{mood}</span></p>
"""
    
    if candidates is not None and len(candidates) > 0:
        html += """<table>
<thead><tr><th>代码</th><th>名称</th><th>价格</th><th>涨幅</th><th>成交额(亿)</th></tr></thead><tbody>
"""
        for _, row in candidates.iterrows():
            cp = row.get("change_pct", 0) or 0
            amt = (row.get("amount", 0) or 0) / 1e8
            cls = "up" if cp >= 0 else "down"
            html += f"<tr><td>{row.get('code','')}</td><td>{str(row.get('name',''))[:6]}</td>"
            html += f"<td>{row.get('price',0):.2f}</td><td class='{cls}'>{cp:+.2f}%</td><td>{amt:.2f}</td></tr>\n"
        html += "</tbody></table>\n"
    else:
        html += '<div class="empty">今日无符合条件的候选股</div>\n'
    
    html += f"""
<div class="tip">
  <strong>💡 操作提醒</strong><br>
  1. 关注上述候选股下午走势，剔除走弱的<br>
  2. 14:30 运行尾盘确认程序: python main.py afternoon<br>
  3. 最多买入 {RISK_CONTROL['max_positions']} 只，分 2-3 笔在 14:50-14:55 买入<br>
  4. 明日开盘务必卖出，目标 {RISK_CONTROL['target_profit_pct']}%，止损 -3%<br>
  5. 纪律 > 判断，执行 > 分析
</div>
<div class="footer">选股系统 v1.0 | 仅供参考，不构成投资建议</div>
</body>
</html>"""
    
    path = os.path.join(REPORT_DIR, f"morning_{today}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  📄 报告已保存: {path}")
    return path


def generate_afternoon_report(final_candidates, market):
    """
    生成尾盘买入报告 + 更新看板
    """
    today = date.today().strftime("%Y-%m-%d")
    now = datetime.now().strftime("%H:%M")
    
    # 保存看板数据
    candidates_data = []
    if final_candidates is not None and len(final_candidates) > 0:
        for _, row in final_candidates.iterrows():
            candidates_data.append({
                "code": str(row.get("code", "")),
                "name": str(row.get("name", ""))[:6],
                "price": round(float(row.get("price", 0) or 0), 2),
                "change_pct": round(float(row.get("change_pct", 0) or 0), 2),
                "close_position": round(float(row.get("close_position", 0) or 0) * 100, 0),
                "candle_body": round(float(row.get("candle_body_pct", 0) or 0), 2),
            })
    
    _save_dashboard_data("afternoon", {
        "count": len(candidates_data),
        "candidates": candidates_data[:5],
        "time": now,
        "has_signal": len(candidates_data) > 0,
    })
    today = date.today().strftime("%Y-%m-%d")
    now = datetime.now().strftime("%H:%M")
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>选股报告 - 尾盘 {today}</title>
<style>
  body {{ font-family: 'Microsoft YaHei', sans-serif; max-width: 900px; margin: 20px auto; padding: 20px; background: #0f1923; color: #e0e0e0; }}
  h1 {{ color: #ffd700; border-bottom: 2px solid #ffd700; padding-bottom: 10px; }}
  .buy {{ background: linear-gradient(135deg, #1a3a2a, #0f1923); border: 1px solid #4caf50; border-radius: 8px; padding: 15px; }}
  .no-buy {{ background: #1a2a3a; border: 1px solid #666; border-radius: 8px; padding: 15px; }}
  table {{ border-collapse: collapse; width: 100%; margin: 15px 0; }}
  th {{ background: #1a3a5c; color: #ffd700; padding: 10px; text-align: center; }}
  td {{ padding: 8px; text-align: center; border-bottom: 1px solid #2a3a4a; }}
  tr:hover {{ background: #1a2a3a; }}
  .up {{ color: #ff4444; }}
  .checklist {{ background: #1a2a3a; border-radius: 8px; padding: 15px; margin: 15px 0; }}
  .done {{ color: #4caf50; }}
  .footer {{ text-align: center; color: #444; margin-top: 30px; font-size: 12px; }}
</style>
</head>
<body>
<h1>🎯 尾盘买入确认</h1>
<p>📅 {today} {now}</p>
"""
    
    if final_candidates is not None and len(final_candidates) > 0:
        html += '<div class="buy"><h2>✅ 发现买入信号</h2></div>'
        html += """<table>
<thead><tr><th>代码</th><th>名称</th><th>价格</th><th>涨幅</th><th>日内位置</th><th>阳线实体</th></tr></thead><tbody>
"""
        for _, row in final_candidates.iterrows():
            cp = row.get("change_pct", 0) or 0
            pos = row.get("close_position", 0) or 0
            body = row.get("candle_body_pct", 0) or 0
            cls = "up" if cp >= 0 else "down"
            html += f"<tr><td>{row.get('code','')}</td><td>{str(row.get('name',''))[:6]}</td>"
            html += f"<td>{row.get('price',0):.2f}</td><td class='{cls}'>{cp:+.2f}%</td>"
            html += f"<td>{pos*100:.0f}%</td><td>{body:+.2f}%</td></tr>\n"
        html += "</tbody></table>\n"
        
        html += f"""
<div class="checklist">
  <h3>📋 买入检查清单</h3>
  <ul>
    <li class="done">✅ 技术面符合条件</li>
    <li class="done">✅ 大盘环境安全</li>
    <li>⬜ 分 2-3 笔在 14:50-14:55 买入</li>
    <li>⬜ 每只 ≤{RISK_CONTROL['max_single_position_pct']}% 仓位</li>
    <li>⬜ 明日开盘设定目标 {RISK_CONTROL['target_profit_pct']}% / 止损 -3%</li>
  </ul>
</div>"""
    else:
        html += '<div class="no-buy"><h2>❌ 无买入信号</h2><p>建议空仓，明天再战。</p></div>'
    
    html += """<div class="footer">选股系统 v1.0 | 仅供参考，不构成投资建议</div></body></html>"""
    
    path = os.path.join(REPORT_DIR, f"afternoon_{today}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  📄 报告已保存: {path}")
    return path


def _generate_dashboard():
    """
    生成桌面看板 HTML（4 面板，自动展示各模块最新数据）
    保存到桌面: 选股看板.html
    """
    data = _load_dashboard_data()
    today = data.get("_date", date.today().strftime("%Y-%m-%d"))
    updated = data.get("_updated", "--:--")
    
    # 大盘数据
    morning_data = data.get("morning", {})
    mk = morning_data.get("market", {})
    sh = mk.get("sh", "")
    sz = mk.get("sz", "")
    cyb = mk.get("cyb", "")
    mood = mk.get("mood", "等待开盘")
    mood_color = {"强势": "#ff4757", "震荡": "#ffa502", "弱势": "#2ed573", "危险": "#ff0000"}.get(mood, "#888")
    
    # 早盘数据
    m_candidates = morning_data.get("candidates", [])
    m_count = morning_data.get("count", 0)
    m_time = morning_data.get("time", "")
    m_status = f"已筛选 {m_count} 只" if m_count > 0 else "⏳ 待运行" if today == date.today().strftime("%Y-%m-%d") else f"昨日: {m_count} 只"
    m_badge = "badge-ok" if m_count > 0 else "badge-wait"
    
    # 尾盘数据
    a_data = data.get("afternoon", {})
    a_candidates = a_data.get("candidates", [])
    a_count = a_data.get("count", 0)
    a_has = a_data.get("has_signal", False)
    a_time = a_data.get("time", "")
    a_status = f"发现 {a_count} 个信号 🎯" if a_has else "❌ 今日无信号" if a_count == 0 and a_time else "⏳ 待运行"
    a_badge = "badge-ok" if a_has else "badge-nope" if a_count == 0 and a_time else "badge-wait"
    
    # 交易数据
    from trade_journal import init_journal
    try:
        jdf = init_journal()
        closed = jdf[(jdf["profit_pct"] != 0) & (jdf["sell_price"].notna()) & (jdf["sell_price"] > 0)]
        total = len(closed)
        wins = len(closed[closed["profit_pct"] > 0]) if total > 0 else 0
        losses = total - wins
        win_rate = round(wins / total * 100, 1) if total > 0 else 0
        avg_p = round(closed["profit_pct"].mean(), 2) if total > 0 else 0
        t_profit = round(closed["profit_pct"].sum(), 2) if total > 0 else 0
    except:
        total = wins = losses = 0; win_rate = 0; avg_p = 0; t_profit = 0
    
    trade_status = f"📊 {total} 笔" if total > 0 else "📭 暂无交易"
    trade_badge = "badge-ok" if total > 0 else "badge-wait"
    
    # 当前时间状态
    now = datetime.now()
    weekday = now.weekday()
    is_weekend = weekday >= 5
    if is_weekend:
        current_hint = "🛑 周末休市"
    elif 0 <= now.hour < 9:
        current_hint = "🌅 盘前准备 · 等待 09:30 开盘"
    elif now.hour < 16:
        current_hint = "📊 盘中 · 监控候选股"
    else:
        current_hint = "📊 盘后 · 运行复盘"
    
    # 构建候选股表格 HTML
    def _stock_table(stocks, cols=None):
        if not stocks:
            return '<div class="empty">暂无数据</div>'
        html = '<table><thead><tr>'
        headers = {"code": "代码", "name": "名称", "price": "价格", "change_pct": "涨幅", "amount": "成交额(亿)", "close_position": "位置", "candle_body": "阳线"}
        keys = cols or ["code", "name", "price", "change_pct"]
        for k in keys:
            html += f'<th>{headers.get(k, k)}</th>'
        html += '</tr></thead><tbody>'
        for s in stocks:
            html += '<tr>'
            for k in keys:
                v = s.get(k, "")
                cls = ""
                if k == "change_pct":
                    cls = "up" if (isinstance(v, str) and v.startswith("+")) or (isinstance(v, (int, float)) and v > 0) else "down" if (isinstance(v, str) and v.startswith("-")) else ""
                    v = f'{v:+.2f}%' if isinstance(v, float) else v
                elif k == "price":
                    v = f'{v:.2f}' if isinstance(v, float) else v
                elif k == "amount":
                    v = f'{v:.2f}' if isinstance(v, float) else v
                elif k == "close_position":
                    v = f'{v:.0f}%' if isinstance(v, (int, float)) else v
                elif k == "candle_body":
                    cls = "up" if (isinstance(v, (int, float)) and v > 0) else ""
                    v = f'{v:+.2f}%' if isinstance(v, float) else v
                html += f'<td class="{cls}">{v}</td>'
            html += '</tr>'
        html += '</tbody></table>'
        return html
    
    m_table = _stock_table(m_candidates, ["code", "name", "price", "change_pct", "amount"])
    a_table = _stock_table(a_candidates, ["code", "name", "price", "change_pct", "close_position"])
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>选股系统看板</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, 'Microsoft YaHei', 'PingFang SC', sans-serif; background: #0a0e17; color: #e0e0e0; min-height: 100vh; }}
  
  /* 头部 */
  .header {{ background: linear-gradient(135deg, #0f1923 0%, #1a2a3a 100%); border-bottom: 2px solid #ffd700; padding: 20px 30px; }}
  .header h1 {{ color: #ffd700; font-size: 24px; display: flex; align-items: center; gap: 10px; }}
  .header .sub {{ color: #888; font-size: 13px; margin-top: 5px; }}
  .header .hint {{ color: #4fc3f7; font-size: 13px; margin-top: 3px; }}
  
  /* 大盘横条 */
  .market-bar {{ display: flex; gap: 20px; padding: 12px 30px; background: #0f1923; border-bottom: 1px solid #1a2a3a; align-items: center; flex-wrap: wrap; }}
  .market-bar .mood {{ color: {mood_color}; font-weight: bold; font-size: 15px; }}
  .market-bar .idx {{ font-size: 14px; }}
  .market-bar .idx .val {{ margin-left: 5px; }}
  .market-bar .updated {{ color: #666; font-size: 12px; margin-left: auto; }}
  .up {{ color: #ff4757; }}
  .down {{ color: #2ed573; }}
  
  /* 4 面板网格 */
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; padding: 16px 30px; }}
  @media (max-width: 900px) {{ .grid {{ grid-template-columns: 1fr; padding: 12px; }} .market-bar {{ padding: 12px; }} .header {{ padding: 15px; }} }}
  
  .card {{ background: #0f1923; border: 1px solid #1a2a3a; border-radius: 12px; overflow: hidden; }}
  .card-header {{ display: flex; align-items: center; justify-content: space-between; padding: 14px 18px; border-bottom: 1px solid #1a2a3a; }}
  .card-header .title {{ font-size: 16px; font-weight: bold; display: flex; align-items: center; gap: 8px; }}
  .badge {{ font-size: 11px; padding: 3px 10px; border-radius: 20px; }}
  .badge-ok {{ background: #1a3a2a; color: #2ed573; border: 1px solid #2ed573; }}
  .badge-wait {{ background: #2a2a1a; color: #ffa502; border: 1px solid #ffa502; }}
  .badge-nope {{ background: #2a1a1a; color: #ff4757; border: 1px solid #ff4757; }}
  .card-body {{ padding: 14px 18px; }}
  .card-body .time {{ color: #666; font-size: 12px; margin-bottom: 8px; }}
  
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ color: #888; padding: 6px 4px; text-align: center; font-weight: normal; border-bottom: 1px solid #1a2a3a; }}
  td {{ padding: 6px 4px; text-align: center; border-bottom: 1px solid #141e2a; }}
  .empty {{ color: #555; text-align: center; padding: 20px; font-size: 13px; }}
  
  /* 交易统计 */
  .stats {{ display: flex; gap: 12px; flex-wrap: wrap; }}
  .stat {{ text-align: center; flex: 1; min-width: 60px; }}
  .stat-num {{ font-size: 20px; font-weight: bold; }}
  .stat-label {{ color: #888; font-size: 11px; margin-top: 2px; }}
  .win {{ color: #2ed573; }}
  .loss {{ color: #ff4757; }}
  
  .footer {{ text-align: center; color: #333; font-size: 11px; padding: 20px; }}
</style>
</head>
<body>

<div class="header">
  <h1>📈 选股系统看板</h1>
  <div class="sub">尾盘买入 · 次日卖出 · 量化筛选 | {today}</div>
  <div class="hint">💡 双击此文件即可打开 · 运行 Python 选股后自动更新</div>
</div>

<div class="market-bar">
  <span>📊 大盘:</span>
  <span class="mood">{mood}</span>
  <span class="idx">上证 <span class="val {'up' if (isinstance(sh, (int,float)) and sh >= 0) or (isinstance(sh, str) and sh and float(sh) >= 0) else 'down'}">{sh}{"%" if sh != "" else ""}</span></span>
  <span class="idx">深证 <span class="val {'up' if (isinstance(sz, (int,float)) and sz >= 0) or (isinstance(sz, str) and sz and float(sz) >= 0) else 'down'}">{sz}{"%" if sz != "" else ""}</span></span>
  <span class="idx">创业板 <span class="val {'up' if (isinstance(cyb, (int,float)) and cyb >= 0) or (isinstance(cyb, str) and cyb and float(cyb) >= 0) else 'down'}">{cyb}{"%" if cyb != "" else ""}</span></span>
  <span class="updated">最后更新: {today} {updated}</span>
</div>

<div class="grid">

  <!-- 面板 1: 早盘选股 -->
  <div class="card">
    <div class="card-header">
      <span class="title">🔍 早盘选股池</span>
      <span class="badge {m_badge}">{m_status}</span>
    </div>
    <div class="card-body">
      <div class="time">⏰ 运行时间: 09:35-11:00 {f' | 本次: {m_time}' if m_time else ''}</div>
      {m_table}
    </div>
  </div>

  <!-- 面板 2: 尾盘买入 -->
  <div class="card">
    <div class="card-header">
      <span class="title">🎯 尾盘买入候选</span>
      <span class="badge {a_badge}">{a_status}</span>
    </div>
    <div class="card-body">
      <div class="time">⏰ 运行时间: 14:30-14:55 {f' | 本次: {a_time}' if a_time else ''}</div>
      {a_table}
    </div>
  </div>

  <!-- 面板 3: 交易复盘 -->
  <div class="card">
    <div class="card-header">
      <span class="title">📊 交易统计</span>
      <span class="badge {trade_badge}">{trade_status}</span>
    </div>
    <div class="card-body">
      <div class="time">📅 最近 30 天</div>
      <div class="stats">
        <div class="stat"><div class="stat-num">{total}</div><div class="stat-label">总交易</div></div>
        <div class="stat"><div class="stat-num win">{wins}</div><div class="stat-label">盈利</div></div>
        <div class="stat"><div class="stat-num loss">{losses}</div><div class="stat-label">亏损</div></div>
        <div class="stat"><div class="stat-num">{win_rate}%</div><div class="stat-label">胜率</div></div>
        <div class="stat"><div class="stat-num {'win' if avg_p >= 0 else 'loss'}">{avg_p:+.2f}%</div><div class="stat-label">平均收益</div></div>
        <div class="stat"><div class="stat-num {'win' if t_profit >= 0 else 'loss'}">{t_profit:+.2f}%</div><div class="stat-label">累计收益</div></div>
      </div>
    </div>
  </div>

  <!-- 面板 4: 操作指南 -->
  <div class="card">
    <div class="card-header">
      <span class="title">📋 今日操作指南</span>
      <span class="badge badge-wait">💡 参考</span>
    </div>
    <div class="card-body" style="font-size: 13px; line-height: 1.8;">
      <div class="time">⏰ 当前: {now.strftime('%H:%M')}</div>
      <table>
        <tr><td>⏰</td><td>09:35</td><td>运行早盘选股</td><td><code>python main.py morning</code></td></tr>
        <tr><td>👀</td><td>09:35-11:30</td><td>跟踪候选股</td><td style="color:#888">人工观察</td></tr>
        <tr><td>🎯</td><td>14:30</td><td>尾盘买入确认</td><td><code>python main.py afternoon</code></td></tr>
        <tr><td>💰</td><td>14:50-14:55</td><td>分批买入</td><td><code>python main.py buy 代码 价格</code></td></tr>
        <tr><td>📈</td><td>次日开盘</td><td>卖出</td><td><code>python main.py sell 代码 价格</code></td></tr>
        <tr><td>📊</td><td>收盘后</td><td>复盘</td><td><code>python main.py review</code></td></tr>
      </table>
      <div style="margin-top: 10px; padding: 8px 12px; background: #1a2a3a; border-radius: 6px; color: #ffd700; font-size: 12px;">
        ⚠️ 纪律守则: 尾盘买入 → 次日开盘卖出 · 亏也要卖 · 不扛单 · 不贪心
      </div>
    </div>
  </div>

</div>

<div class="footer">选股系统 v1.0 · 数据仅供参考 · 投资有风险 · 入市需谨慎</div>

</body>
</html>"""
    
    with open(DASHBOARD_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    
    logger.info(f"看板已更新: {DASHBOARD_HTML}")


def show_daily_checklist():
    """终端操作清单"""
    now = datetime.now()
    current_time = now.strftime("%H:%M")
    
    if now.weekday() >= 5:
        print("  🛑 周末休市\n")
        return
    
    print(f"\n  ⏰ {now.strftime('%Y-%m-%d %H:%M')}")
    print()
    
    if current_time < "09:00":
        print("  🌅 盘前准备")
        print("    · 浏览昨夜重大新闻/公告")
        print("    · 查看外盘（美股、A50期指）")
        print("    · 准备今日观察方向\n")
        print("  📋 等待 09:30 开盘...")
        
    elif current_time < "09:30":
        print("  ⏳ 集合竞价 (09:15-09:25)")
        print("    · 观察持仓竞价情况\n")
        
    elif current_time < "11:30":
        print("  🔍 早盘观察")
        print("    1️⃣  python main.py morning    ← 运行早盘选股")
        print("    2️⃣  跟踪候选股走势")
        print("    3️⃣  缩小候选池到 3-5 只\n")
        
    elif current_time < "13:00":
        print("  ☕ 午间休市")
        print("    · 回顾上午走势")
        
    elif current_time < "14:30":
        print("  👀 下午观察")
        print("    · 监控侯选股，警惕午后跳水")
        
    elif current_time < "15:00":
        print("  🎯 尾盘操作")
        print("    1️⃣  python main.py afternoon    ← 尾盘确认")
        print("    2️⃣  14:50-14:55 分批买入")
        print("    3️⃣  python -c 'from trade_journal import record_buy; ...'")
        print("        记录买入到交易日志\n")
        
    else:
        print("  📊 盘后复盘")
        print("    1️⃣  python main.py review    ← 交易复盘")
        print("    2️⃣  记录今日得失")
        print("    3️⃣  准备明日候选")
    
    print()
