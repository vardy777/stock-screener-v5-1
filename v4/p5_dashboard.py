"""Isolated P5 read-only dashboard preview. Not connected to port 8898 production."""
from __future__ import annotations
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import html,json
from pathlib import Path
from urllib.parse import urlparse
from .execution import CHINA_TZ
from .p5_read_model import DashboardReadModelBuilder

HOST="127.0.0.1"; PORT=8899

def frozen_demo_model():
    market={"data_valid":True,"mode_label":"neutral","rise_count":2381,"fall_count":1964,"flat_count":112,
      "limit_up_count":47,"limit_down_count":9,"market_total_amount_yi":12864.3,"fresh_quote_coverage":.976,
      "as_of":"2026-08-07T14:50:20+08:00","snapshot_id":"ms1-demo-frozen","market_state_id":"mstate1-demo-frozen","data_source":"冻结全市场快照"}
    morning={"pool_id":"mp-demo-frozen","candidates":[
      {"code":"000001","name":"平安银行","rank":1,"score":82.4,"strategy":"V4强势延续"},
      {"code":"600475","name":"华光环能","rank":2,"score":79.8,"strategy":"V4质量动量"},
      {"code":"300871","name":"回盛生物","rank":3,"score":77.2,"strategy":"V4回调确认"}]}
    confirm={"decision_id":"cd-demo-frozen","outcome":"BLOCKED","reason_codes":["score_policy"],
      "lineage":{"feature_context_id":"fc1-demo"},"candidates":[
      {"code":"000001","name":"平安银行","rank":1,"score":77.5,"base_score":82.4,"confirm_delta":-4.9,"strategy":"V4强势延续","v4_paper_eligible":False}]}
    ledger={"initial_cash":100000,"cash":100423.6,"equity":100423.6,"positions":[],"fills":[],"round_trips":[
      {"code":"000001","net_pnl":286.4,"net_return":.0086,"total_fees":11.2},
      {"code":"600475","net_pnl":-162.8,"net_return":-.0051,"total_fees":10.9},
      {"code":"300871","net_pnl":300.0,"net_return":.0094,"total_fees":11.0}]}
    tasks=[{"task_name":"morning_push","status":"SUCCEEDED","recorded_at":"2026-08-07T09:25:31+08:00","attempt":1},
           {"task_name":"confirmation_push","status":"SUCCEEDED","recorded_at":"2026-08-07T14:50:38+08:00","attempt":1}]
    flow={"status":"stale","as_of":"2026-07-04T07:56:24+08:00","source":"冻结板块资金流","sector_flows":{"汽车":{"net_inflow":82.56,"change_pct":3.77},"国防军工":{"net_inflow":46.25,"change_pct":3.67}}}
    return DashboardReadModelBuilder().build(generated_at=datetime(2026,8,8,20,0,tzinfo=CHINA_TZ),production_status="research_locked",
      morning=morning,confirmation=confirm,market=market,fund_flow=flow,ledger=ledger,task_receipts=tasks,
      heartbeat={"status":"ALIVE","recorded_at":"2026-08-08T19:59:30+08:00"},alerts=[],evidence={"strict_pairs":0,"proxy_trades":45,"model_status":"unpublished"})

CSS="""*{box-sizing:border-box}body{margin:0;background:#071019;color:#d9e6ef;font-family:'Microsoft YaHei',sans-serif;overflow-x:hidden}.wrap{max-width:1500px;margin:auto;padding:22px}.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:18px;gap:12px}.title{font-size:22px;font-weight:800}.sub{color:#7890a2;font-size:12px;overflow-wrap:anywhere}.pill{padding:6px 10px;border-radius:20px;background:#401a25;color:#ff8397;font-size:12px;white-space:nowrap}.grid{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:14px}.card{background:#0d1924;border:1px solid #1d3040;border-radius:12px;padding:16px;min-width:0;overflow-x:auto}.span12{grid-column:span 12}.span8{grid-column:span 8}.span6{grid-column:span 6}.span4{grid-column:span 4}.kpis{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px}.kpi{background:#0a151f;padding:13px;border-radius:9px;border:1px solid #172a38;min-width:0}.kpi b{display:block;font-size:21px;margin-top:6px}.muted{color:#7890a2}.ok{color:#48d6a8}.warn{color:#ffc857}.bad{color:#ff6b81}.timeline{display:flex;gap:8px}.node{flex:1;min-width:0;padding:12px;background:#09141d;border-radius:8px;border-top:3px solid #2d5369;overflow-wrap:anywhere}.node.DONE{border-color:#48d6a8}.node.MISSING,.node.NO_FILL{border-color:#ff6b81}h2{font-size:14px;color:#8fdaf2;margin:0 0 14px}table{width:100%;min-width:620px;border-collapse:collapse;font-size:12px}th,td{text-align:left;padding:9px;border-bottom:1px solid #172a38}th{color:#7890a2}.issue{padding:9px;border-left:3px solid #ff6b81;background:#17151b;margin:7px 0}.bar{height:8px;background:#152531;border-radius:5px;overflow:hidden}.bar i{display:block;height:100%;background:#48d6a8}@media(max-width:900px){.wrap{padding:14px}.span8,.span6,.span4{grid-column:span 12}.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.timeline{flex-direction:column}.top{align-items:flex-start}.title{font-size:20px}}"""

