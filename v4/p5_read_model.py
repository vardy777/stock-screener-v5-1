"""P5 content-addressed, read-only dashboard projection."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
from statistics import mean, median
from typing import Any, Mapping


class DashboardContractViolation(ValueError): pass


def _hash(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _money(value): return round(float(value or 0), 2)


@dataclass(frozen=True)
class DashboardReadModelV1:
    read_model_id: str
    generated_at: str
    production_status: str
    data_status: str
    timeline: tuple[dict, ...]
    candidates: tuple[dict, ...]
    market: dict
    sentiment: dict
    fund_flow: dict
    account: dict
    evidence: dict
    operations: dict
    sources: tuple[dict, ...]
    issues: tuple[dict, ...]
    summary: dict
    freshness: dict
    schema_version: str = "dashboard-read-model-v1"

    def to_dict(self): return asdict(self)


class DashboardReadModelBuilder:
    def build(self, *, generated_at: datetime, production_status: str, morning=None,
              confirmation=None, market=None, fund_flow=None, ledger=None,
              task_receipts=(), heartbeat=None, alerts=(), evidence=None,
              source_artifacts=(), source_issues=(), ownership=None, cutover=None):
        if generated_at.tzinfo is None: raise DashboardContractViolation("generated_at: timezone required")
        morning, confirmation, market = dict(morning or {}), dict(confirmation or {}), dict(market or {})
        fund_flow, ledger, evidence = dict(fund_flow or {}), dict(ledger or {}), dict(evidence or {})
        issues = [dict(x) for x in source_issues]
        if not morning: issues.append(self._issue("ERROR", "MORNING_POOL_MISSING", "09:25母池缺失"))
        if not confirmation: issues.append(self._issue("ERROR", "CONFIRMATION_MISSING", "14:50最终决策缺失"))
        if morning and not morning.get("pool_id"): issues.append(self._issue("ERROR", "MORNING_ENTITY_ID_MISSING", "09:25母池是旧格式或缺少实体ID"))
        if confirmation and not confirmation.get("decision_id"): issues.append(self._issue("ERROR", "DECISION_ENTITY_ID_MISSING", "14:50决策是旧格式或缺少实体ID"))
        if market.get("data_valid") is not True: issues.append(self._issue("ERROR", "MARKET_DATA_INVALID", "市场数据无效或过期"))
        if fund_flow.get("status") not in {"current", "valid"}: issues.append(self._issue("WARNING", "FUND_FLOW_STALE", "资金流数据陈旧或不可用"))
        timeline = self._timeline(morning, confirmation, ledger, task_receipts)
        candidates = self._candidates(morning, confirmation)
        market_view = self._market(market)
        sentiment = self._sentiment(market)
        freshness = self._freshness(generated_at, morning, confirmation, market, fund_flow)
        if not freshness["market_current"]:
            sentiment={**sentiment,"advance_ratio":None,"breadth_label":"无法判断","valid":False}
        if market and not freshness["market_current"]:
            issues.append(self._issue("ERROR","MARKET_DATA_STALE","市场行情不是当日数据"))
        if fund_flow.get("sector_flows") and not freshness["fund_flow_current"]:
            issues.append(self._issue("WARNING","FUND_FLOW_STALE","板块资金流不是当日数据"))
        flow = self._flow(fund_flow, freshness["fund_flow_current"])
        account = self._account(ledger)
        evidence_view = self._evidence(evidence, account)
        evidence_view.update(self._acceptance(evidence))
        operations = self._operations(task_receipts, heartbeat, alerts, ownership, cutover)
        summary = self._summary(operations, market_view, confirmation, freshness, candidates)
        if operations["heartbeat_status"] not in {"ALIVE","IDLE_NON_TRADING_DAY","AWAITING_FIRST_WINDOW"}:
            issues.append(self._issue("CRITICAL", "HEARTBEAT_STALE", "调度心跳过期"))
        if evidence_view["model_status"] != "published": issues.append(self._issue("WARNING", "MODEL_UNPUBLISHED", "生产预期模型尚未发布"))
        if confirmation and confirmation.get("outcome") in {"BLOCKED", "OUTCOME_UNKNOWN"}:
            code = "DECISION_BLOCKED" if confirmation.get("outcome") == "BLOCKED" else "OUTCOME_UNKNOWN"
            issues.append(self._issue("WARNING", code, f"14:50决策结果：{confirmation.get('outcome')}"))
        if any(x.get("status") in {"FAILED", "MISSED", "OUTCOME_UNKNOWN"} for x in task_receipts):
            issues.append(self._issue("ERROR", "TASK_FAILURE", "存在失败、漏跑或结果未知任务"))
        payload = {"schema_version":"dashboard-read-model-v1", "generated_at":generated_at.isoformat(timespec="seconds"),
            "production_status":production_status, "data_status":"DEGRADED" if issues else "HEALTHY",
            "timeline":timeline,"candidates":candidates,"market":market_view,"sentiment":sentiment,
            "fund_flow":flow,"account":account,"evidence":evidence_view,"operations":operations,
            "sources":list(source_artifacts),"issues":issues,"summary":summary,"freshness":freshness}
        return DashboardReadModelV1(read_model_id="drm1-"+_hash(payload)[:24],
            **{k:(tuple(v) if k in {"timeline","candidates","sources","issues"} else v) for k,v in payload.items() if k!="schema_version"})

    @staticmethod
    def _issue(severity, code, message): return {"severity":severity,"reason_code":code,"message":message}

    def _timeline(self, morning, confirmation, ledger, receipts):
        status = {(r.get("task_name"),r.get("status")) for r in receipts}
        fills = ledger.get("fills", [])
        return [
            {"key":"morning","label":"09:25 母池","status":"DONE" if morning.get("pool_id") else ("INVALID_ENTITY" if morning else "MISSING"),"entity_id":morning.get("pool_id","")},
            {"key":"feature","label":"14:49 特征冻结","status":"DONE" if ("feature_freeze","SUCCEEDED") in status else "PENDING","entity_id":confirmation.get("lineage",{}).get("feature_context_id","")},
            {"key":"confirmation","label":"14:50 最终确认","status":"DONE" if confirmation.get("decision_id") else ("INVALID_ENTITY" if confirmation else "MISSING"),"entity_id":confirmation.get("decision_id","")},
            {"key":"buy","label":"14:50 模拟买入","status":"DONE" if any(x.get("side")=="BUY" for x in fills) else "NO_FILL","entity_id":next((x.get("fill_id","") for x in fills if x.get("side")=="BUY"),"")},
            {"key":"sell","label":"次日09:30 模拟卖出","status":"DONE" if any(x.get("side")=="SELL" for x in fills) else "PENDING","entity_id":next((x.get("fill_id","") for x in fills if x.get("side")=="SELL"),"")},
        ]

    def _candidates(self, morning, confirmation):
        confirmed = {str(x.get("code")):x for x in confirmation.get("candidates",[])}
        result=[]
        for row in morning.get("candidates",[]):
            final=confirmed.get(str(row.get("code")),{})
            result.append({"code":row.get("code",""),"name":row.get("name",""),"morning_rank":row.get("rank"),
                "base_score":row.get("base_score",row.get("score")),"confirmation_rank":final.get("rank"),
                "confirm_delta":final.get("confirm_delta"),"final_score":final.get("score"),
                "strategy":final.get("strategy",row.get("strategy","V4")),"eligible":final.get("v4_paper_eligible") is True,
                "reason_codes":confirmation.get("reason_codes",[]) if final else ["not_confirmed"],
                "pool_id":morning.get("pool_id",""),"decision_id":confirmation.get("decision_id","")})
        return result

    def _market(self, m):
        return {"market_state_id":m.get("market_state_id",""),"snapshot_id":m.get("snapshot_id",""),
            "as_of":m.get("as_of",""),"data_valid":m.get("data_valid") is True,"mode":m.get("mode_label","unavailable"),
            "rise":int(m.get("rise_count",0) or 0),"fall":int(m.get("fall_count",0) or 0),"flat":int(m.get("flat_count",0) or 0),
            "limit_up":int(m.get("limit_up_count",0) or 0),"limit_down":int(m.get("limit_down_count",0) or 0),
            "turnover_yi":_money(m.get("market_total_amount_yi")),"coverage":round(float(m.get("fresh_quote_coverage",0) or 0),4),
            "source":m.get("data_source","未提供")}

    def _sentiment(self,m):
        total=sum(int(m.get(k,0) or 0) for k in ("rise_count","fall_count","flat_count")); rise=int(m.get("rise_count",0) or 0)
        valid=m.get("data_valid") is True and float(m.get("fresh_quote_coverage",0) or 0)>=.95 and total>=100
        ratio=rise/total if valid else None
        return {"advance_ratio":ratio,"breadth_label":"偏强" if ratio is not None and ratio>=.6 else ("偏弱" if ratio is not None and ratio<=.4 else "中性" if ratio is not None else "无法判断"),
            "valid":valid,"sample_size":total,
            "turnover_yi":_money(m.get("market_total_amount_yi")),"coverage":round(float(m.get("fresh_quote_coverage",0) or 0),4),
            "definition":"上涨家数/上涨下跌平盘总数；仅描述市场宽度，不是盈利概率"}

    def _flow(self,f,current=True):
        rows=list(f.get("sector_flows",{}).items())[:8]
        status=(f.get("status","unavailable") if current else "stale") if rows else "unavailable"
        return {"status":status,"as_of":f.get("as_of",f.get("updated_at","")),
            "source":f.get("source","未提供"),"unit":"亿元","sectors":[{"name":n,"net_inflow":_money(v.get("net_inflow")),"change_pct":v.get("change_pct")} for n,v in rows]}

    def _account(self,l):
        trips=list(l.get("round_trips",[])); pnl=[_money(x.get("net_pnl")) for x in trips]
        wins=sum(x>0 for x in pnl); initial=_money(l.get("initial_cash",100000)); cash=_money(l.get("cash",initial))
        curve=[]; value=initial; peak=initial; max_dd=0
        for x in pnl: value+=x; peak=max(peak,value); max_dd=max(max_dd,(peak-value)/peak if peak else 0); curve.append(value)
        return {"initial_cash":initial,"cash":cash,"equity":_money(l.get("equity",cash)),"positions":list(l.get("positions",[])),
            "closed_trades":len(trips),"wins":wins,"win_rate":wins/len(trips) if trips else None,
            "average_pnl":mean(pnl) if pnl else None,"median_pnl":median(pnl) if pnl else None,
            "net_pnl":sum(pnl),"max_drawdown":max_dd,"equity_curve":curve,"round_trips":trips,
            "definition":"仅统计已闭合往返，包含费用；未平仓不进入胜率"}

    def _evidence(self,e,a):
        return {"strict":{"pairs":int(e.get("strict_pairs",0)),"role":"模型准入主证据"},
            "paper":{"round_trips":a["closed_trades"],"role":"工程与模拟账户证据"},
            "proxy":{"trades":int(e.get("proxy_trades",0)),"role":"15:00代理研究，禁止替代严格样本"},
            "model_status":e.get("model_status","unpublished"),"cohorts_separated":True}

    @staticmethod
    def _acceptance(e):
        live=dict(e.get("live_windows",{}) or {}); admission=dict(e.get("strict_admission",{}) or {})
        names=("morning_0925","feature_1449","confirmation_1450","sell_0930")
        checks={str(x.get("name",x.get("window",""))):x for x in live.get("checks",[])}
        windows=[{"name":name,"status":"PASSED" if checks.get(name,{}).get("passed") is True else "PENDING",
                  "reasons":list(checks.get(name,{}).get("reasons",[]))} for name in names]
        return {"live_windows":windows,"live_windows_passed":live.get("passed") is True,
                "strict_admission":{"passed":admission.get("passed") is True,
                    "reasons":list(admission.get("reasons",[])),
                    "sample_count":int(admission.get("sample_count",e.get("strict_pairs",0)) or 0)},
                "execution_result_count":int(e.get("execution_result_count",0) or 0)}

    def _operations(self,receipts,heartbeat,alerts,ownership=None,cutover=None):
        return {"tasks":list(receipts),"heartbeat_status":(heartbeat or {}).get("status","MISSING"),
            "heartbeat_at":(heartbeat or {}).get("recorded_at",(heartbeat or {}).get("observed_at","")),"alerts":list(alerts),
            "ownership":dict(ownership or {"decision":"P2","account_execution":"legacy_production","scheduler_notifications":"legacy_phase1_scripts","dashboard":"legacy_8898"}),
            "cutover":dict(cutover or {"ready":False,"apply_allowed":False,"plan_id":""})}

    @staticmethod
    def _date_of(value):
        try: return datetime.fromisoformat(str(value).replace("Z","+00:00")).date().isoformat()
        except (TypeError,ValueError):
            text=str(value or "")
            return text[:10] if len(text)>=10 else ""

    def _freshness(self,generated,morning,confirmation,market,fund_flow):
        today=generated.date().isoformat()
        journal_day=str(confirmation.get("trade_date") or morning.get("trade_date") or "")
        market_day=self._date_of(market.get("as_of"))
        flow_day=self._date_of(fund_flow.get("as_of",fund_flow.get("updated_at","")))
        return {"today":today,"journal_trade_date":journal_day,"market_trade_date":market_day,
            "fund_flow_trade_date":flow_day,"journal_current":journal_day==today,
            "market_current":market_day==today and market.get("data_valid") is True,
            "fund_flow_current":flow_day==today and fund_flow.get("status") in {"current","valid"}}

    @staticmethod
    def _summary(operations,market,confirmation,freshness,candidates):
        heartbeat=operations.get("heartbeat_status","")
        if heartbeat=="IDLE_NON_TRADING_DAY":
            phase,title,action="休市","等待下一个交易日 09:25","无需操作"
        elif not freshness.get("market_current"):
            phase,title,action="数据等待","当前没有可信的当日行情","不要依据历史数据判断"
        else:
            outcome=confirmation.get("outcome","")
            phase="尾盘确认" if confirmation else "早盘观察"
            title={"BUY":"模拟买入条件通过","EMPTY":"今日空仓","BLOCKED":"今日不买入","OUTCOME_UNKNOWN":"结果未知，停止执行"}.get(outcome,"等待下一窗口")
            action="仅观察，等待14:50确认" if not confirmation else ("记录模拟交易，不代表实盘建议" if outcome=="BUY" else "保持空仓")
        reasons=[]
        if not freshness.get("journal_current"): reasons.append("候选不是当日数据")
        if not freshness.get("market_current"): reasons.append("市场行情无效或已过期")
        reasons.extend(str(x) for x in confirmation.get("reason_codes",[])[:3])
        return {"phase":phase,"title":title,"action":action,"reasons":reasons,
            "current_candidate_count":len(candidates) if freshness.get("journal_current") else 0}
