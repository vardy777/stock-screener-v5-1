"""
V3 完整模拟交易看板 — 深色交易终端风格

启动: python main.py v3-dashboard
访问: http://localhost:8898

数据源: SimulationEngine (包装 SimAccount + BuyDecision + MarketState)

API:
  GET /              → 主页面 HTML
  GET /api/state     → JSON 模拟状态
  GET /api/run_buy   → 执行买入
  GET /api/run_sell  → 执行卖出
  GET /api/reset     → 重置模拟
"""
import sys
import os
import json
import csv
import logging
import secrets
from datetime import datetime, date
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from v3.simulation import SimulationEngine
from v3.pullback import PullbackEngine
from strategy_spec import DEFAULT_SPEC, TradeCostModel

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(name)s] %(levelname)s %(message)s')
logger = logging.getLogger('v3_dashboard')

PORT = 8898
HOST = '127.0.0.1'
PROJECT_ROOT = Path(__file__).resolve().parent.parent
OVERNIGHT_REPORT_ROOT = PROJECT_ROOT / 'phase1' / 'data' / 'overnight'
MUTATION_TOKEN = secrets.token_urlsafe(24)

# ═══════════════════════════════════════════════════════════════
# CSS — 专业深色交易终端 (A 股红涨绿跌)
# ═══════════════════════════════════════════════════════════════