def render(model):
    s=model.to_dict(); a=s['account']; m=s['market']; ev=s['evidence']; esc=html.escape
    pct=lambda v:'—' if v is None else f'{v*100:.1f}%'
    timeline=''.join(f"<div class='node {x['status']}'><b>{esc(x['label'])}</b><div class='muted'>{esc(x['status'])}</div><small>{esc(x['entity_id'] or '无实体')}</small></div>" for x in s['timeline'])
    candidates=''.join(f"<tr><td>{esc(x['code'])}</td><td>{esc(x['name'])}</td><td>#{x['morning_rank']}</td><td>{x['base_score']}</td><td>{x['confirm_delta'] if x['confirm_delta'] is not None else '—'}</td><td>{x['final_score'] or '—'}</td><td>{esc('、'.join(x['reason_codes']))}</td></tr>" for x in s['candidates'])
    issues=''.join(f"<div class='issue'><b>{esc(x['severity'])} · {esc(x['reason_code'])}</b><div>{esc(x['message'])}</div></div>" for x in s['issues']) or "<div class='ok'>无活动数据问题</div>"
    tasks=''.join(f"<tr><td>{esc(x.get('task_name',''))}</td><td>{esc(x.get('status',''))}</td><td>{x.get('attempt','—')}</td><td>{esc(x.get('recorded_at',''))}</td></tr>" for x in s['operations']['tasks'])
    return f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'><title>V4 P5 控制台</title><style>{CSS}</style></head><body><main class='wrap' data-testid='p5-dashboard'><div class='top'><div><div class='title'>A股隔夜研究系统 <span class='ok'>V4</span></div><div class='sub'>P5只读控制台 · 视图不控制执行 · ReadModel {esc(s['read_model_id'])}</div></div><span class='pill'>{esc(s['production_status'])}</span></div><section class='kpis'><div class='kpi'>账户权益<b>¥{a['equity']:,.2f}</b></div><div class='kpi'>已闭合交易<b>{a['closed_trades']}</b></div><div class='kpi'>模拟胜率<b>{pct(a['win_rate'])}</b></div><div class='kpi'>净盈亏<b class='{'ok' if a['net_pnl']>=0 else 'bad'}'>¥{a['net_pnl']:,.2f}</b></div><div class='kpi'>全市场成交额<b>{m['turnover_yi']:,.0f}亿</b></div><div class='kpi'>新鲜覆盖率<b>{m['coverage']*100:.1f}%</b></div></section><div class='grid' style='margin-top:14px'><section class='card span12'><h2>今日不可变链路</h2><div class='timeline'>{timeline}</div></section><section class='card span8'><h2>09:25母池 → 14:50确认</h2><table><thead><tr><th>代码</th><th>名称</th><th>早盘</th><th>基础分</th><th>确认增量</th><th>最终分</th><th>原因码</th></tr></thead><tbody>{candidates}</tbody></table></section><section class='card span4'><h2>数据与运行告警</h2>{issues}</section><section class='card span4'><h2>市场状态</h2><p>状态：<b>{esc(m['mode'])}</b></p><p>上涨 {m['rise']} · 下跌 {m['fall']} · 涨停 {m['limit_up']} · 跌停 {m['limit_down']}</p><p class='muted'>来源：{esc(m['source'])}<br>截至：{esc(m['as_of'])}<br>快照：{esc(m['snapshot_id'])}</p></section><section class='card span4'><h2>市场情绪（描述性）</h2><p>宽度：<b>{esc(s['sentiment']['breadth_label'])}</b></p><div class='bar'><i style='width:{(s['sentiment']['advance_ratio'] or 0)*100:.1f}%'></i></div><p class='muted'>{esc(s['sentiment']['definition'])}</p></section><section class='card span4'><h2>证据分层</h2><p>严格14:50/09:30：<b>{ev['strict']['pairs']}</b> 对</p><p>Paper闭环：<b>{ev['paper']['round_trips']}</b> 笔</p><p>15:00代理：<b>{ev['proxy']['trades']}</b> 笔</p><p class='warn'>三类证据严格隔离 · 模型 {esc(ev['model_status'])}</p></section><section class='card span6'><h2>P4任务与SLA</h2><table><thead><tr><th>任务</th><th>状态</th><th>尝试</th><th>时间</th></tr></thead><tbody>{tasks}</tbody></table><p class='muted'>心跳：{esc(s['operations']['heartbeat_status'])} · {esc(s['operations']['heartbeat_at'])}</p></section><section class='card span6'><h2>统计口径</h2><p>{esc(a['definition'])}</p><p class='muted'>严格证据、模拟账户和代理回测不得合并；所有数字来自冻结实体投影。</p></section></div></main></body></html>"""

class Handler(BaseHTTPRequestHandler):
    model=frozen_demo_model()
    def do_GET(self):
        path=urlparse(self.path).path
        if path=="/api/read-model": body=json.dumps(self.model.to_dict(),ensure_ascii=False).encode(); kind="application/json"
        elif path=="/": body=render(self.model).encode(); kind="text/html; charset=utf-8"
        else: self.send_error(404); return
        self.send_response(200); self.send_header("Content-Type",kind); self.send_header("Cache-Control","no-store"); self.end_headers(); self.wfile.write(body)
    def do_POST(self): self.send_error(405,"P5 dashboard is read-only")
    def log_message(self,*args): pass

def main(port=PORT): ThreadingHTTPServer((HOST,int(port)),Handler).serve_forever()
if __name__=="__main__": main()
