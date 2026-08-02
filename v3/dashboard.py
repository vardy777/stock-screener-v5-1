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
import html
import math
import logging
import secrets
from datetime import datetime, date
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from v3.simulation import SimulationEngine
from v3.pullback import PullbackEngine
from decision_policy import adaptive_strategy_decision, market_regime_score
from market_universe import list_universe_codes
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

/* ── V4 validation-first dashboard ── */
.dashboard-shell { max-width:1580px; margin:0 auto; }
.stats-bar { grid-template-columns:repeat(6,minmax(150px,1fr)); }
.stat-card { min-height:82px; display:flex; flex-direction:column; justify-content:center; }
.stat-card .label,.research-metric .k,.mkt-item .lbl { font-size:11px; }
.card-header { font-size:14px; min-height:42px; }
.card-body { padding:16px; }
table { font-size:13px; }
thead th,tbody td { padding:9px 10px; }
.validation-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }
.cohort-card { background:#0b1322; border:1px solid #1c2c47; border-radius:9px; padding:14px; }
.cohort-card.primary { border-color:#e94560; box-shadow:inset 0 0 0 1px rgba(233,69,96,.1); }
.cohort-card.warn { border-color:#6b5a21; }
.cohort-top { display:flex; justify-content:space-between; gap:10px; align-items:flex-start; margin-bottom:12px; }
.cohort-title { color:#e2e8f0; font-size:14px; font-weight:700; }
.cohort-source { color:#64748b; font-size:10px; margin-top:3px; }
.cohort-number { font:700 25px Consolas,monospace; color:#f8fafc; }
.cohort-unit { font-size:11px; color:#64748b; margin-left:4px; }
.metric-row { display:grid; grid-template-columns:repeat(3,1fr); gap:7px; margin-top:10px; }
.metric-chip { background:#0f192b; border-radius:6px; padding:8px; }
.metric-chip .k { color:#64748b; font-size:10px; }
.metric-chip .v { color:#dbeafe; font:700 13px Consolas,monospace; margin-top:3px; }
.truth-banner { display:grid; grid-template-columns:minmax(220px,.8fr) minmax(0,2.2fr); gap:16px; align-items:center; padding:16px; margin-bottom:16px; border:1px solid #274568; background:linear-gradient(120deg,#101b31,#0d1423); border-radius:9px; }
.truth-action { font-size:22px; font-weight:800; color:#ffd93d; }
.truth-reasons { display:flex; flex-wrap:wrap; gap:7px; }
.reason-chip { display:inline-flex; align-items:center; padding:5px 8px; border-radius:999px; background:#14223a; color:#9fb4cc; font-size:11px; }
.reason-chip.good { background:rgba(78,204,163,.12); color:#79ddbd; }
.reason-chip.risk { background:rgba(233,69,96,.12); color:#ff8a9b; }
.candidate-list { display:grid; gap:10px; }
.candidate-card { display:grid; grid-template-columns:34px minmax(180px,.8fr) minmax(260px,1.7fr) minmax(190px,.8fr); gap:12px; align-items:center; border:1px solid #1a2a44; background:#0c1526; border-radius:8px; padding:12px; }
.candidate-card.fit { border-color:#365a82; }
.candidate-card.blocked { opacity:.88; }
.candidate-rank { width:30px; height:30px; display:grid; place-items:center; border-radius:8px; background:#17243a; color:#ffd93d; font:700 12px Consolas,monospace; }
.candidate-name { font-weight:700; color:#e2e8f0; font-size:15px; }
.candidate-code { color:#48dbfb; font:12px Consolas,monospace; margin-top:3px; }
.candidate-numbers { display:flex; flex-wrap:wrap; gap:12px; color:#94a3b8; font-size:11px; margin-top:6px; }
.candidate-copy { color:#8fa6bf; font-size:11px; line-height:1.7; }
.candidate-copy strong { color:#cbd5e1; }
.candidate-decision { text-align:right; }
.candidate-decision .shadow { color:#64748b; font-size:10px; margin-top:6px; }
.data-note { margin-top:10px; padding:9px 10px; border-radius:6px; background:#0a1220; color:#70859d; font-size:10px; line-height:1.6; }
.breadth-bar { height:9px; background:#112038; border-radius:999px; overflow:hidden; display:flex; margin:12px 0 6px; }
.breadth-up { background:#e94560; }
.breadth-flat { background:#64748b; }
.breadth-down { background:#4ecca3; }
.distribution { display:grid; grid-template-columns:repeat(4,1fr); gap:7px; margin-top:10px; }
.distribution .box { background:#0d1728; padding:9px; border-radius:6px; text-align:center; }
.distribution .n { font:700 15px Consolas,monospace; color:#e2e8f0; }
.distribution .t { color:#64748b; font-size:9px; margin-top:3px; }
.research-details { margin-top:16px; }
.research-details > summary { cursor:pointer; list-style:none; padding:13px 16px; color:#9fb4cc; font-weight:600; background:#111c30; }
.research-details > summary::-webkit-details-marker { display:none; }
.research-details > .details-body { padding:14px; }
.view-label { color:#64748b; font-size:10px; align-self:center; margin-right:4px; }
.grid-2 table { min-width:520px; }
@media(max-width:1100px){
  .stats-bar{grid-template-columns:repeat(3,1fr)}
  .validation-grid{grid-template-columns:1fr}
  .candidate-card{grid-template-columns:32px 1fr;}
  .candidate-copy,.candidate-decision{grid-column:2;text-align:left}
}
@media(max-width:650px){
  body{padding:8px}.top-bar{align-items:flex-start;gap:10px}.top-bar,.action-bar{flex-direction:column}
  .stats-bar{grid-template-columns:1fr 1fr}.truth-banner{grid-template-columns:1fr}
  .distribution{grid-template-columns:1fr 1fr}.btn-mode-group{margin-left:0;width:100%}.btn-mode{flex:1}
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


def _safe(value) -> str:
    return html.escape(str(value if value is not None else ''), quote=True)


def _wilson_interval(wins: int, total: int, z: float = 1.96) -> tuple:
    if total <= 0:
        return 0.0, 0.0
    p = wins / total
    denominator = 1 + z * z / total
    centre = p + z * z / (2 * total)
    radius = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)
    return (max(0.0, (centre - radius) / denominator),
            min(1.0, (centre + radius) / denominator))


def _compute_validation_summary(state: dict) -> dict:
    """Build clearly separated validation cohorts for the dashboard."""

    history = state.get('trade_history', []) or []
    total = len(history)
    wins = sum(1 for trade in history if float(trade.get('pnl_amount', 0) or 0) > 0)
    ci_low, ci_high = _wilson_interval(wins, total)
    gains = sum(max(0.0, float(t.get('pnl_amount', 0) or 0)) for t in history)
    losses = abs(sum(min(0.0, float(t.get('pnl_amount', 0) or 0)) for t in history))
    legacy_pf = gains / losses if losses > 0 else (float('inf') if gains > 0 else 0.0)
    avg_return = (
        sum(float(t.get('pnl_pct', 0) or 0) for t in history) / total
        if total else 0.0
    )
    research = state.get('research', {}) or {}
    proxy = research.get('summary', {}) or {}
    strict_rows = int(proxy.get('strict_rows', proxy.get('strict_1450_rows', 0)) or 0)
    proxy_trades = int(proxy.get('trades', 0) or 0)
    return {
        'conclusion': '证据不足，继续采样' if strict_rows < 500 else '等待全部准入门槛判定',
        'strict': {
            'pairs': strict_rows,
            'target': 500,
            'progress': min(1.0, strict_rows / 500.0),
            'status': 'collecting' if strict_rows < 500 else 'sample_ready',
        },
        'legacy_simulation': {
            'trades': total,
            'wins': wins,
            'win_rate': wins / total if total else 0.0,
            'win_ci_low': ci_low,
            'win_ci_high': ci_high,
            'profit_factor': legacy_pf,
            'average_return_pct': avg_return,
            'total_return_pct': float(
                state.get('account', {}).get('total_return_pct', 0) or 0
            ),
            'max_drawdown_pct': float(
                state.get('account', {}).get('max_drawdown_pct', 0) or 0
            ),
            'source': '旧版V3模拟账户，非V4独立绩效',
        },
        'proxy_walk_forward': {
            'trades': proxy_trades,
            'win_rate': float(proxy.get('win_rate', 0) or 0),
            'win_ci_low': float(proxy.get('win_rate_ci_low_95', 0) or 0),
            'win_ci_high': float(proxy.get('win_rate_ci_high_95', 0) or 0),
            'profit_factor': float(proxy.get('profit_factor', 0) or 0),
            'cumulative_return': float(proxy.get('cumulative_return', 0) or 0),
            'window_consistency': float(proxy.get('window_consistency', 0) or 0),
            'source': '15:00代理14:50，仅研究，禁止作为实盘证据',
        },
    }


def _candidate_quote_as_of(candidates: list) -> str:
    timestamps = []
    for candidate in candidates or []:
        value = str(candidate.get('quote_time', '') or '')
        if value:
            timestamps.append(value)
    return max(timestamps) if timestamps else ''


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
    as_of = ''
    if isinstance(raw, dict):
        as_of = str(raw.get('date') or raw.get('time') or '')
    age_days = None
    try:
        age_days = (date.today() - date.fromisoformat(as_of[:10])).days
    except (TypeError, ValueError):
        pass
    status = 'fresh' if age_days is not None and 0 <= age_days <= 3 else 'stale'
    return {
        'top': rows[:5],
        'time': raw.get('time', '') if isinstance(raw, dict) else '',
        'as_of': as_of,
        'age_days': age_days,
        'status': status,
        'current': bool(rows and status == 'fresh'),
        'source': '历史外部板块资金缓存',
    }


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


def _build_validation_center_html(validation: dict, v4: dict) -> str:
    strict = validation.get('strict', {})
    legacy = validation.get('legacy_simulation', {})
    proxy = validation.get('proxy_walk_forward', {})
    strict_pairs = int(strict.get('pairs', 0) or 0)
    strict_target = int(strict.get('target', 500) or 500)
    progress = float(strict.get('progress', 0) or 0) * 100
    legacy_n = int(legacy.get('trades', 0) or 0)
    proxy_n = int(proxy.get('trades', 0) or 0)
    checks = v4.get('readiness', {}).get('checks', []) or []
    passed = sum(1 for check in checks if check.get('passed'))
    total_checks = len(checks)
    legacy_pf = float(legacy.get('profit_factor', 0) or 0)
    legacy_pf_text = f'{legacy_pf:.3f}' if legacy_pf < 0.1 else f'{legacy_pf:.2f}'
    return f"""
    <div class="card" style="margin-bottom:16px" data-testid="validation-center">
      <div class="card-header">
        <span>验证中心 · 三类证据严格隔离</span>
        <span class="badge-sm">当前结论：{_safe(validation.get('conclusion','继续采样'))}</span>
      </div>
      <div class="card-body">
        <div class="validation-grid">
          <div class="cohort-card primary">
            <div class="cohort-top"><div><div class="cohort-title">V4严格前向样本</div><div class="cohort-source">真实14:50决策 + 次日09:30成交</div></div><span class="status-pill danger">主证据</span></div>
            <div><span class="cohort-number">{strict_pairs}</span><span class="cohort-unit">/ {strict_target} 笔最低门槛</span></div>
            <div class="breadth-bar"><div class="breadth-up" style="width:{progress:.1f}%"></div></div>
            <div class="metric-row">
              <div class="metric-chip"><div class="k">当前胜率</div><div class="v">样本不足</div></div>
              <div class="metric-chip"><div class="k">95%区间</div><div class="v">不可计算</div></div>
              <div class="metric-chip"><div class="k">准入检查</div><div class="v">{passed}/{total_checks}</div></div>
            </div>
          </div>
          <div class="cohort-card">
            <div class="cohort-top"><div><div class="cohort-title">旧版模拟账户实绩</div><div class="cohort-source">{_safe(legacy.get('source',''))}</div></div><span class="status-pill warn">旁证</span></div>
            <div><span class="cohort-number">{float(legacy.get('win_rate',0))*100:.1f}%</span><span class="cohort-unit">n={legacy_n}</span></div>
            <div class="metric-row">
              <div class="metric-chip"><div class="k">胜率95%区间</div><div class="v">{float(legacy.get('win_ci_low',0))*100:.1f}–{float(legacy.get('win_ci_high',0))*100:.1f}%</div></div>
              <div class="metric-chip"><div class="k">累计收益</div><div class="v">{float(legacy.get('total_return_pct',0)):+.2f}%</div></div>
              <div class="metric-chip"><div class="k">Profit Factor</div><div class="v">{legacy_pf_text}</div></div>
            </div>
          </div>
          <div class="cohort-card warn">
            <div class="cohort-top"><div><div class="cohort-title">代理Walk-Forward</div><div class="cohort-source">{_safe(proxy.get('source',''))}</div></div><span class="status-pill warn">仅研究</span></div>
            <div><span class="cohort-number">{float(proxy.get('win_rate',0))*100:.1f}%</span><span class="cohort-unit">n={proxy_n}</span></div>
            <div class="metric-row">
              <div class="metric-chip"><div class="k">胜率95%区间</div><div class="v">{float(proxy.get('win_ci_low',0))*100:.1f}–{float(proxy.get('win_ci_high',0))*100:.1f}%</div></div>
              <div class="metric-chip"><div class="k">盈利窗口</div><div class="v">{float(proxy.get('window_consistency',0))*100:.1f}%</div></div>
              <div class="metric-chip"><div class="k">Profit Factor</div><div class="v">{float(proxy.get('profit_factor',0)):.2f}</div></div>
            </div>
          </div>
        </div>
        <div class="data-note">只有“V4严格前向样本”可以决定模型准入。旧版模拟账户与15:00代理回测用于发现问题，不能合并计算胜率，也不能据此承诺盈利。</div>
      </div>
    </div>"""


def _build_strategy_policy_html(policy: dict, mode: str) -> str:
    reasons = ''.join(
        f'<span class="reason-chip">{_safe(reason)}</span>'
        for reason in policy.get('reasons', [])
    )
    view = '仅看回调研究池' if mode == 'pullback' else '自动总览（兼容原chase地址）'
    return f"""
    <div class="truth-banner" data-testid="adaptive-strategy">
      <div>
        <div style="color:#64748b;font-size:10px;margin-bottom:5px">系统市场适配 · 因果规则V1</div>
        <div class="truth-action">{_safe(policy.get('label','观望 / 空仓'))}</div>
        <div style="color:#64748b;font-size:10px;margin-top:5px">当前视图：{view} · 视图不控制执行</div>
      </div>
      <div>
        <div class="truth-reasons">{reasons}</div>
        <div class="data-note">此适配层负责解释和排列旧版研究候选；V4生产模型发布后仍由模型阈值、市场风险、Top1、交易时钟和研究门禁共同决定是否模拟买入。</div>
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
        <div class="label">当前持仓浮盈亏</div>
        <div class="value small {_css_class(t)}">{_fmt_pct(t)}</div>
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


def _candidate_explanation(candidate: dict, policy: dict) -> tuple:
    strategy = str(candidate.get('strategy', '未知'))
    score = float(candidate.get('score', 0) or 0)
    change = float(candidate.get('change_pct', 0) or 0)
    reasons = []
    if candidate.get('v4_model_ranked'):
        predicted = candidate.get('predicted_return')
        positive = candidate.get('predicted_positive_probability')
        loss = candidate.get('predicted_large_loss_probability')
        if predicted is not None:
            reasons.append(f'模型预期净收益 {float(predicted)*100:+.2f}%')
        if positive is not None:
            reasons.append(f'模型净盈利概率 {float(positive)*100:.1f}%')
        if loss is not None:
            reasons.append(f'模型大亏概率 {float(loss)*100:.1f}%')
    elif strategy == '回调':
        reasons.extend([
            f'旧版回调评分 {score:.1f}',
            f'当日涨跌 {change:+.2f}%',
        ])
        near_5d = candidate.get('_near_5d', candidate.get('near_5d_return'))
        vol_ratio = candidate.get('_vol_ratio', candidate.get('volume_ratio'))
        dist_ma10 = candidate.get('_dist_ma10', candidate.get('dist_to_ma10'))
        if near_5d is not None:
            reasons.append(f'近5日 {float(near_5d):+.2f}%')
        if vol_ratio is not None:
            reasons.append(f'量比 {float(vol_ratio):.2f}x')
        if dist_ma10 is not None:
            reasons.append(f'距MA10 {float(dist_ma10):+.2f}%')
    else:
        reasons.extend([
            f'旧版追高池：涨幅 {change:+.2f}%',
            f'旧版综合评分 {score:.1f}',
        ])
        amount = candidate.get('amount_yi')
        close_position = candidate.get('close_position')
        if amount is not None:
            reasons.append(f'样本成交额 {float(amount):.2f}亿')
        if close_position is not None:
            reasons.append(f'收盘位于日内区间 {float(close_position)*100:.0f}%')

    preferred = set(policy.get('candidate_strategies', []))
    fit = bool(strategy in preferred or candidate.get('v4_model_ranked'))
    risks = list(candidate.get('v4_block_reasons', []) or [])
    if not fit:
        risks.append('不属于当前市场首选研究池')
    return reasons[:5], list(dict.fromkeys(str(item) for item in risks)), fit


def _build_candidates_html(
    candidates: list, mode: str = 'chase', policy: dict = None
) -> str:
    policy = policy or {}
    visible = list(candidates or [])
    if mode == 'pullback':
        visible = [item for item in visible if item.get('strategy') == '回调']
    preferred = set(policy.get('candidate_strategies', []))
    if preferred:
        visible.sort(key=lambda item: (
            item.get('strategy') not in preferred,
            int(item.get('rank', 999) or 999),
        ))
    if not visible:
        message = '当前缓存中没有回调候选' if mode == 'pullback' else '今日无候选，系统允许整日空仓'
        return f'<div class="empty-state"><div class="big">📋</div>{message}</div>'

    cards = []
    tradable_count = 0
    for candidate in visible:
        reasons, risks, fit = _candidate_explanation(candidate, policy)
        tradable = bool(candidate.get('v4_tradable'))
        tradable_count += int(tradable)
        checked = 'checked' if candidate.get('rank') == 1 and tradable else ''
        disabled = '' if tradable else 'disabled'
        decision_class = 'tag-buy' if tradable else 'tag-hold'
        strategy = str(candidate.get('strategy', '未知'))
        strategy_label = 'V4模型Top1' if candidate.get('v4_model_ranked') else strategy
        reason_html = ' · '.join(_safe(item) for item in reasons) or '缓存未保存细分因子，等待下一次主动选股补齐'
        risk_html = ''.join(f'<span class="reason-chip risk">{_safe(item)}</span>' for item in risks)
        fit_html = '<span class="reason-chip good">当前市场适配</span>' if fit else '<span class="reason-chip">研究观察</span>'
        shadow_score = float(candidate.get('v4_shadow_confidence', 0) or 0) * 100
        quote_time = _safe(candidate.get('quote_time', '--'))
        cards.append(f"""
        <div class="candidate-card {'fit' if fit else 'blocked'}" data-strategy="{_safe(strategy)}">
          <div><input aria-label="选择{_safe(candidate.get('code',''))}" type="checkbox" class="cand-check" value="{_safe(candidate.get('code',''))}" {checked} {disabled}></div>
          <div>
            <div style="display:flex;gap:9px;align-items:center"><span class="candidate-rank">#{_safe(candidate.get('rank','?'))}</span><div><div class="candidate-name">{_safe(candidate.get('name',''))}</div><div class="candidate-code">{_safe(candidate.get('code',''))}</div></div></div>
            <div class="candidate-numbers"><span class="yellow">评分 {float(candidate.get('score',0) or 0):.1f}</span><span class="{_css_class(float(candidate.get('change_pct',0) or 0))}">{float(candidate.get('change_pct',0) or 0):+.2f}%</span><span>参考价 ¥{float(candidate.get('buy_price',candidate.get('price',0)) or 0):.2f}</span></div>
          </div>
          <div class="candidate-copy"><strong>入选依据：</strong>{reason_html}<div class="truth-reasons" style="margin-top:6px">{fit_html}{risk_html}</div><div style="color:#536a83;margin-top:5px">行情时间：{quote_time}</div></div>
          <div class="candidate-decision"><span class="tag {decision_class}">{_safe(candidate.get('v4_decision','观察/空仓'))}</span><div style="margin-top:7px;color:#9fb4cc;font-size:11px">{_safe(strategy_label)}</div><div class="shadow">旧规则影子分 {shadow_score:.0f}/100 · 非概率</div></div>
        </div>""")

    buy_disabled = '' if tradable_count else 'disabled'
    return f"""
    <div class="candidate-list">{''.join(cards)}</div>
    <div style="margin-top:12px;display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap">
      <span style="color:#64748b;font-size:11px">只允许V4门禁通过的Top1被勾选；当前市场可随时给出空仓结论。</span>
      <button class="btn btn-buy-sm" onclick="buySelected()" {buy_disabled}>模拟买入已准入Top1</button>
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
        amount = float(s.get('total_amount', 0) or 0)
        count = int(s.get('count', 0) or 0)
        rows.append(f'<tr><td>🔥</td><td>{_safe(sec_name)}</td>'
                    f'<td style="color:{color}">{avg:+.1f}%</td>'
                    f'<td>{up_ratio*100:.0f}%</td>'
                    f'<td>{amount:,.1f}亿</td><td>{count}</td>'
                    f'<td style="font-size:8px">{bar_char}</td></tr>')
    html_out = '<div class="table-wrap"><table><tr><th></th><th>代理行业</th><th>等权涨跌</th><th>上涨</th><th>成交额</th><th>样本</th><th>强度</th></tr>'
    html_out += ''.join(rows)
    html_out += '</table></div>'
    if bottom:
        html_out += '<div style="font-size:10px;color:#64748b;margin-top:6px">相对弱势: '
        html_out += ', '.join(_safe(b['sector']) for b in bottom[:3])
        html_out += '</div>'
    coverage = float(data.get('classified_coverage', 0) or 0) * 100
    reliable = bool(data.get('classification_reliable'))
    status = '可参与排序' if reliable else '覆盖不足，不参与选股加减分'
    html_out += (
        f'<div class="data-note">口径：{_safe(data.get("classification","名称关键词代理行业"))}；'
        f'映射覆盖 {coverage:.1f}% · {status}。数据时间：{_safe(data.get("as_of") or data.get("time") or "--")}</div>'
    )
    return html_out

def _build_fund_flow_html(data: dict, sectors: dict, market: dict) -> str:
    """Show auditable turnover activity; stale external flow is never promoted."""
    activity = sectors.get('activity_top', []) or []
    rows = []
    for item in activity:
        amount = float(item.get('total_amount', 0) or 0)
        change = float(item.get('avg_pct', 0) or 0)
        rows.append(
            f'<tr><td>◉</td><td>{_safe(item.get("sector","--"))}</td>'
            f'<td>{amount:,.1f}亿</td><td class="{_css_class(change)}">{change:+.2f}%</td>'
            f'<td>{float(item.get("up_ratio",0))*100:.0f}%</td></tr>'
        )
    turnover = float(
        market.get('market_total_amount_yi', sectors.get('market_total_amount_yi', 0)) or 0
    )
    turnover_html = f'{turnover:,.0f}亿' if turnover > 0 else '--'
    amount_coverage = market.get('amount_coverage')
    amount_coverage_html = (
        f'{float(amount_coverage)*100:.1f}%'
        if amount_coverage is not None else '--'
    )
    current_flow = bool(data.get('current'))
    if current_flow:
        flow_note = f'外部主力资金缓存：{_safe(data.get("as_of","--"))}，可作为同日辅助观察。'
    else:
        age = data.get('age_days')
        age_text = f'{age}天前' if age is not None else '时间未知'
        flow_note = f'主力净流入缓存已过期（{_safe(data.get("as_of","--"))}，{age_text}），已从当日信号中移除。'
    table_html = (
        '<div class="table-wrap"><table><tr><th></th><th>代理行业</th><th>成交额</th><th>等权涨跌</th><th>上涨</th></tr>'
        + ''.join(rows) + '</table></div>'
        if rows else '<div class="empty-state">暂无可审计的行业成交活跃度</div>'
    )
    return f"""
      <div class="research-metrics" style="margin-bottom:10px">
        <div class="research-metric"><div class="k">全市场样本成交额</div><div class="v">{turnover_html}</div></div>
        <div class="research-metric"><div class="k">金额有效覆盖</div><div class="v">{amount_coverage_html}</div></div>
      </div>
      {table_html}
      <div class="data-note">{flow_note}<br>成交额不是净流入；行业活跃度来自名称关键词映射，仅作透明代理，不参与当前选股加减分。</div>"""


def _build_sentiment_html(data: dict, market: dict) -> str:
    score = data.get('score', 5)
    label = data.get('label', '中性')
    lu = int(market.get('limit_up_count', data.get('limit_up', 0)) or 0)
    ld = int(market.get('limit_down_count', data.get('limit_down', 0)) or 0)
    ur = float(market.get('advance_ratio', data.get('up_ratio', 0.5)) or 0.5)
    avg = float(market.get('market_equal_weight_pct', data.get('avg_change', 0)) or 0)
    median_raw = market.get('market_median_pct', data.get('median_change'))
    median = float(median_raw) if median_raw is not None else None
    up = int(market.get('rise_count', 0) or 0)
    down = int(market.get('fall_count', 0) or 0)
    flat = int(market.get('flat_count', 0) or 0)
    observed = int(market.get('observed_codes', 0) or 0)
    if observed <= 0:
        observed = up + down + flat
    up_width = (up / observed * 100) if observed else ur * 100
    flat_width = (flat / observed * 100) if observed else 0
    down_width = max(0.0, 100 - up_width - flat_width)
    median_text = f'{median:+.2f}%' if median is not None else '--'
    threshold_method = market.get('limit_threshold_method')
    if threshold_method == 'board_aware_proxy':
        threshold_note = '涨跌停按普通股10%、创业板20%、ST 5%的近似阈值统计；不等同于交易所最终封板名单。'
    elif threshold_method == 'legacy_9_5':
        threshold_note = '旧缓存采用统一±9.5%阈值，未按板块修正；这里只能视为大涨/大跌家数代理。'
    else:
        threshold_note = '涨跌停阈值口径不可用，不参与交易判断。'

    # 颜色
    if score >= 6: bar_color = '#ff6b6b'
    elif score >= 4: bar_color = '#fbbf24'
    else: bar_color = '#4ecca3'

    bar = '█' * score + '░' * (10 - score)
    return f'''<div style="padding:4px;">
    <div style="display:flex;justify-content:space-between;align-items:flex-end"><div><div style="font-size:22px;font-weight:bold">{_safe(label)}</div><div style="font-size:10px;color:#64748b">情绪综合分 {score}/10</div></div><div style="font-size:22px;color:{bar_color};font-family:Consolas,monospace">{bar}</div></div>
    <div class="breadth-bar"><div class="breadth-up" style="width:{up_width:.1f}%"></div><div class="breadth-flat" style="width:{flat_width:.1f}%"></div><div class="breadth-down" style="width:{down_width:.1f}%"></div></div>
    <div style="display:flex;justify-content:space-between;color:#64748b;font-size:10px"><span>上涨 {up if observed else '--'}</span><span>平盘 {flat if observed else '--'}</span><span>下跌 {down if observed else '--'}</span></div>
    <div class="distribution">
      <div class="box"><div class="n red">{lu}</div><div class="t">触及涨停阈值</div></div>
      <div class="box"><div class="n green">{ld}</div><div class="t">触及跌停阈值</div></div>
      <div class="box"><div class="n">{ur*100:.1f}%</div><div class="t">市场宽度</div></div>
      <div class="box"><div class="n {_css_class(avg)}">{avg:+.2f}%</div><div class="t">等权均值 / 中位{median_text}</div></div>
    </div>
    <div class="data-note">{threshold_note}数据时间：{_safe(market.get('as_of') or data.get('as_of') or '--')}</div>
  </div>'''

def _build_market_state_html(mkt: dict) -> str:
    mode = mkt.get('mode_label', 'neutral')
    mode_colors = {'risk_on': 'red', 'neutral': 'blue', 'risk_off': 'green'}
    mode_color = mode_colors.get(mode, 'muted')

    equal_weight = float(mkt.get('market_equal_weight_pct', mkt.get('sh_1d_pct', 0)) or 0)
    median_raw = mkt.get('market_median_pct')
    median = float(median_raw) if median_raw is not None else None
    ar = float(mkt.get('advance_ratio', 0.5) or 0.5)
    regime = float(mkt.get('regime_score', 0) or 0)
    turnover = float(mkt.get('market_total_amount_yi', 0) or 0)
    coverage = float(mkt.get('quote_coverage', 0) or 0)
    fresh_coverage = float(mkt.get('fresh_quote_coverage', 0) or 0)
    data_valid = mkt.get('data_valid') is True
    observed_mode = mkt.get('observed_mode_label', mode)
    status_label = '可执行快照' if data_valid else ('历史/非交易快照' if mkt.get('observed_codes') else '无可用全市场快照')

    return f"""
    <div class="mkt-grid">
      <div class="mkt-item">
        <div class="lbl">执行市场状态</div>
        <div class="val {mode_color}">{_safe(mode.upper())}</div>
      </div>
      <div class="mkt-item">
        <div class="lbl">最近观测状态</div>
        <div class="val">{_safe(str(observed_mode).upper())}</div>
      </div>
      <div class="mkt-item">
        <div class="lbl">全市场等权涨跌</div>
        <div class="val {_css_class(equal_weight)}">{_fmt_pct(equal_weight)}</div>
      </div>
      <div class="mkt-item">
        <div class="lbl">涨跌中位数</div>
        <div class="val {_css_class(median or 0)}">{_fmt_pct(median) if median is not None else '--'}</div>
      </div>
      <div class="mkt-item">
        <div class="lbl">市场宽度</div>
        <div class="val {_css_class(ar-.5)}">{ar*100:.1f}%</div>
      </div>
      <div class="mkt-item">
        <div class="lbl">Regime分</div>
        <div class="val {_css_class(regime)}">{regime:+.2f}</div>
      </div>
      <div class="mkt-item">
        <div class="lbl">样本成交额</div>
        <div class="val">{'{:,.0f}亿'.format(turnover) if turnover else '--'}</div>
      </div>
      <div class="mkt-item">
        <div class="lbl">快照 / 实时覆盖</div>
        <div class="val">{coverage*100:.1f}% / {fresh_coverage*100:.1f}%</div>
      </div>
    </div>
    <div class="data-note"><strong>{status_label}</strong> · 样本 {int(mkt.get('observed_codes',0) or 0):,}/{int(mkt.get('expected_codes',0) or 0):,} · 数据时间 {_safe(mkt.get('as_of') or '--')}<br>{_safe(mkt.get('metric_definition','全市场状态不可用时不做推断'))}</div>"""


def build_html(state: dict, mode: str = 'chase') -> str:
    acct = state['account']
    mkt = state['market_state']
    now = state['time']

    is_pullback = mode == 'pullback'
    policy = state.get('strategy_policy', {}) or {}
    mode_badge = '🟡' if policy.get('key') == 'observe' else '🔵'
    mode_label = policy.get('label', '观望 / 空仓')
    chase_active = ' active-chase' if not is_pullback else ''
    pullback_active = ' active-pullback' if is_pullback else ''
    candidate_title = '回调研究池（视图筛选）' if is_pullback else '系统自动候选池'
    visible_count = sum(
        1 for candidate in state.get('candidates', [])
        if not is_pullback or candidate.get('strategy') == '回调'
    )
    v4 = state.get('v4', {})
    risk_off = mkt.get('mode_label', 'neutral') == 'risk_off'
    trade_allowed = bool(state.get('trade_allowed', False))
    trade_disabled = '' if trade_allowed else 'disabled'
    sell_allowed = bool(v4.get('clock', {}).get('sell', {}).get('allowed', False))
    sell_disabled = '' if sell_allowed else 'disabled'
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
<body><main class="dashboard-shell">

<div class="top-bar">
  <div class="logo"><span class="accent">V4 隔夜策略</span><span class="sub"> · 前向验证与模拟观测台</span><span style="font-size:11px;color:#8da4bc;margin-left:10px">{mode_badge} {_safe(mode_label)}</span></div>
  <div><span class="badge badge-on">本机模拟</span><span class="time" style="margin-left:12px">{_safe(now)}</span></div>
</div>

<div class="action-bar">
  <div style="flex:1;display:flex;align-items:center;gap:10px;min-width:260px"><span style="color:#48dbfb;font-weight:700">14:50–14:51:59 → 次日09:30后</span><span style="color:#7b91a9;font-size:11px">{_safe(trade_hint)}</span></div>
  <span class="view-label">候选视图（不控制策略）</span>
  <div class="btn-mode-group"><button class="btn-mode{chase_active}" onclick="switchMode('chase')">自动总览</button><button class="btn-mode{pullback_active}" onclick="switchMode('pullback')">仅看回调池</button></div>
  <button class="btn btn-sell" onclick="apiCall('/api/run_sell','卖出')" {sell_disabled}>窗口内卖出</button>
  <button class="btn btn-buy-sm" onclick="buySelected()" {trade_disabled}>模拟买入Top1</button>
  <button class="btn btn-reset" onclick="if(confirm('确认重置模拟账户?'))apiCall('/api/reset','重置')">重置</button>
  <button class="btn btn-refresh" onclick="location.reload()">刷新</button>
</div>

{_build_v4_status_html(v4)}
{_build_validation_center_html(state.get('validation',{}), v4)}
{_build_strategy_policy_html(policy, mode)}

<div class="card" style="margin-bottom:16px" data-testid="candidate-pool">
  <div class="card-header"><span>{candidate_title}</span><span class="badge-sm">{visible_count} 只 · {_safe(mode_label)}</span></div>
  <div class="card-body">{_build_candidates_html(state.get('candidates',[]), mode, policy)}</div>
</div>

<div class="grid grid-2">
  <div class="card"><div class="card-header"><span>市场状态与数据质量</span><span class="badge-sm">{_safe(mkt.get('mode_label','unavailable').upper())}</span></div><div class="card-body">{_build_market_state_html(mkt)}</div></div>
  <div class="card"><div class="card-header"><span>市场情绪与涨跌分布</span><span class="badge-sm">全市场样本</span></div><div class="card-body">{_build_sentiment_html(state.get('sentiment',{}), mkt)}</div></div>
</div>

<div class="grid grid-2">
  <div class="card"><div class="card-header"><span>候选板块证据</span><span class="badge-sm">Top 5 · 代理分类</span></div><div class="card-body">{_build_sector_ranks_html(state.get('sector_ranks',{}))}</div></div>
  <div class="card"><div class="card-header"><span>资金与成交活跃度</span><span class="badge-sm">净流入过期自动降级</span></div><div class="card-body">{_build_fund_flow_html(state.get('fund_flow',{}), state.get('sector_ranks',{}), mkt)}</div></div>
</div>

<div class="card" style="margin-bottom:16px"><div class="card-header"><span>模拟账户概览</span><span class="badge-sm">旧版账户沿用 · 不并入V4胜率</span></div><div class="card-body">{_build_stats_bar(acct)}</div></div>

<div class="grid grid-2">
  <div class="card"><div class="card-header"><span>当前持仓</span><span class="badge-sm">{acct['position_count']} 只</span></div><div class="card-body">{_build_positions_html(state['positions'])}</div></div>
  <div class="card"><div class="card-header"><span>模拟资金曲线</span><span class="badge-sm">最近 {min(len(state['daily_records']),15)} 条</span></div><div class="card-body">{_build_equity_chart_text(state['daily_records'], acct['initial_capital'])}</div></div>
</div>

<div class="card"><div class="card-header"><span>逐笔模拟交易记录</span><span class="badge-sm">{len(state['trade_history'])} 笔 · 费用口径以账户记录为准</span></div><div class="card-body">{_build_trade_history_html(state['trade_history'])}</div></div>

<details class="card research-details"><summary>展开：代理Walk-Forward明细、精度—覆盖率与准入检查</summary><div class="details-body">{_build_research_html(state.get('research', {}))}</div></details>

<div class="footer">V4本机研究与模拟系统 · 8898地址与原定时推送入口保持兼容 · RESEARCH_LOCKED期间不产生可执行买单</div>
</main>

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
_cache_ttl = 5

def _fresh_engine_state(mode: str = 'chase', force: bool = False) -> dict:
    """读取本地状态；看板GET请求绝不触发行情抓取或重新选股。"""
    global _cache_state, _cache_time
    
    # 使用缓存避免超时
    now = datetime.now()
    if not force and _cache_state is not None and _cache_time is not None:
        if (now - _cache_time).total_seconds() < _cache_ttl:
            return dict(_cache_state)  # 返回副本避免修改
    
    engine = SimulationEngine()
    engine.load_state()
    
    # URL mode is a read-only view filter.  The market policy, not the URL,
    # decides which research pool is currently preferred.
    candidates = engine.load_candidates_from_file()
    state = engine.get_state()
    state['candidates'] = candidates
    cached_market = engine.load_market_state_from_file()
    if cached_market:
        state['market_state'] = cached_market
    
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
    market = state.get('market_state', {}) or {}
    sectors = state.get('sector_ranks', {}) or {}
    sentiment = state.get('sentiment', {}) or {}
    fallback_as_of = (
        market.get('as_of') or sectors.get('as_of')
        or sentiment.get('as_of') or _candidate_quote_as_of(candidates)
    )
    if not market.get('observed_codes') and (
        sectors.get('observed_codes') or sentiment
    ):
        # Older caches did not persist the full market contract.  Reconstruct
        # descriptive metrics only and keep data_valid=False (fail closed).
        expected_codes = len(list_universe_codes(
            PROJECT_ROOT / 'phase1' / 'data' / 'daily'
        ))
        observed_codes = int(sectors.get('observed_codes', 0) or 0)
        observed_return = float(sentiment.get('avg_change', 0) or 0) / 100
        observed_breadth = float(sentiment.get('up_ratio', 0.5) or 0.5)
        observed_regime = market_regime_score(observed_breadth, observed_return, 0.0)
        observed_rises = int(round(observed_codes * observed_breadth))
        market.update({
            'market_equal_weight_pct': observed_return * 100,
            'market_median_pct': None,
            'market_mean_signal_return': observed_return,
            'advance_ratio': observed_breadth,
            'regime_score': observed_regime,
            'market_mean_gap': 0.0,
            'limit_up_count': int(sentiment.get('limit_up', 0) or 0),
            'limit_down_count': int(sentiment.get('limit_down', 0) or 0),
            'limit_threshold_method': 'legacy_9_5',
            'rise_count': observed_rises,
            'fall_count': max(0, observed_codes - observed_rises),
            'flat_count': 0,
            'market_total_amount_yi': float(sectors.get('market_total_amount_yi', 0) or 0),
            'observed_codes': observed_codes,
            'expected_codes': expected_codes,
            'quote_coverage': (
                min(1.0, observed_codes / expected_codes) if expected_codes else 0.0
            ),
            'fresh_quote_coverage': 0.0,
            'amount_coverage': None,
            'data_valid': False,
            'snapshot_complete': False,
            'mode_label': 'unavailable',
            'observed_mode_label': (
                'risk_on' if float(sentiment.get('score', 5) or 5) >= 7
                else ('risk_off' if float(sentiment.get('score', 5) or 5) <= 3 else 'neutral')
            ),
            'as_of': fallback_as_of,
            'data_source': '旧版本地市场缓存',
            'metric_definition': '旧缓存仅可描述最近行情，缺少可执行覆盖率，不参与交易决策',
        })
        state['market_state'] = market
    if not sectors.get('as_of'):
        sectors['as_of'] = fallback_as_of
        state['sector_ranks'] = sectors
    sentiment.setdefault('as_of', fallback_as_of)
    sentiment.setdefault('source', '全市场本地缓存')
    state['sentiment'] = sentiment
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
    state['strategy_policy'] = adaptive_strategy_decision(
        state.get('market_state', {}), state.get('sentiment', {})
    )
    state['validation'] = _compute_validation_summary(state)
    state['trade_allowed'] = bool(
        state.get('v4', {}).get('readiness', {}).get('trade_enabled', False)
        and state.get('v4', {}).get('clock', {}).get('buy', {}).get('allowed', False)
        and state.get('market_state', {}).get('mode_label', 'neutral') != 'risk_off'
        and state.get('strategy_policy', {}).get('key') != 'observe'
        and any(candidate.get('v4_tradable') for candidate in state.get('candidates', []))
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
        
        from market_universe import list_universe_codes
        codes = list_universe_codes(PROJECT_ROOT / 'phase1' / 'data' / 'daily')
        if not codes:
            return []
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
