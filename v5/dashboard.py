"""Isolated V5 product preview.  Never binds the V4 production port by default."""
from __future__ import annotations
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import html,json
from .product_read_model import build

def render(model):
    value=model.to_dict();today=value["today"];candidates=value["candidates"];account=value["account"];validation=value["validation"]
    cards="".join(f"<li><b>#{x['rank']} {html.escape(x['name'])} {x['code']}</b> · 涨幅 {x['change_pct']:.2f}% · 分位 {x['score_percentile']:.0%}<br><small>理由：{'、'.join(x['reasons'])}；排序不是上涨概率</small></li>" for x in candidates["items"]) or f"<p>{html.escape(candidates['empty_reason'])}</p>"
    return f"""<!doctype html><meta charset='utf-8'><title>V5 股票研究预览</title><style>body{{font-family:Microsoft YaHei,Arial;max-width:1050px;margin:30px auto;background:#f6f8fa;color:#18212b;padding:0 18px}}section{{background:#fff;border:1px solid #d9e1e8;border-radius:10px;padding:18px;margin:14px 0}}h1{{margin-bottom:4px}}h2{{font-size:18px}}.action{{font-size:22px;color:#0b6b4f}}.warn{{color:#a33}}li{{padding:9px 0;border-bottom:1px solid #eee}}small{{color:#667}}</style><h1>V5 今日股票研究（预览）</h1><p>影子开发 · 只读 · 不连接券商</p><section><h2>今日决策</h2><div class='action'>{html.escape(today['action'])}</div><p>行情质量：{today['data_quality']} · 覆盖率：{today['coverage'] if today['coverage'] is not None else '无'} · 候选：{today['candidate_count']}</p></section><section><h2>候选详情</h2><ul>{cards}</ul></section><section><h2>模拟账户</h2><p>闭合交易：{account['performance']['trade_count']} · 结论：{html.escape(account['performance']['conclusion'])}</p></section><section><h2>策略验证</h2><p class='warn'>严格样本：{validation['strict_samples']} · 模型：{validation['model_status']} · 状态：research_locked</p><p>严格样本、模拟账户和代理回测永不合并。没有严格样本时，不能宣称策略有效。</p></section>"""

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        model=build()
        if self.path=="/api/read-model":body=json.dumps(model.to_dict(),ensure_ascii=False).encode();kind="application/json"
        elif self.path=="/":body=render(model).encode();kind="text/html; charset=utf-8"
        else:self.send_error(404);return
        self.send_response(200);self.send_header("Content-Type",kind);self.send_header("Cache-Control","no-store");self.end_headers();self.wfile.write(body)
    def do_POST(self):self.send_error(405,"read only")
    def log_message(self,*args):pass
def main(port=8899):ThreadingHTTPServer(("127.0.0.1",port),Handler).serve_forever()
if __name__=="__main__":main()
