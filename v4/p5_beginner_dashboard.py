"""One-page, evidence-first, read-only stock research dashboard."""
from __future__ import annotations

import html


def _e(value) -> str:
    return html.escape(str(value))


def _price(value) -> str:
    if value in (None, ""):
        return "暂无可靠价格"
    return f"¥{float(value):.2f}"


CSS = """
:root{color-scheme:dark;--bg:#081019;--panel:#101b25;--line:#263746;--text:#eef3f6;
--muted:#91a0aa;--green:#48c89a;--amber:#f0bd55;--red:#ef7385;--blue:#7fc9e8}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:"Microsoft YaHei",system-ui,sans-serif}
.page{max-width:1120px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;gap:16px;align-items:start}
.brand{font-size:24px;font-weight:800}.sub,.muted{color:var(--muted);font-size:13px}.lock{border:1px solid #75404a;color:#ff9aaa;padding:6px 10px;border-radius:99px;font-size:12px}
.hero{margin-top:20px;background:linear-gradient(135deg,#132b3c,#0e1d29);border:1px solid #31516a;border-radius:16px;padding:24px}
.eyebrow{color:var(--blue);font-size:12px;font-weight:800}.hero h1{font-size:30px;margin:8px 0 16px}.action{border-left:4px solid var(--green);background:#0b1822;padding:13px 15px;border-radius:8px}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:14px}.stat,.panel{background:var(--panel);border:1px solid var(--line);border-radius:13px;padding:16px}.stat b{display:block;font-size:22px;margin-top:5px}
.layout{display:grid;grid-template-columns:1.35fr .65fr;gap:14px;margin-top:14px}.panel{margin-bottom:14px}.panel h2{font-size:16px;color:var(--blue);margin:0 0 14px}
.market{display:grid;grid-template-columns:repeat(2,1fr);gap:9px}.metric{background:#0b1720;border-radius:8px;padding:11px}.metric b{display:block;font-size:19px;margin-top:3px}
.candidate{background:#0b1720;border:1px solid #294151;border-radius:11px;padding:17px;margin-top:10px}.candidate-head{display:flex;justify-content:space-between;gap:12px}.candidate h3{margin:0;font-size:20px}.tag{background:#183440;color:#9be1ee;border-radius:99px;padding:5px 9px;font-size:12px;height:max-content}
.prices{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:13px}.price{background:#132531;border-radius:8px;padding:11px}.price b{display:block;font-size:17px;margin:4px 0}.reason{padding:8px 0;border-bottom:1px solid #203441}.reason:last-child{border:0}
.risk{background:#271a20;border-left:3px solid var(--red);padding:10px;margin:8px 0}.notice{background:#2b2618;border:1px solid #5a4925;color:#f4cd72;border-radius:8px;padding:12px}.empty{padding:10px 0;color:#b0bdc5}
.good{color:var(--green)}.bad{color:var(--red)}.warn{color:var(--amber)}.health{color:var(--muted);font-size:12px;border-top:1px solid var(--line);padding-top:13px;margin-top:4px}.foot{color:#71838f;font-size:12px;margin-top:16px}
@media(max-width:760px){.page{padding:14px}.top{display:block}.lock{display:inline-block;margin-top:9px}.hero{padding:18px}.hero h1{font-size:24px}.stats{grid-template-columns:repeat(2,1fr)}.layout{display:block}.prices{grid-template-columns:1fr}.candidate-head{display:block}.tag{display:inline-block;margin-top:8px}}
"""


REASONS = {
    "not_confirmed": "未通过14:50尾盘确认",
    "score_policy": "规则评分未达到确认条件",
    "research_locked": "研究准入门禁尚未解除",
    "market_risk": "市场环境不符合策略要求",
    "data_invalid": "行情覆盖或时效不合格",
    "no_candidate": "早盘母池没有合格候选",
}