CSS = r"""
* { margin:0; padding:0; box-sizing:border-box; }
body {
  font-family:'Microsoft YaHei','PingFang SC',-apple-system,'Segoe UI',sans-serif;
  background:#0a0e17; color:#c8d6e5; padding:16px; min-height:100vh;
}
::-webkit-scrollbar { width:6px; }
::-webkit-scrollbar-track { background:#131a2a; }
::-webkit-scrollbar-thumb { background:#2a3a5a; border-radius:3px; }

/* ── Top Bar ── */
.top-bar {
  display:flex; justify-content:space-between; align-items:center;
  padding:12px 20px;
  background:linear-gradient(135deg,#0f1729 0%,#1a2340 100%);
  border:1px solid #1e3050; border-radius:8px; margin-bottom:16px;
}
.top-bar .logo {
  font-size:18px; font-weight:700; letter-spacing:1px;
}
.top-bar .logo .accent { color:#e94560; }
.top-bar .logo .sub { color:#48dbfb; }
.top-bar .time { font-size:12px; color:#5a7a9a; font-family:'Consolas','Courier New',monospace; }
.top-bar .badge {
  display:inline-block; padding:2px 10px; border-radius:10px;
  font-size:11px; font-weight:600;
}
.badge-on { background:rgba(72,219,251,0.12); color:#48dbfb; }
.badge-off { background:rgba(233,69,96,0.15); color:#e94560; }

/* ── Stats Bar ── */
.stats-bar {
  display:grid;
  grid-template-columns:repeat(auto-fit,minmax(130px,1fr));
  gap:10px; margin-bottom:16px;
}
.stat-card {
  background:linear-gradient(180deg,#0f1729 0%,#0d1322 100%);
  border:1px solid #1a2a44; border-radius:8px; padding:12px 14px;
  text-align:center;
}
.stat-card .label {
  font-size:10px; color:#5a7a9a; text-transform:uppercase;
  letter-spacing:0.5px; margin-bottom:4px;
}
.stat-card .value {
  font-size:20px; font-weight:700;
  font-family:'Consolas','Courier New',monospace;
}
.stat-card .value.small { font-size:16px; }
.stat-card.primary {
  background:linear-gradient(135deg,#0f1f3a 0%,#162540 100%);
  border-color:#2a4a7a;
}
.stat-card.primary .value { font-size:24px; }

/* A 股红涨绿跌 */
.red  { color:#ff6b6b; }   /* 涨 = 红 */
.green { color:#4ecca3; }  /* 跌 = 绿 */
.blue  { color:#48dbfb; }
.yellow { color:#ffd93d; }
.muted { color:#5a7a9a; }

/* ── Grid ── */
.grid { display:grid; gap:14px; margin-bottom:16px; }
.grid-2 { grid-template-columns:1fr; }
.grid-3 { grid-template-columns:1fr; }
@media(min-width:1000px){ .grid-2{grid-template-columns:1fr 1fr;} }
@media(min-width:1200px){ .grid-3{grid-template-columns:1fr 1fr 1fr;} }

/* ── Card ── */
.card {
  background:linear-gradient(180deg,#0f1729 0%,#0d1322 100%);
  border:1px solid #1a2a44; border-radius:8px; overflow:hidden;
}
.card-header {
  display:flex; justify-content:space-between; align-items:center;
  padding:10px 16px;
  background:linear-gradient(90deg,#131f35 0%,#0f1729 100%);
  border-bottom:1px solid #1a2a44;
  font-size:13px; font-weight:600;
  color:#48dbfb; letter-spacing:0.5px;
}
.card-header .icon { margin-right:6px; }
.card-header .badge-sm {
  font-size:10px; font-weight:400; color:#5a7a9a;
}
.card-body { padding:12px 16px 16px; }

/* ── Table ── */
.table-wrap { overflow-x:auto; }
table { width:100%; border-collapse:collapse; font-size:12px; min-width:600px; }
thead th {
  text-align:left; padding:8px 10px; color:#5a7a9a; font-weight:500; font-size:11px;
  border-bottom:1px solid #1a2a44; white-space:nowrap;
}
tbody td {
  padding:7px 10px; border-bottom:1px solid #0f1a2a;
  white-space:nowrap; font-family:'Consolas','Courier New',monospace; font-size:12px;
}
tbody tr:nth-child(even) { background:rgba(15,23,41,0.4); }
tbody tr:hover { background:rgba(72,219,251,0.06); }
.code-link { color:#48dbfb; text-decoration:none; }
.code-link:hover { text-decoration:underline; }

/* ── Tags ── */
.tag {
  display:inline-block; padding:1px 7px; border-radius:3px;
  font-size:10px; font-weight:600;
}
.tag-buy { background:rgba(255,107,107,0.15); color:#ff6b6b; }
.tag-sell { background:rgba(78,204,163,0.15); color:#4ecca3; }
.tag-hold { background:rgba(72,219,251,0.12); color:#48dbfb; }
.tag-top3 { background:rgba(233,69,96,0.15); color:#e94560; }
.tag-cand { background:rgba(255,217,61,0.12); color:#ffd93d; }

/* ── Watchlist Card ── */
.watch-grid {
  display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr));
  gap:10px; margin-bottom:16px;
}
@media(min-width:1200px){ .watch-grid{grid-template-columns:repeat(4,1fr);} }
@media(min-width:900px) and (max-width:1199px){ .watch-grid{grid-template-columns:repeat(3,1fr);} }
.watch-card {
  background:linear-gradient(180deg,#0f1729 0%,#0d1322 100%);
  border:1px solid #1a2a44; border-radius:8px; padding:12px;
  transition:border-color 0.2s;
}
.watch-card:hover { border-color:#2a4a6a; }
.watch-card.risk-high { border-left:3px solid #e94560; }
.watch-card.risk-medium { border-left:3px solid #ffd93d; }
.watch-card.risk-low { border-left:3px solid #48dbfb; }
.watch-card .w-name {
  font-size:13px; font-weight:600; margin-bottom:4px;
  display:flex; justify-content:space-between; align-items:center;
}
.watch-card .w-price {
  font-size:18px; font-weight:700; font-family:'Consolas',monospace;
}
.watch-card .w-change { font-size:12px; font-weight:600; }
.watch-card .w-meta {
  font-size:10px; color:#5a7a9a; margin:4px 0;
  display:flex; gap:8px; flex-wrap:wrap;
}
.watch-card .w-action {
  font-size:11px; padding:4px 0; margin-top:4px;
  border-top:1px solid #0f1a2a;
}
.watch-badge {
  display:inline-block; padding:1px 6px; border-radius:3px;
  font-size:9px; font-weight:600;
}
.watch-badge.buy { background:rgba(78,204,163,0.15); color:#4ecca3; }
.watch-badge.hold { background:rgba(72,219,251,0.12); color:#48dbfb; }
.watch-badge.reduce { background:rgba(255,165,0,0.15); color:#ffa500; }
.watch-badge.sell { background:rgba(233,69,96,0.15); color:#e94560; }
.watch-badge.watch { background:rgba(100,100,120,0.15); color:#888; }
.watch-stats {
  display:flex; gap:12px; margin-bottom:12px; font-size:11px;
  color:#64748b;
}
.watch-stats .stat-item { }
.watch-stats .stat-val { font-weight:600; }

/* ── Position Card ── */
.pos-grid { display:grid; grid-template-columns:1fr; gap:10px; }
@media(min-width:600px){ .pos-grid{grid-template-columns:1fr 1fr;} }
@media(min-width:900px){ .pos-grid{grid-template-columns:1fr 1fr 1fr;} }
.pos-card {
  background:#0d1525; border-radius:6px; padding:12px;
  border:1px solid #15223a;
}
.pos-card .code-row {
  display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;
}
.pos-card .code { font-weight:700; font-size:14px; color:#48dbfb; }
.pos-card .name { font-size:11px; color:#5a7a9a; }
.pos-card .row {
  display:flex; justify-content:space-between; font-size:11px; margin:3px 0;
}
.pos-card .row .lbl { color:#5a7a9a; }
.pos-card .row .val { font-family:'Consolas','Courier New',monospace; }

/* ── Empty State ── */
.empty-state {
  text-align:center; padding:24px; color:#2a3a5a; font-size:14px;
}
.empty-state .big { font-size:32px; margin-bottom:8px; }

/* ── Equity Chart (bar) ── */
.chart-wrap { font-family:'Consolas','Courier New',monospace; font-size:11px; line-height:1.5; }
.chart-wrap .bar-row { display:flex; align-items:center; margin:2px 0; }
.chart-wrap .bar-label { color:#5a7a9a; width:75px; text-align:right; padding-right:8px; flex-shrink:0; }
.chart-wrap .bar-track { flex:1; height:16px; background:#0a0e17; border-radius:2px; overflow:hidden; }
.chart-wrap .bar-fill { height:100%; border-radius:2px; transition:width 0.3s; }
.chart-wrap .bar-val { width:65px; text-align:right; padding-left:6px; font-size:10px; flex-shrink:0; }
.chart-wrap .bar-base { color:#5a7a9a; width:8px; text-align:center; flex-shrink:0; }

/* ── Market Status ── */
.mkt-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:8px; }
.mkt-item {
  background:#0d1525; border-radius:6px; padding:10px;
  border:1px solid #15223a; text-align:center;
}
.mkt-item .lbl { font-size:10px; color:#5a7a9a; margin-bottom:3px; }
.mkt-item .val { font-size:16px; font-weight:700; font-family:'Consolas','Courier New',monospace; }

/* ── Buttons ── */
.action-bar {
  display:flex; gap:10px; flex-wrap:wrap; margin-bottom:16px;
}
.btn {
  padding:8px 20px; border:none; border-radius:6px;
  font-size:13px; font-weight:600; cursor:pointer; transition:opacity 0.2s;
}
.btn:hover { opacity:0.85; }
.btn-buy { background:#e94560; color:#fff; }
.btn-sell { background:#4ecca3; color:#0a0e17; }
.btn-reset { background:#1a2a44; color:#c8d6e5; border:1px solid #2a3a5a; }
.btn-refresh { background:#2a3a5a; color:#c8d6e5; border:1px solid #3a4a6a; }
.btn:disabled,.btn-buy-sm:disabled { opacity:.35; cursor:not-allowed; }

/* ── Strategy readiness / research ── */
.readiness {
  display:flex; align-items:flex-start; justify-content:space-between; gap:16px;
  padding:14px 16px; margin-bottom:16px; border-radius:8px;
  background:linear-gradient(135deg,#151b2d 0%,#101827 100%);
  border:1px solid #334155;
}
.readiness.warn { border-left:4px solid #ffd93d; }
.readiness.ok { border-left:4px solid #4ecca3; }
.readiness.danger { border-left:4px solid #e94560; }
.readiness-title { color:#f1f5f9; font-weight:700; font-size:14px; margin-bottom:5px; }
.readiness-copy { color:#94a3b8; font-size:11px; line-height:1.65; }
.status-pill { display:inline-block; white-space:nowrap; padding:5px 10px; border-radius:999px; font-size:10px; font-weight:700; }
.status-pill.warn { color:#ffd93d; background:rgba(255,217,61,.12); }
.status-pill.ok { color:#4ecca3; background:rgba(78,204,163,.12); }
.status-pill.danger { color:#ff6b6b; background:rgba(255,107,107,.12); }
.research-metrics { display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); gap:8px; }
.research-metric { background:#0b1322; border:1px solid #17243a; border-radius:6px; padding:10px; }
.research-metric .k { color:#64748b; font-size:10px; margin-bottom:5px; }
.research-metric .v { color:#e2e8f0; font:700 17px Consolas,monospace; }
.check-list { display:grid; gap:7px; font-size:11px; }
.check-item { display:flex; justify-content:space-between; gap:10px; padding-bottom:6px; border-bottom:1px solid #142036; }
.check-pass { color:#4ecca3; }
.check-fail { color:#ff6b6b; }
.section-note { color:#64748b; font-size:10px; line-height:1.55; margin-top:8px; }

/* ── Mode Toggle ── */
.btn-mode-group {
  display:inline-flex; border-radius:6px; overflow:hidden;
  border:1px solid #2a3a5a; margin-left:auto;
}
.btn-mode {
  padding:8px 18px; border:none; font-size:12px; font-weight:600;
  cursor:pointer; transition:all 0.2s; color:#5a7a9a;
  background:#0f1729;
}
.btn-mode.active-chase {
  background:#e94560; color:#fff;
}
.btn-mode.active-pullback {
  background:#2a6cb8; color:#fff;
}
.btn-mode:not(.active-chase):not(.active-pullback):hover {
  background:#1a2840; color:#c8d6e5;
}

/* ── Toast ── */
.toast {
  position:fixed; top:20px; right:20px; padding:12px 20px;
  border-radius:6px; font-size:13px; font-weight:500; z-index:999;
  animation:slideIn 0.3s ease;
}
.toast-success { background:rgba(78,204,163,0.9); color:#0a0e17; }
.toast-error { background:rgba(233,69,96,0.9); color:#fff; }
.toast-info { background:rgba(72,219,251,0.9); color:#0a0e17; }
@keyframes slideIn { from{transform:translateX(100%);opacity:0;} to{transform:translateX(0);opacity:1;} }

/* 勾选买入按钮 */
.btn-buy-sm {
  background:rgba(255,107,107,0.12); color:#ff6b6b; border:1px solid rgba(255,107,107,0.3);
  padding:4px 12px; border-radius:4px; font-size:11px; cursor:pointer; font-family:inherit;
}
.btn-buy-sm:hover { background:rgba(255,107,107,0.25); }
.cand-check { width:16px; height:16px; cursor:pointer; accent-color:#ff6b6b; }

/* ── Footer ── */
.footer {
  text-align:center; color:#1a2a44; font-size:11px;
  margin-top:20px; padding:12px; border-top:1px solid #0f1a2a;
}
"""


# ═══════════════════════════════════════════════════════════════
# HTML 构建函数
# ═══════════════════════════════════════════════════════════════

def _css_class(val: float) -> str:
    """A 股: 涨(正)用红色, 跌(负)用绿色"""
    if val > 0:
        return 'red'
    elif val < 0:
        return 'green'
    return 'blue'


def _fmt(val, suffix='') -> str:
    """格式化数字"""
    if isinstance(val, float):
        return f'{val:,.2f}{suffix}'
    return f'{val}{suffix}'


def _fmt_pct(val) -> str:
    return f'{val:+.2f}%'


def _load_json(path: Path, default):
    try:
        with Path(path).open('r', encoding='utf-8') as handle:
            return json.load(handle)
    except (OSError, ValueError, TypeError):
        return default


