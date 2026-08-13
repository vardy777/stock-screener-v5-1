"""Single-page, decision-first, read-only stock research dashboard."""
import html

def e(v): return html.escape(str(v))
def money(v): return "等待冻结盘口" if v in (None,"") else f"¥{float(v):.2f}"

CSS="""
*{box-sizing:border-box}body{margin:0;background:#07111b;color:#eef4f7;font-family:"Microsoft YaHei",system-ui,sans-serif}.wrap{max-width:1240px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.brand{font-size:25px;font-weight:850}.sub,.muted{font-size:13px;color:#8799a7}.lock,.tag{display:inline-block;border-radius:99px;padding:6px 10px;font-size:12px}.lock{background:#3b2027;color:#ff9eae}.tag{background:#15303a;color:#91dced}.hero{margin-top:20px;padding:24px;border:1px solid #285066;border-radius:18px;background:linear-gradient(135deg,#10283a,#0a1b27);display:grid;grid-template-columns:1.25fr .75fr;gap:22px}.hero h1{font-size:30px;margin:8px 0}.label{color:#71dbba;font-size:12px;font-weight:800}.action{padding:14px;background:#071722;border-left:4px solid #71dbba;border-radius:9px}.facts{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:14px}.fact,.card{background:#0d1b27;border:1px solid #1d3443;border-radius:14px;padding:17px}.fact b{display:block;font-size:23px;margin-top:5px}.good{color:#55d6aa}.bad{color:#ff8296}.warn{color:#ffd166}.grid{display:grid;grid-template-columns:1.35fr .65fr;gap:14px;margin-top:14px}.card h2{font-size:16px;color:#91ddf2;margin:0 0 14px}.candidate{padding:18px;background:#081722;border:1px solid #244251;border-radius:12px;margin-top:10px}.candidate-head{display:flex;justify-content:space-between;gap:12px}.candidate h3{margin:0;font-size:20px}.prices{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:14px}.price{padding:12px;background:#102431;border-radius:9px}.price b{display:block;font-size:18px;margin-top:4px}.reason{padding:9px 0;border-bottom:1px solid #18303f}.reason:last-child{border:0}.notice{padding:13px;background:#302814;color:#ffd66b;border:1px solid #574719;border-radius:9px}.risk{padding:10px;margin:8px 0;background:#241820;border-left:3px solid #ff8296}.market{display:grid;grid-template-columns:repeat(2,1fr);gap:9px}.metric{background:#081722;padding:11px;border-radius:9px}.metric b{display:block;font-size:19px}.health{margin-top:14px;padding:12px 16px;border-radius:10px;background:#0a1822;color:#8da0ad;font-size:12px}.empty{padding:25px 10px;color:#9aabb6}.score{font-size:12px;color:#8da0ad;margin-top:9px}.foot{margin:18px 0;color:#6f8492;font-size:12px}@media(max-width:760px){.wrap{padding:14px}.top{display:block}.lock{margin-top:10px}.hero{display:block;padding:18px}.hero>div+div{margin-top:16px}.hero h1{font-size:24px}.facts{grid-template-columns:repeat(2,1fr)}.grid{display:block}.card{margin-top:14px}.prices{grid-template-columns:1fr}.candidate-head{display:block}.tag{margin-top:8px}}
"""

REASONS={"not_confirmed":"尚未通过14:50尾盘确认","score_policy":"规则评分未达到确认条件","research_locked":"研究准入门禁未解除","market_risk":"市场环境不符合策略要求","data_invalid":"行情数据无效或覆盖不足"}