def render(model, view="research") -> str:
    state = model.to_dict()
    market = state["market"]
    sentiment = state["sentiment"]
    freshness = state["freshness"]
    evidence = state["evidence"]
    account = state["account"]
    operations = state["operations"]
    current = list(state["candidates"] if freshness["journal_current"] else [])
    confirmed = [row for row in current if row["confirmation_rank"] is not None]
    visible = confirmed or current
    market_ok = bool(freshness["market_current"] and market["data_valid"])

    if confirmed:
        headline = "尾盘已产生模拟观察标的"
        action = "仅按14:50冻结卖一价执行本地模拟买入；这不是实盘建议。"
    elif current:
        headline = "早盘有观察标的，但尾盘没有确认买入"
        action = "保持空仓。候选只有通过尾盘确认后才进入模拟交易。"
    elif freshness["journal_current"]:
        headline = "今天没有可用的推荐股票"
        action = "保持空仓。系统没有足够证据时不会凑数推荐。"
    else:
        headline = "尚无今天的有效研究结论"
        action = "不要使用历史页面信息做今天的判断。"

    why = list(state["summary"].get("reasons", []))
    if not why:
        why = ["当前没有标的同时满足数据质量、母池和尾盘确认条件"]
    why_html = "".join(f"<div class='reason'>• {_e(REASONS.get(x, x))}</div>" for x in why[:4])

    cards = []
    for row in visible[:5]:
        reasons = [REASONS.get(x, x) for x in row["reason_codes"]] or ["通过当前阶段规则"]
        status = "尾盘已确认" if row["confirmation_rank"] is not None else "早盘重点观察"
        cards.append(f"""<article class='candidate'><div class='candidate-head'><div>
<h3>#{_e(row['morning_rank'])} {_e(row['name'] or '名称不可用')} <span class='muted'>{_e(row['code'])}</span></h3>
<div class='muted'>{_e(row['sector'] or '板块未知')} · {_e(row['strategy'])}</div></div><span class='tag'>{status}</span></div>
<div class='prices'><div class='price'>早盘观察价<b>{_price(row['reference_price'])}</b><small class='muted'>只用于回看</small></div>
<div class='price'>模拟买入价<b>{_price(row['confirmed_buy_price'])}</b><small class='muted'>{_e(row['buy_price_source'] or '仅接受14:50冻结卖一价')}</small></div>
<div class='price'>模拟卖出规则<b>次日09:30买一价</b><small class='muted'>届时冻结，不提前猜价</small></div></div>
<p><b>入选或未确认原因</b></p>{''.join(f"<div class='reason'>• {_e(x)}</div>" for x in reasons[:4])}
<div class='muted'>规则分：{_e(row['base_score'])} → {_e(row['final_score'] if row['final_score'] is not None else '待确认')}。评分是排序，不是上涨概率。</div></article>""")
    if not cards:
        coverage = market["coverage"] * 100
        reason = f"今天09:25行情新鲜覆盖率仅 {coverage:.1f}%，低于95%硬门槛。" if coverage < 95 else "今天没有标的通过完整规则链。"
        cards.append(f"<div class='empty'><b>没有推荐并不是页面故障。</b><p>{_e(reason)}系统因此关闭候选，不会用残缺数据凑股票。</p><p>买入价只能来自14:50冻结卖一价，卖出价只能来自次日09:30冻结买一价；当前均不能编造。</p></div>")

    risks = []
    if not market_ok:
        risks.append(f"今日行情质量不合格：新鲜覆盖率 {market['coverage']*100:.1f}%（要求≥95%）。")
    strict_pairs = int(evidence["strict"]["pairs"])
    if strict_pairs < 500:
        risks.append(f"严格14:50/次日09:30样本仅 {strict_pairs} 对，尚不能证明策略有效。")
    if evidence["model_status"] != "published":
        risks.append("机器学习模型尚未发布；当前是冻结规则排序，不是概率预测。")
    if state["fund_flow"]["status"] != "current":
        risks.append("板块资金流不是当日可信数据，已排除出主要判断。")
    risks_html = "".join(f"<div class='risk'>{_e(x)}</div>" for x in risks)

    tasks = list(operations["tasks"])
    done = sum(x.get("status") == "SUCCEEDED" for x in tasks)
    failed = sum(x.get("status") not in {"SUCCEEDED"} for x in tasks)
    pushes = sum(x.get("task_name") in {"morning_push", "confirmation_push"} and x.get("status") == "SUCCEEDED" and x.get("entity_kind") == "NotificationReceiptV1" for x in tasks)
    paper_rate = "样本不足" if account["win_rate"] is None else f"{account['win_rate']*100:.1f}%"

    return f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'><title>V4 今日股票研究</title><style>{CSS}</style></head><body><main class='page' data-testid='p5-dashboard'>
<header class='top'><div><div class='brand'>V4 今日股票研究</div><div class='sub'>只读研究与本地模拟 · 不连接券商 · 数据不足时明确空仓</div></div><span class='lock'>{_e(state['production_status'])}</span></header>
<section class='hero'><div class='eyebrow'>今天的结论</div><h1>{_e(headline)}</h1><div class='action'><b>现在怎么做</b><div>{_e(action)}</div></div><div style='margin-top:14px'><div class='eyebrow'>为什么</div>{why_html}</div></section>
<section class='stats'><div class='stat'>行情质量<b class='{'good' if market_ok else 'bad'}'>{'合格' if market_ok else '不合格'}</b></div><div class='stat'>新鲜覆盖率<b>{market['coverage']*100:.1f}%</b></div><div class='stat'>早盘观察<b>{len(current)}</b></div><div class='stat'>尾盘确认<b>{len(confirmed)}</b></div></section>
<div class='layout'><div><section class='panel'><h2>推荐股票与价格计划</h2>{''.join(cards)}</section></div><aside>
<section class='panel'><h2>今天市场怎么样</h2><div class='market'><div class='metric'>上涨<b>{market['rise']}</b></div><div class='metric'>下跌<b>{market['fall']}</b></div><div class='metric'>成交额<b>{market['turnover_yi']:,.0f}亿</b></div><div class='metric'>涨停 / 跌停<b>{market['limit_up']} / {market['limit_down']}</b></div></div><p>市场宽度：<b>{_e(sentiment['breadth_label'])}</b></p><p class='muted'>行情时间：{_e(market['as_of'] or '未知')}<br>来源：{_e(market['source'])}</p></section>
<section class='panel'><h2>主要风险</h2>{risks_html or '<div class="good">未发现活动风险</div>'}</section>
<section class='panel'><h2>策略真的有效吗</h2><div class='notice'><b>现在不能下结论。</b><br>严格样本 {strict_pairs} 对；代理回测不能替代真实窗口证据。</div><p>本地模拟完整往返：<b>{account['closed_trades']}</b> 笔<br>模拟胜率：<b>{paper_rate}</b><br>模拟累计净盈亏：<b>¥{account['net_pnl']:+,.2f}</b></p></section>
</aside></div><div class='health'>链路状态：{_e(operations['heartbeat_status'])} · 今日任务 {done}/9 · 已验收推送 {pushes}/2 · 异常 {failed} · 页面只读</div>
<div class='foot'>价格契约：模拟买入价必须来自14:50冻结卖一价；模拟卖出规则只接受次日09:30冻结买一价。没有可靠盘口就显示“暂无可靠价格”。规则评分不代表上涨概率，本页面不构成投资建议。</div>
</main></body></html>"""