def _load_research_status() -> dict:
    """Load the newest normal-cost walk-forward report for the dashboard."""

    report_dirs = [
        OVERNIGHT_REPORT_ROOT / 'wf_report',
        OVERNIGHT_REPORT_ROOT / 'wf_report_smoke_optimized',
        OVERNIGHT_REPORT_ROOT / 'wf_report_smoke',
    ]
    available = [path for path in report_dirs if (path / 'summary.json').exists()]
    if not available:
        return {
            'available': False,
            'research_only': True,
            'acceptance_pass': False,
            'summary': {},
            'coverage': [],
            'report_name': '尚无报告',
        }

    # Prefer a full-universe report when present; otherwise use the latest smoke run.
    report_dir = available[0]
    summary_path = report_dir / 'summary.json'
    summary = _load_json(summary_path, {})
    stress_candidates = [
        OVERNIGHT_REPORT_ROOT / 'wf_report_stress' / 'summary.json',
        OVERNIGHT_REPORT_ROOT / 'wf_report_smoke_optimized_stress' / 'summary.json',
        OVERNIGHT_REPORT_ROOT / 'wf_report_smoke_stress' / 'summary.json',
    ]
    stress_summary = {}
    for stress_path in stress_candidates:
        if stress_path.exists():
            stress_summary = _load_json(stress_path, {})
            break
    coverage = []
    coverage_path = report_dir / 'precision_coverage.csv'
    if coverage_path.exists():
        try:
            with coverage_path.open('r', encoding='utf-8-sig', newline='') as handle:
                coverage = list(csv.DictReader(handle))
        except OSError:
            coverage = []

    return {
        'available': True,
        'research_only': bool(summary.get('research_only', True)),
        'acceptance_pass': bool(summary.get('acceptance_pass', False)),
        'summary': summary,
        'stress_summary': stress_summary,
        'coverage': coverage,
        'report_name': report_dir.name,
        'updated_at': datetime.fromtimestamp(summary_path.stat().st_mtime).strftime(
            '%Y-%m-%d %H:%M'
        ),
    }


def _load_fund_flow_summary() -> dict:
    raw = _load_json(PROJECT_ROOT / 'v3' / 'data' / 'sector_fund_flow.json', {})
    flows = raw.get('sector_flows', {}) if isinstance(raw, dict) else {}
    rows = [
        {'sector': name, **values}
        for name, values in flows.items()
        if isinstance(values, dict)
    ]
    rows.sort(key=lambda item: float(item.get('net_inflow', 0)), reverse=True)
    return {'top': rows[:5], 'time': raw.get('time', '') if isinstance(raw, dict) else ''}


def _build_coverage_html(rows: list) -> str:
    if not rows:
        return '<div class="empty-state">下次滚动回测后生成精度—覆盖率曲线</div>'
    body = []
    names = {
        'selection_score': '联合置信度',
        'predicted_return': '预测净收益',
        'predicted_positive_probability': '净盈利概率',
    }
    for row in rows:
        try:
            body.append(
                '<tr>'
                f'<td>{names.get(row.get("ranking_signal"), row.get("ranking_signal", "--"))}</td>'
                f'<td>Top {float(row.get("top_fraction", 0))*100:.0f}%</td>'
                f'<td>{int(float(row.get("trades", 0)))}</td>'
                f'<td>{float(row.get("win_rate", 0))*100:.1f}%</td>'
                f'<td>{float(row.get("target_1pct_rate", 0))*100:.1f}%</td>'
                f'<td>{float(row.get("average_net_return", 0))*100:+.3f}%</td>'
                f'<td>{float(row.get("profit_factor", 0)):.2f}</td>'
                '</tr>'
            )
        except (TypeError, ValueError):
            continue
    return (
        '<div class="table-wrap"><table><thead><tr>'
        '<th>排序信号</th><th>覆盖范围</th><th>交易数</th><th>净盈利胜率</th>'
        '<th>达到1%</th><th>平均净收益</th><th>PF</th></tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div>'
    )


def _build_research_html(research: dict) -> str:
    if not research.get('available'):
        return """
        <div class="readiness danger">
          <div><div class="readiness-title">尚无可用的滚动回测报告</div>
          <div class="readiness-copy">模拟看板可以查看，但策略不具备任何实盘准入依据。</div></div>
          <span class="status-pill danger">实盘锁定</span>
        </div>"""

    summary = research.get('summary', {})
    stress = research.get('stress_summary', {})
    research_only = research.get('research_only', True)
    accepted = research.get('acceptance_pass', False)
    if accepted:
        status_class, status_text = 'ok', '通过研究门槛'
        title = '滚动样本外验证已达到候选准入条件'
    elif research_only:
        status_class, status_text = 'warn', '代理数据 · 仅研究'
        title = '当前仍使用15:00代理14:50成交，禁止据此进入实盘'
    else:
        status_class, status_text = 'danger', '验证未通过'
        title = '样本外指标未达到准入门槛，保持模拟运行'

    win = float(summary.get('win_rate', 0)) * 100
    win_low = float(summary.get('win_rate_ci_low_95', 0)) * 100
    hit = float(summary.get('target_1pct_rate', 0)) * 100
    avg = float(summary.get('average_net_return', 0)) * 100
    drawdown = float(summary.get('max_drawdown', 0)) * 100
    pf = float(summary.get('profit_factor', 0))
    consistency = float(summary.get('window_consistency', 0)) * 100
    trades = int(summary.get('trades', 0))
    stress_return = float(stress.get('cumulative_return', 0)) * 100
    strict_rows = int(summary.get('strict_1450_rows', 0))

    checks = [
        ('严格14:50样本', strict_rows > 0, f'{strict_rows:,} 行'),
        ('交易样本≥500', trades >= 500, f'{trades:,} 笔'),
        ('胜率95%下限>50%', win_low > 50, f'{win_low:.1f}%'),
        ('Profit Factor≥1.20', pf >= 1.20, f'{pf:.2f}'),
        ('加倍滑点后仍盈利', bool(stress) and stress_return > 0, f'{stress_return:+.2f}%'),
        ('盈利窗口≥70%', consistency >= 70, f'{consistency:.1f}%'),
        ('最大回撤≤12%', drawdown >= -12, f'{drawdown:.1f}%'),
    ]
    check_html = ''.join(
        f'<div class="check-item"><span>{label}</span>'
        f'<span class="{"check-pass" if passed else "check-fail"}">'
        f'{"✓" if passed else "×"} {value}</span></div>'
        for label, passed, value in checks
    )
    coverage_html = _build_coverage_html(research.get('coverage', []))

    return f"""
    <div class="readiness {status_class}">
      <div>
        <div class="readiness-title">{title}</div>
        <div class="readiness-copy">报告 {research.get('report_name','--')} · 更新 {research.get('updated_at','--')} · 自动调节交易覆盖率，允许无信号日空仓。</div>
      </div>
      <span class="status-pill {status_class}">{status_text}</span>
    </div>
    <div class="grid grid-2">
      <div class="card">
        <div class="card-header"><span>🧪 样本外表现</span><span class="badge-sm">扣除费用与滑点</span></div>
        <div class="card-body">
          <div class="research-metrics">
            <div class="research-metric"><div class="k">净盈利胜率</div><div class="v">{win:.1f}%</div></div>
            <div class="research-metric"><div class="k">胜率95%下限</div><div class="v">{win_low:.1f}%</div></div>
            <div class="research-metric"><div class="k">净收益≥1%</div><div class="v">{hit:.1f}%</div></div>
            <div class="research-metric"><div class="k">平均净收益/笔</div><div class="v">{avg:+.3f}%</div></div>
            <div class="research-metric"><div class="k">Profit Factor</div><div class="v">{pf:.2f}</div></div>
            <div class="research-metric"><div class="k">最大回撤</div><div class="v">{drawdown:.1f}%</div></div>
            <div class="research-metric"><div class="k">加倍滑点收益</div><div class="v">{stress_return:+.2f}%</div></div>
          </div>
          <div class="section-note">胜率指扣除所有费用后的净盈利概率；“达到1%”单独统计，不与胜率混用。</div>
        </div>
      </div>
      <div class="card">
        <div class="card-header"><span>🛡️ 策略准入检查</span><span class="badge-sm">必须全部通过</span></div>
        <div class="card-body"><div class="check-list">{check_html}</div></div>
      </div>
    </div>
    <div class="card" style="margin-bottom:16px">
      <div class="card-header"><span>🎚️ 精度—覆盖率</span><span class="badge-sm">越往Top区域越少交易</span></div>
      <div class="card-body">{coverage_html}</div>
    </div>"""


