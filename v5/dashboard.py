"""V5 four-page, read-only research product. Default preview port is 8899."""
from __future__ import annotations
from datetime import datetime
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import argparse,html,json
from pathlib import Path
from urllib.parse import urlparse
from .core import CHINA_TZ
from .sources import V5ReadOnlySources

CSS="""
:root{--bg:#07111b;--panel:#0e1c28;--line:#203747;--text:#edf4f7;--muted:#8ba0ad;--blue:#79d2ec;--green:#55d6aa;--red:#ff8296;--amber:#ffd166}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:"Microsoft YaHei",system-ui,sans-serif}.wrap{max-width:1180px;margin:auto;padding:22px}.top{display:flex;justify-content:space-between;gap:16px;align-items:center}.brand{font-size:24px;font-weight:850}.sub,.muted{color:var(--muted);font-size:13px}.lock{padding:6px 10px;border-radius:99px;background:#3a2028;color:#ff9bad;font-size:12px}.nav{display:flex;gap:8px;margin:20px 0;overflow:auto}.nav a{color:#a9bbc5;text-decoration:none;padding:9px 13px;border:1px solid var(--line);border-radius:9px;white-space:nowrap}.nav a.on{background:#173447;color:#fff;border-color:#39627a}.hero,.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:20px}.hero h1{font-size:30px;margin:8px 0 14px}.label{color:var(--blue);font-size:12px;font-weight:800}.action{border-left:4px solid var(--green);background:#091722;padding:14px;border-radius:8px}.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:14px;margin-top:14px}.span8{grid-column:span 8}.span6{grid-column:span 6}.span4{grid-column:span 4}.stat{font-size:27px;font-weight:800;margin-top:5px}.bad{color:var(--red)}.good{color:var(--green)}.warn{color:var(--amber)}table{width:100%;border-collapse:collapse;font-size:13px}th,td{padding:11px;text-align:left;border-bottom:1px solid var(--line)}th{color:var(--muted)}.empty{padding:28px 8px;color:#aabac3}.foot{margin-top:15px;color:#6f8490;font-size:12px}.risk{padding:10px;border-left:3px solid var(--red);background:#241820;margin:8px 0}@media(max-width:760px){.wrap{padding:14px}.top{display:block}.lock{display:inline-block;margin-top:8px}.grid{display:block}.card{margin-top:12px}.hero h1{font-size:24px}}
"""
CSS += "@media(max-width:760px){.nav{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));overflow:visible}.nav a{text-align:center;padding:9px 6px}}"
NAV=(("today","今日决策"),("candidates","候选详情"),("account","模拟账户"),("validation","策略验证"))
def _nav(view):return "".join(f"<a class='{'on' if key==view else ''}' href='/{key}'>{label}</a>" for key,label in NAV)
def _shell(view,content):return f"<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'><title>V5 股票研究</title><style>{CSS}</style></head><body><main class='wrap'><header class='top'><div><div class='brand'>V5 股票研究</div><div class='sub'>独立事实源 · 本地模拟 · 不连接券商</div></div><span class='lock'>research_locked</span></header><nav class='nav'>{_nav(view)}</nav>{content}<div class='foot'>排序分不是上涨概率；没有冻结盘口就不展示买卖价格；本系统不构成投资建议。</div></main></body></html>"
def render(model,view="today"):
    value=model.to_dict();today=value["today"];c=value["candidates"];account=value["account"];validation=value["validation"]
    if view=="today":
        content=f"<section class='hero'><div class='label'>今天的结论</div><h1>{html.escape(today['action'])}</h1><div class='action'><b>当前可执行动作</b><br>{'等待严格数据进入影子采集' if today['data_quality']=='unavailable' else '仅执行系统冻结的本地模拟流程'}</div></section><div class='grid'><section class='card span4'><div class='muted'>行情质量</div><div class='stat {'good' if today['data_quality']=='accepted' else 'bad'}'>{today['data_quality']}</div></section><section class='card span4'><div class='muted'>全市场覆盖率</div><div class='stat'>{f'{today["coverage"]*100:.1f}%' if today['coverage'] is not None else '无数据'}</div></section><section class='card span4'><div class='muted'>当前候选</div><div class='stat'>{today['candidate_count']}</div></section></div>"
    elif view=="candidates":
        rows="".join(f"<tr><td>#{x['rank']}</td><td>{html.escape(x['name'])}<br><span class='muted'>{x['code']}</span></td><td>{x['change_pct']:.2f}%</td><td>{x['score_percentile']:.0%}</td><td>{'、'.join(x['reasons'])}</td></tr>" for x in c["items"])
        body=(f"<table><thead><tr><th>排名</th><th>股票</th><th>涨幅</th><th>相对分位</th><th>入选理由</th></tr></thead><tbody>{rows}</tbody></table>" if rows else f"<div class='empty'><b>当前没有候选。</b><p>{html.escape(c['empty_reason'])}</p><p>系统不会用残缺行情或历史候选凑数。</p></div>")
        content=f"<section class='card'><h2>候选详情</h2>{body}</section>"
    elif view=="account":
        ledger=account["ledger"];perf=account["performance"]
        content=f"<div class='grid'><section class='card span4'><div class='muted'>初始资金</div><div class='stat'>¥{float(ledger.get('initial_cash',100000)):,.2f}</div></section><section class='card span4'><div class='muted'>可用现金</div><div class='stat'>¥{float(ledger.get('cash',100000)):,.2f}</div></section><section class='card span4'><div class='muted'>完整往返</div><div class='stat'>{perf['trade_count']}</div></section><section class='card span6'><h2>当前持仓</h2><div class='empty'>{'暂无持仓' if not ledger.get('positions') else html.escape(str(ledger['positions']))}</div></section><section class='card span6'><h2>模拟表现</h2><p>证据队列：{perf['cohort']}</p><p>结论：<b>{perf['conclusion']}</b></p></section></div>"
    else:
        content=f"<section class='hero'><div class='label'>策略有效性</div><h1 class='warn'>{'尚不能证明策略有效' if validation['strict_samples']<500 else html.escape(validation['strategy_conclusion'])}</h1><div class='action'>严格样本 {validation['strict_samples']} · 模拟往返 {validation['paper_round_trips']} · 模型 {validation['model_status']}</div></section><div class='grid'><section class='card span6'><h2>证据隔离</h2><p>严格窗口样本、模拟账户、代理回测分别统计，永不合并。</p></section><section class='card span6'><h2>准入状态</h2><div class='risk'>research_locked 保持；达到样本、Walk-Forward、压力和发布门禁前禁止实盘。</div></section></div>"
    return _shell(view,content)

class Handler(BaseHTTPRequestHandler):
    data_dir=Path("v5/data")
    def do_GET(self):
        path=urlparse(self.path).path;view="today" if path in {"/","/today"} else path.strip("/")
        model=V5ReadOnlySources(self.data_dir).build(datetime.now(CHINA_TZ).date().isoformat())
        if path=="/api/read-model":body=json.dumps(model.to_dict(),ensure_ascii=False).encode();kind="application/json"
        elif view in {x[0] for x in NAV}:body=render(model,view).encode();kind="text/html; charset=utf-8"
        else:self.send_error(404);return
        self.send_response(200);self.send_header("Content-Type",kind);self.send_header("Cache-Control","no-store");self.end_headers();self.wfile.write(body)
    def do_POST(self):self.send_error(405,"read only")
    def log_message(self,*args):pass
def main(port=8899,data_dir="v5/data"):
    Handler.data_dir=Path(data_dir);ThreadingHTTPServer(("127.0.0.1",port),Handler).serve_forever()
if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--port",type=int,default=8899);parser.add_argument("--data-dir",default="v5/data");args=parser.parse_args();main(args.port,args.data_dir)
