#!/usr/bin/env python
"""
dashboard.py — V2 实时看板
监听 DASHBOARD_PORT (8899)
提供HTML页面显示: 当前持仓、今日候选、win_rate统计、回测概览
数据来自 trade_journal.csv 和 win_rate_data.json
"""
import sys, os, json, csv, logging
from datetime import datetime, date
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from v2.config import DATA_DIR, JOURNAL_PATH, WIN_RATE_DATA, DASHBOARD_PORT

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s %(message)s')
logger = logging.getLogger('dashboard')


# ── 数据加载 ──

def load_journal():
    """读取交易日志"""
    if not os.path.exists(JOURNAL_PATH):
        return []
    with open(JOURNAL_PATH, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader)


def load_win_rate():
    """读取胜率数据"""
    if os.path.exists(WIN_RATE_DATA):
        try:
            with open(WIN_RATE_DATA, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def load_dashboard_data():
    """读取 dashboard_data.json"""
    path = os.path.join(DATA_DIR, "dashboard_data.json")
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def get_positions(trades):
    """获取当前持仓 (已买入未卖出)"""
    positions = []
    for t in trades:
        try:
            sell_price = float(t.get("sell_price", 0)) if t.get("sell_price") else 0
        except (ValueError, TypeError):
            sell_price = 0
        if sell_price == 0:
            positions.append(t)
    return positions


# ── HTML 模板 ──

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>📈 V2 选股系统 - Dashboard</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'Microsoft YaHei', -apple-system, sans-serif; background: #0f0f23; color: #ccd6f6; padding: 20px; }}
  .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; border-bottom: 2px solid #00a8ff; padding-bottom: 12px; }}
  .header h1 {{ font-size: 24px; color: #00a8ff; }}
  .header .time {{ color: #8892b0; font-size: 14px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 16px; }}
  .card {{ background: #1a1a2e; border-radius: 12px; padding: 16px; border: 1px solid #2a2a4a; }}
  .card h2 {{ font-size: 16px; color: #e94560; margin-bottom: 12px; border-bottom: 1px solid #333; padding-bottom: 8px; }}
  .card h3 {{ font-size: 14px; color: #4ecca3; margin: 8px 0; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ text-align: left; padding: 6px 4px; color: #8892b0; border-bottom: 1px solid #333; font-weight: 500; }}
  td {{ padding: 6px 4px; border-bottom: 1px solid #222; }}
  .pos {{ color: #ff6b6b; }}
  .neg {{ color: #4ecca3; }}
  .score {{ color: #ffd93d; }}
  .badge {{ display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 11px; }}
  .badge-green {{ background: rgba(78,204,163,0.2); color: #4ecca3; }}
  .badge-red {{ background: rgba(255,107,107,0.2); color: #ff6b6b; }}
  .badge-yellow {{ background: rgba(255,217,61,0.2); color: #ffd93d; }}
  .stat-row {{ display: flex; gap: 16px; flex-wrap: wrap; }}
  .stat-item {{ flex: 1; min-width: 100px; text-align: center; padding: 8px; }}
  .stat-item .value {{ font-size: 24px; font-weight: bold; }}
  .stat-item .label {{ font-size: 11px; color: #8892b0; margin-top: 4px; }}
  .empty {{ color: #555; text-align: center; padding: 24px; }}
  .footer {{ text-align: center; color: #555; font-size: 12px; margin-top: 24px; padding: 16px; border-top: 1px solid #222; }}
</style>
</head>
<body>
<div class="header">
  <h1>📈 V2 选股系统</h1>
  <div class="time">🕒 {time}</div>
</div>

<div class="grid">
  <!-- 当前持仓 -->
  <div class="card">
    <h2>📋 当前持仓</h2>
    {positions_html}
  </div>

  <!-- 今日候选 -->
  <div class="card">
    <h2>🎯 今日候选</h2>
    {candidates_html}
  </div>

  <!-- 胜率统计 -->
  <div class="card">
    <h2>📊 胜率统计</h2>
    {winrate_html}
  </div>

  <!-- 回测概览 -->
  <div class="card">
    <h2>🔬 回测概览</h2>
    {backtest_html}
  </div>

  <!-- 精选结果 -->
  <div class="card">
    <h2>🏆 尾盘精选</h2>
    {final_picks_html}
  </div>

  <!-- 因子IC -->
  <div class="card">
    <h2>📐 因子IC权重</h2>
    {factor_ic_html}
  </div>
</div>

<div class="footer">
  V2 定时推送系统 · 数据自动更新 · 持仓数据来自 trade_journal.csv
</div>
</body>
</html>"""


def build_positions_html(trades):
    positions = get_positions(trades)
    if not positions:
        return '<div class="empty">📭 当前无持仓</div>'

    rows = ""
    for p in positions:
        rows += f"""<tr>
            <td>{p.get('code','')}</td>
            <td>{p.get('name','')}</td>
            <td>{p.get('buy_price','N/A')}</td>
            <td class="pos">{p.get('buy_reason','')}</td>
        </tr>"""

    return f"""<table>
        <tr><th>代码</th><th>名称</th><th>买入价</th><th>理由</th></tr>
        {rows}
    </table>
    <p style="color:#8892b0; margin-top:8px;">共 {len(positions)} 只持仓</p>"""


def build_candidates_html(dash_data):
    morning = dash_data.get("morning", {})
    candidates = morning.get("candidates", [])
    verify = dash_data.get("verify", {})

    if not candidates:
        return '<div class="empty">📭 今日暂无候选</div>'

    rows = ""
    for c in candidates:
        rows += f"""<tr>
            <td>{c.get('code','')}</td>
            <td>{c.get('name','')}</td>
            <td class="{'pos' if c.get('change_pct',0)>=0 else 'neg'}">{c.get('change_pct',0):+.2f}%</td>
            <td class="score">{c.get('strategy_total',0):.1f}</td>
            <td>{c.get('industry','')}</td>
        </tr>"""

    html = f"""<table>
        <tr><th>代码</th><th>名称</th><th>涨幅</th><th>策略分</th><th>行业</th></tr>
        {rows}
    </table>"""

    if verify.get("candidates"):
        html += f'<p style="color:#4ecca3; margin-top:8px;">✅ 已通过14:45验证: {len(verify.get("candidates",[]))} 只</p>'

    return html


def build_winrate_html(wr_data):
    if not wr_data:
        return '<div class="empty">📭 暂无胜率数据</div>'

    cum = wr_data.get("cumulative", {})
    today_data = wr_data.get("today", {})
    history = wr_data.get("history", [])

    wr = cum.get("win_rate", 0)
    wr_color = "pos" if wr >= 50 else "neg"

    # 累计统计
    stats = f"""<div class="stat-row">
        <div class="stat-item"><div class="value {wr_color}">{wr:.1f}%</div><div class="label">累计胜率</div></div>
        <div class="stat-item"><div class="value">{cum.get('total_trades',0)}</div><div class="label">总交易</div></div>
        <div class="stat-item"><div class="value {'pos' if cum.get('total_profit',0)>=0 else 'neg'}">{cum.get('total_profit',0):+.2f}%</div><div class="label">累计收益</div></div>
    </div>"""

    # 今日数据
    if today_data:
        td = today_data
        stats += f"""<h3>今日结算</h3>
        <div class="stat-row">
            <div class="stat-item"><div class="value">{td.get('total',0)}</div><div class="label">交易笔数</div></div>
            <div class="stat-item"><div class="value pos">{td.get('wins',0)}</div><div class="label">盈利</div></div>
            <div class="stat-item"><div class="value neg">{td.get('losses',0)}</div><div class="label">亏损</div></div>
            <div class="stat-item"><div class="value {'pos' if td.get('avg_profit',0)>=0 else 'neg'}">{td.get('avg_profit',0):+.2f}%</div><div class="label">平均收益</div></div>
        </div>"""

    # 近5日趋势
    recent = history[-5:] if len(history) >= 5 else history
    if recent:
        trend_rows = ""
        for r in recent:
            wr_v = r.get("win_rate", 0)
            emoji = "🟢" if wr_v >= 50 else "🔴"
            trend_rows += f"""<tr>
                <td>{r.get('date','')}</td>
                <td>{r.get('total',0)}</td>
                <td>{r.get('wins',0)}/{r.get('losses',0)}</td>
                <td class="{'pos' if wr_v>=50 else 'neg'}">{emoji} {wr_v:.1f}%</td>
                <td class="{'pos' if r.get('avg_profit',0)>=0 else 'neg'}">{r.get('avg_profit',0):+.2f}%</td>
            </tr>"""
        stats += f"""<h3>近5日趋势</h3>
        <table>
            <tr><th>日期</th><th>笔数</th><th>胜/负</th><th>胜率</th><th>平均收益</th></tr>
            {trend_rows}
        </table>"""

    return stats


def build_backtest_html(dash_data):
    """回测概览 - 从 dashboard_data 读取 (如果有)"""
    # 目前无专用回测数据, 显示基础信息
    return """<div class="stat-row">
        <div class="stat-item"><div class="value">3</div><div class="label">最大持仓</div></div>
        <div class="stat-item"><div class="value">80%</div><div class="label">总仓位</div></div>
        <div class="stat-item"><div class="value neg">-3.0%</div><div class="label">止损线</div></div>
    </div>
    <p style="color:#555; margin-top:8px;">运行 <code>python backtest.py</code> 查看详细回测结果</p>"""


def build_final_picks_html(dash_data):
    final = dash_data.get("final_picks", {})
    picks = final.get("picks", [])
    if not picks:
        return '<div class="empty">🏆 今日尚未精选</div>'

    rows = ""
    for p in picks:
        kp = p.get("kelly_pct", 0)
        rows += f"""<tr>
            <td>{p.get('code','')}</td>
            <td>{p.get('name','')}</td>
            <td class="{'pos' if p.get('change_pct',0)>=0 else 'neg'}">{p.get('change_pct',0):+.2f}%</td>
            <td>{p.get('industry','')}</td>
            <td class="score">{p.get('final_score',0)}</td>
            <td>{kp:.1f}%</td>
        </tr>"""

    return f"""<table>
        <tr><th>代码</th><th>名称</th><th>涨幅</th><th>行业</th><th>评分</th><th>Kelly</th></tr>
        {rows}
    </table>
    <p style="color:#8892b0; margin-top:8px;">分散检查: {final.get('diversification','N/A')}</p>"""


def build_factor_ic_html(dash_data):
    """从 factor_ic.json 加载 IC 权重"""
    factor_ic_path = os.path.join(DATA_DIR, "factor_ic.json")
    if not os.path.exists(factor_ic_path):
        return '<div class="empty">📐 因子IC数据尚未生成 (周六运行 compute_factor_ic.py)</div>'

    try:
        with open(factor_ic_path, "r") as f:
            ic_data = json.load(f)
    except Exception:
        return '<div class="empty">📐 因子IC数据读取失败</div>'

    weights = ic_data.get("ic_weights", {})
    ic_values = ic_data.get("ic_values", {})
    days = ic_data.get("trading_days", 0)

    if not weights:
        return '<div class="empty">📐 无IC权重数据</div>'

    # 按权重排序
    sorted_w = sorted(weights.items(), key=lambda x: x[1], reverse=True)

    rows = ""
    for fname, weight in sorted_w:
        ics = ic_values.get(fname, [])
        mean_ic = sum(ics) / len(ics) if ics else 0
        ic_color = "pos" if mean_ic > 0 else "neg"
        rows += f"""<tr>
            <td>{fname}</td>
            <td class="score">{weight:.4f}</td>
            <td class="{ic_color}">{mean_ic:+.4f}</td>
            <td>{len(ics)}</td>
        </tr>"""

    return f"""<p style="color:#8892b0;">交易日: {days} 天 | 因子数: {len(weights)}</p>
    <table>
        <tr><th>因子</th><th>权重</th><th>平均IC</th><th>天数</th></tr>
        {rows}
    </table>"""


# ── HTTP Handler ──

class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/":
            self.handle_dashboard()
        elif path == "/api/data":
            self.handle_api_data()
        elif path == "/api/positions":
            self.handle_api_positions()
        elif path == "/api/candidates":
            self.handle_api_candidates()
        elif path == "/api/winrate":
            self.handle_api_winrate()
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"404 Not Found")

    def handle_dashboard(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

        trades = load_journal()
        wr_data = load_win_rate()
        dash_data = load_dashboard_data()

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        html = HTML_TEMPLATE.format(
            time=now,
            positions_html=build_positions_html(trades),
            candidates_html=build_candidates_html(dash_data),
            winrate_html=build_winrate_html(wr_data),
            backtest_html=build_backtest_html(dash_data),
            final_picks_html=build_final_picks_html(dash_data),
            factor_ic_html=build_factor_ic_html(dash_data),
        )
        self.wfile.write(html.encode("utf-8"))

    def _send_json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))

    def handle_api_data(self):
        trades = load_journal()
        wr_data = load_win_rate()
        dash_data = load_dashboard_data()
        self._send_json({
            "positions": get_positions(trades),
            "win_rate": wr_data,
            "dashboard": dash_data,
            "time": datetime.now().isoformat(),
        })

    def handle_api_positions(self):
        trades = load_journal()
        positions = get_positions(trades)
        # 检查是否有当日quote数据
        for p in positions:
            p["current_price"] = None  # 需要从实时行情获取
        self._send_json({"positions": positions, "count": len(positions)})

    def handle_api_candidates(self):
        dash_data = load_dashboard_data()
        morning = dash_data.get("morning", {})
        candidates = morning.get("candidates", [])
        self._send_json({"candidates": candidates, "count": len(candidates)})

    def handle_api_winrate(self):
        wr_data = load_win_rate()
        self._send_json(wr_data)

    def log_message(self, format, *args):
        logger.info(f"{self.client_address[0]} - {format % args}")


def main():
    port = DASHBOARD_PORT
    server = HTTPServer(("0.0.0.0", port), DashboardHandler)
    logger.info(f"📈 Dashboard running at http://localhost:{port}")
    logger.info(f"   API: http://localhost:{port}/api/data")
    logger.info(f"   Press Ctrl+C to stop")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down dashboard...")
        server.shutdown()


if __name__ == "__main__":
    main()