def _build_v4_status_html(v4: dict) -> str:
    readiness = v4.get('readiness', {})
    clock = v4.get('clock', {})
    buy = clock.get('buy', {})
    sell = clock.get('sell', {})
    status = readiness.get('status', 'research_locked')
    status_class = 'ok' if readiness.get('trade_enabled') else 'warn'
    checks = readiness.get('checks', [])
    passed = sum(1 for check in checks if check.get('passed'))
    total = len(checks)
    scheduler_ok = v4.get('scheduler_contract_preserved', False)
    return f"""
    <div class="readiness {status_class}">
      <div>
        <div class="readiness-title">{readiness.get('headline','V4状态不可用')}</div>
        <div class="readiness-copy">
          版本 {v4.get('system_version','V4')} · 准入 {passed}/{total} ·
          买入：{buy.get('reason','--')} · 卖出：{sell.get('reason','--')}<br>
          下一步：{readiness.get('next_action','继续积累独立样本')}<br>
          账户与交易记录沿用旧版模拟数据，不代表V4独立绩效
        </div>
      </div>
      <div style="display:grid;gap:6px;text-align:right">
        <span class="status-pill {status_class}">{status.upper()}</span>
        <span class="status-pill {'ok' if scheduler_ok else 'danger'}">{'原推送链路已兼容' if scheduler_ok else '推送链路异常'}</span>
      </div>
    </div>"""


def _build_stats_bar(acct: dict) -> str:
    r = acct['total_return_pct']
    t = acct['today_pnl_pct']
    return f"""
    <div class="stats-bar">
      <div class="stat-card primary">
        <div class="label">可用资金(下次买入基准)</div>
        <div class="value {_css_class(r)}">¥{_fmt(acct['current_capital'])}</div>
      </div>
      <div class="stat-card">
        <div class="label">总权益(现金+持仓)</div>
        <div class="value small {_css_class(r)}">¥{_fmt(acct['total_equity'])}</div>
      </div>
      <div class="stat-card">
        <div class="label">历史模拟累计盈亏</div>
        <div class="value {_css_class(r)}">{_fmt_pct(r)}</div>
      </div>
      <div class="stat-card">
        <div class="label">初始本金(不变)</div>
        <div class="value small muted">¥{_fmt(acct['initial_capital'])}</div>
      </div>
      <div class="stat-card">
        <div class="label">今日盈亏</div>
        <div class="value {_css_class(t)}">{_fmt_pct(t)}</div>
      </div>
      <div class="stat-card">
        <div class="label">持仓市值</div>
        <div class="value small blue">¥{_fmt(acct['position_market_value'])}</div>
      </div>
      <div class="stat-card">
        <div class="label">持仓数</div>
        <div class="value small blue">{acct['position_count']}</div>
      </div>
      <div class="stat-card">
        <div class="label">历史模拟交易</div>
        <div class="value small blue">{acct['total_trades']}</div>
      </div>
      <div class="stat-card">
        <div class="label">历史模拟胜率</div>
        <div class="value small {_css_class(acct['win_rate'] - 50)}">{acct['win_rate']:.1f}%</div>
      </div>
      <div class="stat-card">
        <div class="label">最大回撤</div>
        <div class="value small green">{_fmt_pct(-acct['max_drawdown_pct'])}</div>
      </div>
    </div>"""


def _build_positions_html(positions: list) -> str:
    if not positions:
        return '<div class="empty-state"><div class="big">📭</div>当日无持仓</div>'
    cards = []
    for p in positions:
        cls = _css_class(p['pnl_pct'])
        c = f"""
    <div class="pos-card">
      <div class="code-row">
        <div>
          <span class="code">{p['code']}</span>
          <span class="name"> {p['name']}</span>
        </div>
        <span class="tag tag-{'buy' if p['pnl_pct']>=0 else 'sell'}">{_fmt_pct(p['pnl_pct'])}</span>
      </div>
      <div class="row"><span class="lbl">买入价</span><span class="val">¥{_fmt(p['buy_price'])}</span></div>
      <div class="row"><span class="lbl">数量</span><span class="val">{p['shares']} 股</span></div>
      <div class="row"><span class="lbl">现价</span><span class="val {cls}">¥{_fmt(p['current_price'])}</span></div>
      <div class="row"><span class="lbl">盈亏金额</span><span class="val {cls}">¥{_fmt(p['pnl_amount'])}</span></div>
      <div class="row"><span class="lbl">买入日</span><span class="val muted">{p.get('buy_date','--')}</span></div>
      <div class="row"><span class="lbl">目标</span><span class="val blue">¥{_fmt(p['target_sell'])}</span></div>
      <div class="row"><span class="lbl">止损</span><span class="val green">¥{_fmt(p['stop_loss'])}</span></div>
    </div>"""
        cards.append(c)
    return '<div class="pos-grid">' + ''.join(cards) + '</div>'


def _build_candidates_html(candidates: list, mode: str = 'chase') -> str:
    if not candidates:
        return '<div class="empty-state"><div class="big">📋</div>今日无候选</div>'
    
    is_pullback = mode == 'pullback'
    
    rows = []
    for c in candidates:
        top3 = c.get('rank', 99) <= 3
        st = c.get('strategy', '追高')
        strat_badge = '<span style=\"background:rgba(255,107,107,0.15);color:#ff6b6b;padding:1px 6px;border-radius:3px;font-size:10px\">追高</span>' if st == '追高' else '<span style=\"background:rgba(72,219,251,0.15);color:#48dbfb;padding:1px 6px;border-radius:3px;font-size:10px\">回调</span>'
        tag = 'tag-top3' if top3 else 'tag-cand'
        label = '🟢 买入' if top3 else '候选'
        # Precision-first default: only the strongest candidate is preselected.
        checked = 'checked' if c.get('rank', 99) == 1 and c.get('v4_tradable') else ''
        v4_decision = c.get('v4_decision', '观察/空仓')
        v4_reasons = '、'.join(c.get('v4_block_reasons', [])) or '通过全部门槛'
        v4_confidence = float(c.get('v4_shadow_confidence', 0.0) or 0.0) * 100
        v4_class = 'tag-buy' if c.get('v4_tradable') else 'tag-hold'
        v4_cell = (
            f'<span class="tag {v4_class}" title="{v4_reasons}">{v4_decision}</span>'
            f'<div style="font-size:9px;color:#64748b;margin-top:3px">影子置信 {v4_confidence:.0f}%</div>'
        )
        
        if is_pullback:
            # 回调模式: 排名, 代码, 名称, 今日跌幅, 5日涨幅, 缩量比, 距MA10, 评分
            pct = c.get('change_pct', c.get('pct_chg', 0))
            near_5d = c.get('near_5d_return', 0)
            vol_r = c.get('volume_ratio', 1.0)
            dist_ma10 = c.get('dist_to_ma10', 0)
            score = c.get('pullback_score', c.get('score', 0))
            rows.append(f"""
        <tr>
          <td><input type="checkbox" class="cand-check" value="{c['code']}" {checked}></td>
          <td><span class="tag {tag}">#{c.get('rank','?')}</span></td>
          <td><a class="code-link" href="javascript:void(0)">{c['code']}</a></td>
          <td>{c['name']}</td>
          <td class="green">{_fmt_pct(pct)}</td>
          <td class="red">{near_5d:+.1f}%</td>
          <td class="{'green' if vol_r < 0.6 else 'blue'}">{vol_r:.2f}x</td>
          <td class="{'blue' if dist_ma10 > 0 else 'green'}">{dist_ma10:+.1f}%</td>
          <td class="yellow">{score:.1f}</td>
          <td>{v4_cell}</td>
          <td>{label}</td>
        </tr>""")
        else:
            # 追高模式: 原有列
            rows.append(f"""
        <tr>
          <td><input type="checkbox" class="cand-check" value="{c['code']}" {checked}></td>
          <td><span class="tag {tag}">#{c.get('rank','?')}</span></td>
          <td><a class="code-link" href="javascript:void(0)">{c['code']}</a></td>
          <td>{c['name']}</td>
          <td class="yellow">{c['score']:.1f}</td>
          <td class="{_css_class(c.get('change_pct',0))}">{_fmt_pct(c.get('change_pct',0))}</td>
          <td class="blue">¥{_fmt(c.get('buy_price',c.get('price',0)))}</td>
          <td>{strat_badge}</td>
          <td>{v4_cell}</td>
        </tr>""")
    
    if is_pullback:
        header = """<thead><tr>
          <th style="width:30px"><input type="checkbox" id="cand-select-all" onchange="toggleAll(this)"></th>
          <th>#</th><th>代码</th><th>名称</th><th>今日跌幅</th><th>5日涨幅</th><th>缩量比</th><th>距MA10</th><th>回调评分</th><th>V4决策</th><th>操作</th>
        </tr></thead>"""
        buy_hint = '<span style="color:#64748b;font-size:11px">默认Top1；缩量与支撑只作解释，不替代准入门槛</span>'
    else:
        header = """<thead><tr>
          <th style="width:30px"><input type="checkbox" id="cand-select-all" onchange="toggleAll(this)"></th>
          <th>#</th><th>代码</th><th>名称</th><th>评分</th><th>涨幅</th><th>建议买入价</th><th>策略</th><th>V4决策</th>
        </tr></thead>"""
        buy_hint = '<span style="color:#64748b;font-size:11px">默认只选择Top1，允许整日空仓</span>'
    
    return f"""
    <div class="table-wrap">
      <table>
        {header}
        <tbody>{''.join(rows)}</tbody>
      </table>
      <div style="margin-top:8px;display:flex;gap:8px;align-items:center">
        {buy_hint}
        <button class="btn btn-buy-sm" onclick="buySelected()">买入勾选的</button>
      </div>
    </div>"""


