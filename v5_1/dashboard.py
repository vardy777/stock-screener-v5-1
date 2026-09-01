"""Multi-page read-only V5.1 research dashboard; offline until explicit cutover."""
from __future__ import annotations
from datetime import datetime
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import argparse,html,json
from pathlib import Path
from urllib.parse import urlparse
from shared_core.core import CHINA_TZ
from .production_read_model import ImmutableReadModelBuilder

BUILD_ID="V5.1-OFFLINE-20260827"
CSS=""":root{--bg:#071019;--panel:#0d1b26;--line:#203847;--text:#edf5f7;--muted:#91a7b3;--cyan:#77d7ee;--green:#59d6a8;--red:#ff8194;--amber:#ffd166}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:'Microsoft YaHei',system-ui}.wrap{width:min(1180px,calc(100% - 28px));margin:auto;padding:22px 0}.top{display:flex;justify-content:space-between;gap:16px}.brand{font-size:26px;font-weight:900}.muted{color:var(--muted)}.lock,.pill{padding:5px 9px;border-radius:99px;background:#34212a;color:#ff9bad;font-size:12px}.nav{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0}.nav a{color:var(--cyan);text-decoration:none;padding:8px 12px;border:1px solid var(--line);border-radius:9px}.card{background:var(--panel);border:1px solid var(--line);border-radius:15px;padding:17px;margin:11px 0}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px}.metric{background:#102331;padding:12px;border-radius:10px}.value{font-size:22px;font-weight:800}.good{color:var(--green)}.bad{color:var(--red)}.warn{color:var(--amber)}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:9px;border-bottom:1px solid var(--line)}@media(max-width:760px){.grid,.metrics{grid-template-columns:1fr}.top{display:block}.brand{font-size:22px}}"""

def _e(v):return html.escape(str(v if v is not None else "—"))
def _nav():return "<nav class='nav'><a href='/today'>今日</a><a href='/candidates'>候选</a><a href='/validation'>验证</a><a href='/account'>账户</a><a href='/health'>健康</a></nav>"
def _head(model,title):return f"<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{_e(title)}</title><style>{CSS}</style></head><body><main class='wrap'><header class='top'><div><div class='brand'>V5.1 A股隔夜研究</div><div class='muted'>Persistent Master → 09:35母池 → 14:49决策 → 14:50:40+执行 → 次日09:30+退出</div></div><span class='lock'>RESEARCH LOCKED</span></header>{_nav()}<section class='card'><b>交易日 {_e(model.trade_date)}</b>　当前状态 <span class='value {'bad' if model.state=='FAIL_CLOSED' else 'good' if model.state=='TRADED' else 'warn'}'>{_e(model.state)}</span></section>"
def _foot():return "<footer class='muted'>本系统仅作严格本地模拟研究，不连接券商；V5 Legacy与V5.1 Current证据永久分离。</footer></main></body></html>"
def _timeline(m):
    items=[("Persistent Security Master",m.master.get("status")),("Daily Status",m.tradability.get("status")),("09:30 Market Open",m.market.get("open_status")),("09:35 Morning Pool",m.baseline.get("morning_status")),("14:49 Feature Freeze",m.market.get("freeze_status")),("14:50 Confirmation",m.baseline.get("confirmation_status")),("14:50:40 Execution",m.baseline.get("execution_status")),("Next 09:30 Exit",m.baseline.get("exit_status"))]
    return "<section class='card'><h2>今日生产时间轴</h2>"+"".join(f"<div>{_e(k)}　<b>{_e(v or '○')}</b></div>" for k,v in items)+"</section>"
def _strategy(title,row,origin):
    candidates=row.get("candidates",[]);cards="".join(f"<div class='card'><b>#{_e(x.get('rank'))} {_e(x.get('name'))} {_e(x.get('code'))}</b><p>因子贡献 {_e(x.get('factor_contributions'))}</p><p>14:49变化 {_e(x.get('changes','等待'))}</p><p>14:50 {_e(x.get('status','等待'))}　{_e(x.get('rejection_reason',''))}</p></div>" for x in candidates)
    return f"<section class='card'><div class='muted'>{_e(origin)}</div><h2>{_e(title)} · {_e(row.get('state','WAITING'))}</h2><p>Top1 {_e(row.get('top1','—'))}</p></section>{cards or '<section class=\'card\'>尚无严格候选事实</section>'}"