def render(model,view="research"):
    s=model.to_dict(); m=s["market"]; sent=s["sentiment"]; summary=s["summary"]; fresh=s["freshness"]
    candidates=list(s["candidates"] if fresh["journal_current"] else [])
    confirmed=[x for x in candidates if x["confirmation_rank"] is not None]
    focus=confirmed or candidates
    market_ok=fresh["market_current"] and m["data_valid"]
    title=("今日可以进入模拟观察" if confirmed else "今日暂无确认买入股票" if fresh["journal_current"] else "等待今日有效行情")
    action=("仅按14:50冻结ask1进行模拟观察，不代表实盘建议" if confirmed else
            "保持空仓，等待14:50确认" if candidates else "不要依据过期或覆盖不足的数据选股")
    why=list(summary.get("reasons",[])) or (["早盘候选尚未通过尾盘确认"] if candidates else ["今日没有满足数据与策略门禁的候选"])
    why_html="".join(f"<div class='reason'>• {e(REASONS.get(x,x))}</div>" for x in why[:4])
    cards=""
    for x in focus[:5]:
        reasons=[REASONS.get(v,v) for v in x["reason_codes"]] or ["通过当前阶段规则"]
        cards+=f"""<article class='candidate'><div class='candidate-head'><div><h3>#{e(x['morning_rank'])} {e(x['name'] or '名称不可用')} <span class='muted'>{e(x['code'])}</span></h3><div class='muted'>{e(x['sector'] or '板块未知')} · {e(x['strategy'])}</div></div><span class='tag'>{'尾盘已确认' if x['confirmation_rank'] is not None else '早盘重点观察'}</span></div><div class='prices'><div class='price'>早盘参考价<b>{money(x['reference_price'])}</b></div><div class='price'>允许模拟买入价<b>{money(x['confirmed_buy_price'])}</b><small class='muted'>{e(x['buy_price_source'] or '仅14:50 ask1有效')}</small></div><div class='price'>模拟卖出价<b>次日09:30 bid1</b><small class='muted'>到时按冻结盘口成交，不提前猜价</small></div></div><p><b>入选理由</b></p>{''.join(f"<div class='reason'>• {e(r)}</div>" for r in reasons[:4])}<div class='score'>规则分 {e(x['base_score'])} → {e(x['final_score'] if x['final_score'] is not None else '待确认')}；只是相对排序，不是上涨概率。</div></article>"""
    if not cards:
        data_reason=(f"当前新鲜行情覆盖率 {m['coverage']*100:.1f}%，低于95%门槛。" if m["coverage"]<.95 else
                     f"行情日期或有效性未通过今日校验（记录覆盖率 {m['coverage']*100:.1f}%）。")
        cards=f"<div class='empty'><b>今日没有可展示的推荐股票。</b><p>{data_reason}系统必须停止选股，不能用不完整或过期数据凑候选。</p><p><b>价格计划：</b>允许模拟买入价只能是14:50冻结ask1；模拟卖出价只能是次日09:30冻结bid1。当前均不可给出。</p><p class='score'>规则分只是相对排序，不是上涨概率。</p></div>"
    risks=[]
    if not market_ok:
        risks.append((f"行情覆盖不足：{m['coverage']*100:.1f}%（门槛95%）" if m["coverage"]<.95 else
                      f"行情不是今日有效数据：记录覆盖率 {m['coverage']*100:.1f}%"))
    if s["production_status"]!="published": risks.append("机器学习模型尚未发布，当前只有冻结规则排序")
    if s["evidence"]["strict"]["pairs"]<500: risks.append(f"严格14:50/次日09:30样本仅 {s['evidence']['strict']['pairs']} 对，不能证明策略有效")
    if s["fund_flow"]["status"]!="current": risks.append("板块资金流不是当日可信数据，已从决策展示中剔除")
    risk_html="".join(f"<div class='risk'>{e(x)}</div>" for x in risks) or "<div class='good'>未发现活动数据风险</div>"
    tasks=s["operations"]["tasks"]; task_fail=sum(1 for x in tasks if x.get("status") not in {"SUCCEEDED"})
    completed=sum(1 for x in tasks if x.get("status")=="SUCCEEDED")
    pushes=sum(1 for x in tasks if x.get("task_name") in {"morning_push","confirmation_push"} and x.get("status")=="SUCCEEDED" and x.get("entity_kind")=="NotificationReceiptV1")
    return f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'><title>V4 今日股票研究</title><style>{CSS}</style></head><body><main class='wrap' data-testid='p5-dashboard'><header class='top'><div><div class='brand'>V4 今日股票研究</div><div class='sub'>只展示影响今日判断的信息 · 本地模拟 · 不连接券商</div></div><span class='lock'>{e(s['production_status'])}</span></header><section class='hero'><div><div class='label'>今天的结论</div><h1>{e(title)}</h1><div class='action'><b>现在怎么做</b><div>{e(action)}</div></div></div><div><div class='label'>主要依据</div>{why_html}</div></section><section class='facts'><div class='fact'>行情可信度<b class='{'good' if market_ok else 'bad'}'>{'有效' if market_ok else '不足'}</b></div><div class='fact'>新鲜覆盖率<b>{m['coverage']*100:.1f}%</b></div><div class='fact'>重点观察<b>{len(candidates)}</b></div><div class='fact'>尾盘确认<b>{len(confirmed)}</b></div></section><div class='grid'><section class='card'><h2>今日股票与价格计划</h2>{cards}</section><aside><section class='card'><h2>今日市场</h2><div class='market'><div class='metric'>上涨<b>{m['rise']}</b></div><div class='metric'>下跌<b>{m['fall']}</b></div><div class='metric'>成交额<b>{m['turnover_yi']:,.0f}亿</b></div><div class='metric'>涨/跌停<b>{m['limit_up']}/{m['limit_down']}</b></div></div><p>市场宽度：<b>{e(sent['breadth_label'])}</b></p><p class='muted'>行情时间：{e(m['as_of'] or '未知')}<br>来源：{e(m['source'])}</p></section><section class='card'><h2>必须知道的风险</h2>{risk_html}</section><section class='card'><h2>模拟结果</h2><p>闭合交易 <b>{s['account']['closed_trades']}</b> 笔 · 胜率 <b>{'样本不足' if s['account']['win_rate'] is None else f"{s['account']['win_rate']*100:.1f}%"}</b></p><p>累计净盈亏 <b>¥{s['account']['net_pnl']:+,.2f}</b></p></section></aside></div><div class='health'>系统状态：{e(s['operations']['heartbeat_status'])}（最后任务 {e(s['operations']['heartbeat_at'] or '尚无')}） · 已完成任务 {completed}/9 · 已验收推送 {pushes}/2 · 异常 {task_fail} · 页面只读</div><div class='foot'>价格说明：早盘价仅供观察；只有14:50冻结ask1可作为模拟买入价，次日09:30冻结bid1作为模拟卖出价。系统不会在缺少盘口时编造价格。</div></main></body></html>"""