def _build_trade_history_html(history: list) -> str:
    if not history:
        return '<div class="empty-state"><div class="big">📄</div>暂无交易记录</div>'
    rows = []
    for t in history:
        cls = _css_class(t['pnl_pct'])
        tag = 'tag-buy' if t['pnl_pct'] >= 0 else 'tag-sell'
        rows.append(f"""
        <tr>
          <td>{t.get('date','--')}</td>
          <td><a class="code-link" href="javascript:void(0)">{t['code']}</a></td>
          <td>{t['name']}</td>
          <td>¥{_fmt(t['buy_price'])}</td>
          <td>¥{_fmt(t['sell_price'])}</td>
          <td class="{cls}">{_fmt_pct(t['pnl_pct'])}</td>
          <td class="{cls}">¥{_fmt(t['pnl_amount'])}</td>
          <td><span class="tag {tag}">{'盈利' if t['pnl_pct']>=0 else '亏损'}</span></td>
        </tr>""")
    return f"""
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>日期</th><th>代码</th><th>名称</th><th>买入价</th><th>卖出价</th><th>盈亏%</th><th>盈亏金额</th><th>状态</th>
        </tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </div>"""


def _build_equity_chart_text(records: list, initial_capital: float) -> str:
    """用 bar 字符画每日资金变化图, 显示最近 10-20 条"""
    if not records:
        # 尝试展示初始资金
        return f'<div class="empty-state">暂无每日结算数据</div>'

    # 取最近 15 条
    pts = records[-15:]
    values = [float(r.get('end_capital', initial_capital)) for r in pts]
    labels = [r.get('date', '')[-5:] for r in pts]

    min_v = min(values) if values else initial_capital
    max_v = max(values) if values else initial_capital
    rng = max_v - min_v if max_v > min_v else 1

    lines = []
    max_bar = 40
    for i, v in enumerate(values):
        bar_len = int((v - min_v) / rng * max_bar) if rng > 0 else max_bar // 2
        bar_len = max(1, min(bar_len, max_bar))
        bar = '█' * bar_len
        cls = _css_class(v - initial_capital)
        pct = (v - initial_capital) / initial_capital * 100 if initial_capital > 0 else 0
        lines.append(f"""
    <div class="bar-row">
      <span class="bar-label">{labels[i]}</span>
      <span class="bar-base">│</span>
      <div class="bar-track"><div class="bar-fill {cls}" style="width:{bar_len/max_bar*100}%"></div></div>
      <span class="bar-val {cls}">¥{v:,.0f}</span>
      <span class="bar-val {cls}" style="width:55px;">{pct:+.2f}%</span>
    </div>""")

    return '<div class="chart-wrap">' + ''.join(lines) + '</div>'


def _build_sector_ranks_html(data: dict) -> str:
    top = data.get('top', [])
    bottom = data.get('bottom', [])
    if not top:
        return '<div class="empty-state"><div class="big">📋</div>暂无板块数据</div>'
    rows = []
    for s in top:
        color = '#ff6b6b' if s['avg_pct'] > 0 else '#4ecca3'
        bar_char = '█' * int(max(1, s['avg_pct'] * 3))
        sec_name = s['sector']
        avg = s['avg_pct']
        up_ratio = s['up_ratio']
        rows.append(f'<tr><td>🔥</td><td>{sec_name}</td>'
                    f'<td style="color:{color}">{avg:+.1f}%</td>'
                    f'<td>{up_ratio*100:.0f}%</td>'
                    f'<td style="font-size:8px">{bar_char}</td></tr>')
    html = '<div class="table-wrap"><table><tr><th></th><th>行业</th><th>涨幅</th><th>上涨</th><th>强度</th></tr>'
    html += ''.join(rows)
    html += '</table></div>'
    if bottom:
        html += '<div style="font-size:10px;color:#64748b;margin-top:6px">冷门: '
        html += ', '.join(b['sector'] for b in bottom[:3])
        html += '</div>'
    return html

def _build_fund_flow_html(data: dict) -> str:
    """构建板块资金流 Top 5 显示"""
    top = data.get('top', [])
    if not top:
        return '<div class="empty-state"><div class="big">💰</div>暂无资金流数据</div>'
    rows = []
    for s in top:
        net = s['net_inflow']
        # 颜色: 流入红色, 流出绿色
        color = '#ff6b6b' if net > 0 else '#4ecca3'
        sign = '+' if net > 0 else ''
        bar_char = '█' * int(max(1, min(abs(net) / 5, 20)))
        sec_name = s['sector']
        change = s.get('change_pct', 0)
        chg_color = '#ff6b6b' if change > 0 else '#4ecca3'
        rows.append(f'<tr><td>💰</td><td>{sec_name}</td>'
                    f'<td style="color:{color};font-weight:600">{sign}{net:.1f}亿</td>'
                    f'<td style="color:{chg_color}">{change:+.1f}%</td>'
                    f'<td style="font-size:8px">{bar_char}</td></tr>')
    html = '<div class="table-wrap"><table><tr><th></th><th>行业</th><th>主力净流入</th><th>涨幅</th><th>强度</th></tr>'
    html += ''.join(rows)
    html += '</table></div>'
    return html


def _build_sentiment_html(data: dict) -> str:
    score = data.get('score', 5)
    label = data.get('label', '中性')
    lu = data.get('limit_up', 0)
    ld = data.get('limit_down', 0)
    ur = data.get('up_ratio', 0.5)
    avg = data.get('avg_change', 0)

    # 颜色
    if score >= 6: bar_color = '#ff6b6b'
    elif score >= 4: bar_color = '#fbbf24'
    else: bar_color = '#4ecca3'

    bar = '█' * score + '░' * (10 - score)
    return f'''<div style="text-align:center;padding:8px;">
    <div style="font-size:20px;font-weight:bold;margin-bottom:4px">{label}</div>
    <div style="font-size:28px;color:{bar_color};font-family:Consolas,monospace;margin-bottom:8px">{bar}</div>
    <div style="font-size:12px;color:#94a3b8;margin-bottom:4px">{score}/10</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:11px;color:#64748b">
      <div>涨停 🔴 {lu} 家</div><div>跌停 🟢 {ld} 家</div>
      <div>上涨 {ur*100:.0f}%</div><div>均值 {avg:+.2f}%</div>
    </div>
  </div>'''