def render(model,view="today"):
    out=_head(model,"V5.1 "+view)
    if view=="today":
        out+=_timeline(model)+f"<div class='grid'><section class='card'><h2>Security Master</h2><p>状态 {_e(model.master.get('status'))} · 证券数量 {_e(model.master.get('count'))} · 版本 {_e(model.master.get('version'))}</p><p>最后验证 {_e(model.master.get('last_verified_at'))} · Freshness {_e(model.master.get('freshness'))}</p><p>SSE {_e(model.master.get('sse_status'))} · SZSE {_e(model.master.get('szse_status'))} · 独立来源 {_e(model.master.get('independent_sources'))}</p><p class='bad'>失败原因 {_e(model.master.get('failure_reason'))}</p><p>今日状态覆盖率 {_e(model.tradability.get('coverage'))}</p></section><section class='card'><h2>行情可信度</h2><p>Sina {_e(model.market.get('sina_coverage'))} · Tencent {_e(model.market.get('tencent_coverage'))}</p><p>Quote age {_e(model.market.get('quote_age'))} · Consensus {_e(model.market.get('consensus'))}</p></section></div>"+_strategy("V5.1 Baseline",model.baseline,"09:35 MORNING POOL → 14:50 CONFIRMATION")+_strategy("CloseScan Challenger",model.closescan,"CLOSESCAN · FULL-MARKET @ 14:49")
    elif view=="candidates":out+=_strategy("V5.1 Baseline",model.baseline,"09:35 MORNING POOL")+_strategy("CloseScan Challenger",model.closescan,"CLOSESCAN · FULL-MARKET @ 14:49")
    elif view=="validation":
        c=model.comparison;out+=f"<section class='card'><h2>Baseline vs CloseScan · STRICT ONLY</h2><table><tr><th></th><th>Baseline</th><th>CloseScan</th></tr><tr><td>Strict Round Trips</td><td>{_e(c.get('baseline',{}).get('strict_round_trips'))}</td><td>{_e(c.get('closescan',{}).get('strict_round_trips'))}</td></tr><tr><td>Win Rate</td><td>{_e(c.get('baseline',{}).get('win_rate'))}</td><td>{_e(c.get('closescan',{}).get('win_rate'))}</td></tr><tr><td>Mean Return</td><td>{_e(c.get('baseline',{}).get('mean_net_return'))}</td><td>{_e(c.get('closescan',{}).get('mean_net_return'))}</td></tr><tr><td>Max Drawdown</td><td>{_e(c.get('baseline',{}).get('max_drawdown'))}</td><td>{_e(c.get('closescan',{}).get('max_drawdown'))}</td></tr></table><p>Paired Sessions {_e(c.get('paired_sessions'))} · Agreement {_e(c.get('selection_agreement_rate'))}</p><div class='value warn'>{_e(c.get('conclusion','EVIDENCE_INSUFFICIENT'))}</div><h3>Strict Equity Curve</h3><p>Baseline {_e(c.get('baseline',{}).get('equity_curve',[]))}</p><p>CloseScan {_e(c.get('closescan',{}).get('equity_curve',[]))}</p></section>"
    elif view=="account":out+=f"<div class='grid'><section class='card'><h2>Baseline Account</h2><pre>{_e(model.accounts.get('baseline',{}))}</pre></section><section class='card'><h2>CloseScan Account</h2><pre>{_e(model.accounts.get('closescan',{}))}</pre></section></div><section class='card'><h2>Decision / Execution</h2><p>Decision Snapshot {_e(model.baseline.get('decision_snapshot_id'))}</p><p>Execution Snapshot {_e(model.baseline.get('execution_snapshot_id'))}</p><p>Fill {_e(model.baseline.get('fill'))} · Slippage {_e(model.baseline.get('slippage'))} · Fees {_e(model.baseline.get('fees'))}</p></section>"
    elif view=="health":out+=f"<section class='card'><h2>系统健康</h2><p>Security Master {_e(model.master.get('status'))}</p><p>Daily Status {_e(model.tradability.get('status'))}</p><p>Sina {_e(model.market.get('sina_status'))} · Tencent {_e(model.market.get('tencent_status'))}</p><p>Fact Lineage {_e(model.health.get('lineage'))} · Paper Ledger {_e(model.health.get('paper'))}</p><p>Notifications {_e(model.health.get('notifications'))} · Live Acceptance {_e(model.health.get('live_acceptance'))}</p><p class='bad'>Failed component {_e(model.health.get('failed_component'))} · First failure {_e(model.health.get('first_failure'))} · Latest retry {_e(model.health.get('latest_retry'))} · Recovery {_e(model.health.get('recovery_state'))}</p></section>"
    return out+_foot()

class Handler(BaseHTTPRequestHandler):
    data_dir=Path("v5_1/data");model_factory=None
    @classmethod
    def get_model(cls,day):return cls.model_factory(day) if cls.model_factory else ImmutableReadModelBuilder(cls.data_dir).build(day)
    def do_GET(self):
        path=urlparse(self.path).path;routes={"/":"today","/today":"today","/candidates":"candidates","/validation":"validation","/account":"account","/health":"health"}
        if path=="/api/read-model":model=self.get_model(datetime.now(CHINA_TZ).date().isoformat());body=json.dumps(model.to_dict(),ensure_ascii=False).encode();kind="application/json; charset=utf-8"
        elif path in routes:model=self.get_model(datetime.now(CHINA_TZ).date().isoformat());body=render(model,routes[path]).encode();kind="text/html; charset=utf-8"
        else:self.send_error(404);return
        self.send_response(200);self.send_header("Content-Type",kind);self.send_header("Cache-Control","no-store");self.send_header("X-V5-Build",BUILD_ID);self.end_headers();self.wfile.write(body)
    def do_POST(self):self.send_error(405)
    def log_message(self,*args):pass
def main(port=8901,data_dir="v5_1/data"):
    Handler.data_dir=Path(data_dir);ThreadingHTTPServer(("127.0.0.1",port),Handler).serve_forever()
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--port",type=int,default=8901);p.add_argument("--data-dir",default="v5_1/data");a=p.parse_args();main(a.port,a.data_dir)