def _build_market_state_html(mkt: dict) -> str:
    mode = mkt.get('mode_label', 'neutral')
    mode_colors = {'risk_on': 'red', 'neutral': 'blue', 'risk_off': 'green'}
    mode_color = mode_colors.get(mode, 'muted')

    sh1 = mkt.get('sh_1d_pct', 0)
    sh5 = mkt.get('sh_5d_pct', 0)
    sh20 = mkt.get('sh_20d_pct', 0)
    ar = mkt.get('advance_ratio', 0.5)
    comp = mkt.get('composite', 0)

    return f"""
    <div class="mkt-grid">
      <div class="mkt-item">
        <div class="lbl">市场模式</div>
        <div class="val {mode_color}">{mode.upper()}</div>
      </div>
      <div class="mkt-item">
        <div class="lbl">综合评分</div>
        <div class="val {_css_class(comp)}">{comp:+.1f}</div>
      </div>
      <div class="mkt-item">
        <div class="lbl">上证 1日</div>
        <div class="val {_css_class(sh1)}">{_fmt_pct(sh1)}</div>
      </div>
      <div class="mkt-item">
        <div class="lbl">上证 5日</div>
        <div class="val {_css_class(sh5)}">{_fmt_pct(sh5)}</div>
      </div>
      <div class="mkt-item">
        <div class="lbl">上证 20日</div>
        <div class="val {_css_class(sh20)}">{_fmt_pct(sh20)}</div>
      </div>
      <div class="mkt-item">
        <div class="lbl">上涨占比</div>
        <div class="val {_css_class(ar - 0.5)}">{ar*100:.0f}%</div>
      </div>
    </div>"""


def build_html(state: dict, mode: str = 'chase') -> str:
    acct = state['account']
    mkt = state['market_state']
    now = state['time']
    
    is_pullback = mode == 'pullback'
    mode_badge = '🔵' if is_pullback else '🔴'
    mode_label = '回调买入' if is_pullback else '追高买入'
    chase_active = ' active-chase' if not is_pullback else ''
    pullback_active = ' active-pullback' if is_pullback else ''
    candidate_icon = '📉' if is_pullback else '🎯'
    candidate_title = '回调候选' if is_pullback else '今日候选'
    v4 = state.get('v4', {})
    risk_off = mkt.get('mode_label', 'neutral') == 'risk_off'
    trade_allowed = bool(state.get('trade_allowed', False))
    trade_disabled = '' if trade_allowed else 'disabled'
    if risk_off:
        trade_hint = '市场风险关闭：今日保持空仓'
    elif not v4.get('readiness', {}).get('trade_enabled', False):
        trade_hint = 'V4研究准入未通过：候选仅观察，不产生买单'
    else:
        trade_hint = v4.get('clock', {}).get('buy', {}).get('reason', '等待14:50窗口')

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta id="refresh-meta" http-equiv="refresh" content="60">
<title>隔夜策略控制台 · 模拟</title>
<style>{CSS}</style>
</head>
<body>

<!-- ═══ 顶部栏 ═══ -->
<div class="top-bar">
  <div class="logo">
    <span class="accent">V4 隔夜策略</span>
    <span class="sub">· 研究、风控与模拟控制台</span>
    <span style="font-size:11px;color:#5a7a9a;margin-left:8px;">{mode_badge} {mode_label}</span>
  </div>
  <div>
    <span class="badge badge-on">🟢 模拟</span>
    <span class="time" style="margin-left:12px;">🕒 {now}</span>
  </div>
</div>

<!-- ═══ 操作按钮 ═══ -->
<div class="action-bar">
  <div style="flex:1;display:flex;align-items:center;gap:10px">
    <span style="color:#48dbfb;font-weight:600;font-size:13px">14:50 → 次日09:30后</span>
    <span style="color:#64748b;font-size:11px">{trade_hint}</span>
  </div>
  <div class="btn-mode-group">
    <button class="btn-mode{chase_active}" onclick="switchMode('chase')">综合候选</button>
    <button class="btn-mode{pullback_active}" onclick="switchMode('pullback')">回调候选</button>
  </div>
  <button class="btn btn-sell" onclick="apiCall('/api/run_sell','手动卖出')">卖出持仓</button>
  <button class="btn btn-buy-sm" onclick="buySelected()" {trade_disabled}>模拟买入Top1</button>
  <button class="btn btn-reset" onclick="if(confirm('确认重置模拟账户?'))apiCall('/api/reset','重置')">🔄 重置</button>
  <button class="btn btn-refresh" onclick="location.reload()">🔄 刷新</button>
</div>

<!-- ═══ 顶部资金概览 ═══ -->
{_build_stats_bar(acct)}

<!-- ═══ V4 control plane ═══ -->
{_build_v4_status_html(v4)}

<!-- ═══ Research truth / acceptance gate ═══ -->
{_build_research_html(state.get('research', {}))}

<!-- ═══ Grid: 持仓 + 候选 + 市场 ═══ -->
<div class="grid grid-3">

  <!-- 持仓卡片 -->
  <div class="card">
    <div class="card-header">
      <span><span class="icon">📦</span>当前持仓</span>
      <span class="badge-sm">{acct['position_count']} 只</span>
    </div>
    <div class="card-body">
      {_build_positions_html(state['positions'])}
    </div>
  </div>

  <!-- 今日候选 -->
  <div class="card">
    <div class="card-header">
      <span><span class="icon">{candidate_icon}</span>{candidate_title}</span>
      <span class="badge-sm">Top {len(state['candidates'])}</span>
    </div>
    <div class="card-body">
      <div style="color:#64748b;font-size:10px;margin-bottom:6px">
        🕒 {state.get('time','')} | {mode_label} · 候选数量: {len(state['candidates'])} 只
      </div>
      {_build_candidates_html(state['candidates'], mode)}
    </div>
  </div>

  <!-- 市场状态 -->
  <div class="card">
    <div class="card-header">
      <span><span class="icon">📊</span>市场状态</span>
      <span class="badge-sm">{mkt.get('mode_label','neutral').upper()}</span>
    </div>
    <div class="card-body">
      {_build_market_state_html(mkt)}
    </div>
  </div>
</div>

<!-- ═══ 新增行: 板块热度 + 资金流 + 市场情绪 ═══ -->
<div class="grid grid-3" style="margin-bottom:16px;">

  <!-- 板块热度 Top 5 -->
  <div class="card">
    <div class="card-header">
      <span><span class="icon">🔥</span>板块热度 Top 5</span>
    </div>
    <div class="card-body">
      {_build_sector_ranks_html(state.get('sector_ranks',{}))}
    </div>
  </div>

  <!-- 资金流 Top 5 (P2) -->
  <div class="card">
    <div class="card-header">
      <span><span class="icon">💰</span>资金流 Top 5</span>
    </div>
    <div class="card-body">
      {_build_fund_flow_html(state.get('fund_flow',{}))}
    </div>
  </div>

  <!-- 市场情绪 -->
  <div class="card">
    <div class="card-header">
      <span><span class="icon">😷</span>市场情绪</span>
    </div>
    <div class="card-body">
      {_build_sentiment_html(state.get('sentiment',{}))}
    </div>
  </div>

</div>

<!-- ═══ 资金曲线 ═══ -->
<div class="card" style="margin-bottom:16px;">
  <div class="card-header">
    <span><span class="icon">📈</span>资金曲线 (每日结算)</span>
    <span class="badge-sm">最近 {min(len(state['daily_records']),15)} 条</span>
  </div>
  <div class="card-body">
    {_build_equity_chart_text(state['daily_records'], acct['initial_capital'])}
  </div>
</div>

<!-- ═══ 交易历史 ═══ -->
<div class="card">
  <div class="card-header">
    <span><span class="icon">📋</span>交易历史</span>
    <span class="badge-sm">{len(state['trade_history'])} 笔</span>
  </div>
  <div class="card-body">
    {_build_trade_history_html(state['trade_history'])}
  </div>
</div>

<div class="footer">
  V4本机研究与模拟系统 · 仅监听 localhost · 原定时推送入口保持兼容 · 未通过准入前不产生可执行买单
</div>

<script>
// ── Mode preservation across refreshes ──
(function() {{
  var url = new URL(window.location.href);
  var currentMode = url.searchParams.get('mode');
  var storedMode = sessionStorage.getItem('v3_mode');
  if (!currentMode && storedMode && storedMode !== 'chase') {{
    url.searchParams.set('mode', storedMode);
    window.location.replace(url.toString());
    return;
  }}
  if (currentMode) {{
    sessionStorage.setItem('v3_mode', currentMode);
  }}
}})();

// ── Mode switch ──
function switchMode(mode) {{
  sessionStorage.setItem('v3_mode', mode);
  var url = new URL(window.location.href);
  url.searchParams.set('mode', mode);
  window.location.href = url.toString();
}}

// ── Trading hours check ──
function isTradingHours() {{
  var now = new Date();
  var day = now.getDay();  // 0=Sun, 6=Sat
  if (day === 0 || day === 6) return false;
  var t = now.getHours() * 100 + now.getMinutes();
  return (t >= 928 && t <= 1130) || (t >= 1300 && t <= 1500);
}}

function toggleAll(src) {{
  document.querySelectorAll('.cand-check').forEach(cb => cb.checked = src.checked);
}}

function buySelected() {{
  const codes = Array.from(document.querySelectorAll('.cand-check:checked'))
    .map(cb => cb.value);
  if (codes.length === 0) {{
    alert('请至少勾选一只股票');
    return;
  }}
  apiCall('/api/run_buy_selected?codes=' + codes.join(','), '买入');
}}

function apiCall(url, label) {{
  const toast = document.createElement('div');
  toast.className = 'toast toast-info';
  toast.textContent = label + ' 处理中...';
  document.body.appendChild(toast);

  fetch(url, {{
    method: 'POST',
    headers: {{'X-Dashboard-Token': '{MUTATION_TOKEN}'}},
    credentials: 'same-origin'
  }})
    .then(r => r.json())
    .then(data => {{
      if (data.success) {{
        toast.className = 'toast toast-success';
        toast.textContent = '✅ ' + data.message;
        setTimeout(() => location.reload(), 1500);
      }} else {{
        toast.className = 'toast toast-error';
        toast.textContent = '❌ ' + (data.message || '操作失败');
      }}
    }})
    .catch(err => {{
      toast.className = 'toast toast-error';
      toast.textContent = '❌ 请求失败: ' + err.message;
    }});
  setTimeout(() => {{ if(toast.parentNode) toast.remove(); }}, 5000);
}}
</script>

</body>
</html>"""


# ═══════════════════════════════════════════════════════════════
# HTTP 服务器
# ═══════════════════════════════════════════════════════════════

# ── State 缓存 (避免每次 API 请求都全量扫描) ──
_cache_state = None
_cache_time = None
_cache_ttl = 0  # 禁用缓存，确保每次都是最新数据

def _fresh_engine_state(mode: str = 'chase', force: bool = False) -> dict:
    """创建全新引擎, 加载状态, 选股, 返回含 P0/P1 数据的完整 state"""
    global _cache_state, _cache_time
    
    # 使用缓存避免超时
    now = datetime.now()
    if not force and _cache_state is not None and _cache_time is not None:
        if (now - _cache_time).total_seconds() < _cache_ttl:
            return dict(_cache_state)  # 返回副本避免修改
    
    engine = SimulationEngine()
    engine.load_state()
    
    if mode == 'pullback':
        candidates = _screen_pullback_candidates()
        state = engine.get_state()
        state['candidates'] = candidates
    else:
        try:
            engine.screen_today()
        except Exception as e:
            logger.warning(f'screen_today failed: {e}')
        state = engine.get_state()
    
    # P0: 板块排名
    if 'sector_ranks' not in state or not state.get('sector_ranks', {}).get('top'):
        try:
            from v3.market import MarketContext
            r = MarketContext()
            r.load_cache()
            state['sector_ranks'] = r.get_sector_summary()
        except Exception as e:
            logger.warning(f'加载板块排名失败: {e}')
            state['sector_ranks'] = {'top': [], 'bottom': [], 'time': '', 'total_sectors': 0}
    # P1: 市场情绪
    if 'sentiment' not in state:
        try:
            # → MarketContext
            s = MarketContext()
            state['sentiment'] = s.load_cache() or {
                'label': '中性', 'score': 5, 'limit_up': 0, 'limit_down': 0,
                'up_ratio': 0.5, 'avg_change': 0
            }
        except Exception as e:
            logger.warning(f'加载情绪数据失败: {e}')
            state['sentiment'] = {
                'label': '中性', 'score': 5, 'limit_up': 0, 'limit_down': 0,
                'up_ratio': 0.5, 'avg_change': 0
            }
    state['research'] = _load_research_status()
    state['fund_flow'] = _load_fund_flow_summary()
    try:
        from v4.runtime import V4Runtime
        runtime = V4Runtime()
        if any('v4_tradable' not in candidate for candidate in state.get('candidates', [])):
            state['candidates'] = runtime.evaluate_candidates(
                state.get('candidates', []), state.get('market_state', {})
            )
        state['v4'] = runtime.system_state(state.get('market_state', {}))
    except Exception as e:
        logger.exception('V4看板状态加载失败: %s', e)
        state['v4'] = {
            'system_version': 'V4 unavailable',
            'readiness': {'status': 'error', 'headline': 'V4状态不可用', 'trade_enabled': False},
            'clock': {},
            'scheduler_contract_preserved': True,
        }
    state['trade_allowed'] = bool(
        state.get('v4', {}).get('readiness', {}).get('trade_enabled', False)
        and state.get('v4', {}).get('clock', {}).get('buy', {}).get('allowed', False)
        and state.get('market_state', {}).get('mode_label', 'neutral') != 'risk_off'
    )
    # 保存到缓存
    _cache_state = dict(state)
    _cache_time = datetime.now()
    return state


def _screen_pullback_candidates() -> list:
    """回调策略选股: 使用 PullbackEngine 从行情中筛选回调股
    
    流程:
    1. 获取今日行情 (缩水版, 只取跌幅区间的)
    2. 对候选取K线做深度验证
    3. 评分排序返回
    """
    try:
        from v3.data import DataFetcher
        df = DataFetcher()
        
        # 获取行情: 覆盖主要代码区间
        codes = (
            [f'{i:06d}' for i in range(1, 2000)]         # 深主板
            + [f'6{i:05d}' for i in range(0, 1000)]     # 沪主板
            + [f'3{i:05d}' for i in range(0, 2000)]     # 创业板
            + [f'2{i:05d}' for i in range(0, 1000)]     # 中小板
        )
        quotes = df.batch_fetch_quotes(codes)
        
        if quotes is None or quotes.empty:
            logger.warning("回调模式: 无法获取行情")
            return []
        
        logger.info(f"回调模式: 获取行情 {len(quotes)} 只")
        
        # 排除科创板/ST
        q = quotes[quotes['price'] > 0].copy()
        q = q[~q['code'].str.startswith('688')].copy()
        q = q[~q['code'].str.startswith('8')].copy()
        q = q[~q['code'].str.startswith('4')].copy()
        q = q[~q['name'].str.contains(r'ST|\\*ST', na=False)].copy()
        
        # 统一列名
        if 'change_pct' in q.columns and 'pct_chg' not in q.columns:
            q.rename(columns={'change_pct': 'pct_chg'}, inplace=True)
        
        # 第一步: PullbackEngine 初步筛选 (今日跌幅2~5% + 基础条件)
        pb = PullbackEngine(mode='pullback')
        result = pb.detect(q)  # 无K线时先做基础筛选
        
        if result is None or result.empty:
            logger.info("回调模式: 无候选")
            return []
        
        # 第二步: 对初筛结果获取K线做深度验证 (限制数量避免过多请求)
        kline_data = {}
        subsample = result.head(30)  # 最多取30只查K线
        for _, row in subsample.iterrows():
            code = str(row.get('code', ''))
            try:
                kline = df.fetch_kline(code, days=30)
                if kline is not None and not kline.empty:
                    kline_data[code] = kline
            except Exception as e:
                logger.debug(f"获取K线失败 {code}: {e}")
        
        logger.info(f"回调模式: 获取到 {len(kline_data)} 只K线数据")
        
        # 用K线数据重新深度筛选
        if kline_data:
            result = pb.detect(q, kline_data)
        else:
            # 无K线数据, 用简化评分
            result['pullback_score'] = result.apply(
                lambda r: pb.score_pullback_simple(r), axis=1
            )
            result = result.sort_values('pullback_score', ascending=False).head(10)
        
        if result is None or result.empty:
            return []
        
        # 转换为看板格式
        candidates = []
        for i, (_, s) in enumerate(result.iterrows()):
            price = float(s.get('price', 0))
            pct = float(s.get('pct_chg', s.get('change_pct', 0)))
            score = float(s.get('pullback_score', 70))
            near_5d = float(s.get('near_5d_return', 0))
            vol_r = float(s.get('volume_ratio', 1.0))
            dist_ma10 = float(s.get('dist_to_ma10', 0))
            
            candidates.append({
                'code': str(s.get('code', '')),
                'name': str(s.get('name', '')),
                'score': round(score, 1),
                'pullback_score': round(score, 1),
                'price': price,
                'change_pct': round(pct, 2),
                'pct_chg': round(pct, 2),
                'buy_price': round(
                    TradeCostModel(DEFAULT_SPEC).buy_fill_price(price), 2
                ),
                'near_5d_return': round(near_5d, 2),
                'volume_ratio': round(vol_r, 3),
                'dist_to_ma10': round(dist_ma10, 2),
                'rank': i + 1,
            })
        
        logger.info(f"回调策略候选: {len(candidates)} 只")
        return candidates
        
    except Exception as e:
        logger.exception(f"回调选股失败: {e}")
        return []


class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP 请求处理器"""

    def handle_one_request(self) -> None:
        """安全处理单次请求, 捕获网络断开异常"""
        try:
            super().handle_one_request()
        except ConnectionResetError:
            pass  # 浏览器断连, 忽略
        except BrokenPipeError:
            pass
        except Exception:
            self.log_error('请求处理异常')

    def log_message(self, fmt, *args):
        logger.info(f"{self.client_address[0]} - {fmt % args}")

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html, status=200):
        body = html.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header(
            'Content-Security-Policy',
            "default-src 'self'; style-src 'unsafe-inline'; "
            "script-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:"
        )
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, msg, status=500):
        self._send_json({'success': False, 'message': msg}, status)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip('/') or '/'

        try:
            if path == '/' or path == '':
                self._handle_home()
            elif path == '/api/health':
                self._send_json({
                    'success': True,
                    'service': 'overnight-dashboard',
                    'system_version': 'V4',
                    'host': HOST,
                    'port': PORT,
                    'time': datetime.now().isoformat(timespec='seconds'),
                })
            elif path == '/api/v4/status':
                from v4.runtime import V4Runtime
                self._send_json(V4Runtime().system_state())
            elif path == '/api/state':
                self._handle_state()
            else:
                self._send_error(f'未知路径: {path}', 404)
        except Exception as e:
            logger.exception(f"处理请求失败: {path}")
            self._send_error(f'服务器错误: {str(e)}')

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip('/') or '/'
        if not secrets.compare_digest(
            self.headers.get('X-Dashboard-Token', ''), MUTATION_TOKEN
        ):
            self._send_error('操作令牌无效，请刷新看板后重试', 403)
            return
        try:
            if path == '/api/run_buy':
                self._handle_run_buy()
            elif path == '/api/run_buy_selected':
                self._handle_run_buy_selected()
            elif path == '/api/run_sell':
                self._handle_run_sell()
            elif path == '/api/reset':
                self._handle_reset()
            else:
                self._send_error(f'未知路径: {path}', 404)
        except Exception as e:
            logger.exception(f"处理写操作失败: {path}")
            self._send_error(f'服务器错误: {str(e)}')

    def _get_mode(self) -> str:
        """从请求 URL 中解析 mode 参数"""
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        mode = params.get('mode', ['chase'])[0]
        return mode if mode in ('chase', 'pullback') else 'chase'
    
    def _handle_home(self):
        mode = self._get_mode()
        state = _fresh_engine_state(mode)
        html = build_html(state, mode)
        self._send_html(html)

    def _handle_state(self):
        mode = self._get_mode()
        state = _fresh_engine_state(mode)
        self._send_json(state)

    def _handle_run_buy(self):
        """执行买入；V4 在有效窗口内自行刷新候选并执行全部门禁。"""
        engine = SimulationEngine()
        engine.load_state()
        try:
            result = engine.execute_buy()
            self._send_json(result)
        except Exception as e:
            logger.exception("买入失败")
            self._send_error(f'买入失败: {str(e)}')

    def _handle_run_buy_selected(self):
        """执行勾选买入: 只买用户勾选的股票"""
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        codes_str = params.get('codes', [''])[0]
        selected = [c.strip() for c in codes_str.split(',') if c.strip()]
        
        engine = SimulationEngine()
        engine.load_state()
        try:
            result = engine.execute_buy(selected_codes=selected)
            self._send_json(result)
        except Exception as e:
            logger.exception("勾选买入失败")
            self._send_error(f'勾选买入失败: {str(e)}')

    def _handle_run_sell(self):
        """执行卖出:
        从 engine.positions 获取持仓, 然后调用 engine.execute_sell()
        """
        engine = SimulationEngine()
        engine.load_state()
        try:
            positions = engine.positions
            if not positions:
                self._send_json({
                    'success': True,
                    'message': '当前无持仓',
                    'sold': 0,
                    'detail': []
                })
                return

            result = engine.execute_sell()
            self._send_json(result)
        except Exception as e:
            logger.exception("卖出失败")
            self._send_error(f'卖出失败: {str(e)}')

    def _handle_reset(self):
        engine = SimulationEngine()
        engine.load_state()
        try:
            engine.reset()
            self._send_json({
                'success': True,
                'message': '模拟账户已重置 (初始资金 ¥100,000)',
            })
        except Exception as e:
            logger.exception("重置失败")
            self._send_error(f'重置失败: {str(e)}')


def run_dashboard(port: int = None):
    """启动看板服务器"""
    global PORT
    if port is not None:
        PORT = port

    server = ThreadingHTTPServer((HOST, PORT), DashboardHandler)
    server.allow_reuse_address = True
    logger.info(f"📊 V3 模拟交易看板已启动")
    logger.info(f"   访问地址: http://localhost:{PORT}")
    logger.info(f"   API 端点:")
    logger.info(f"     GET /              → 主页")
    logger.info(f"     GET /api/state     → JSON 状态")
    logger.info(f"     POST /api/run_buy  → 执行买入")
    logger.info(f"     POST /api/run_sell → 执行卖出")
    logger.info(f"     POST /api/reset    → 重置模拟")
    logger.info(f"   按 Ctrl+C 停止服务器")

    # 自动重启机制: 崩溃后等待 3 秒自动重启
    while True:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            logger.info("服务器已停止")
            server.server_close()
            break
        except Exception as e:
            logger.error(f"服务器崩溃: {e}, 3秒后自动重启...")
            server.server_close()
            import time
            time.sleep(3)
            # 重新创建 server 对象 (因为端口可能还处于 TIME_WAIT)
            try:
                server = ThreadingHTTPServer((HOST, PORT), DashboardHandler)
                logger.info(f"服务器已自动重启, http://localhost:{PORT}")
            except OSError:
                logger.error(f"端口 {PORT} 仍被占用, 等待 10 秒后重试...")
                time.sleep(10)
                server = ThreadingHTTPServer((HOST, PORT), DashboardHandler)


if __name__ == '__main__':
    run_dashboard()
