"""V5 product read model: decision, candidates, account and validation pages."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping
from .contracts import AcquisitionSessionV1,CandidateFunnelV1
from .decision_flow import MorningPoolV5,ConfirmationV5
from .performance import PerformanceReportV1

@dataclass(frozen=True)
class V5ProductReadModel:
    today:dict;candidates:dict;account:dict;validation:dict;schema_version:str="v5-product-read-model-v1"
    def to_dict(self):return {"schema_version":self.schema_version,"today":self.today,"candidates":self.candidates,"account":self.account,"validation":self.validation}

def build(*,acquisition:AcquisitionSessionV1|None=None,morning:MorningPoolV5|None=None,confirmation:ConfirmationV5|None=None,market_state:Mapping|None=None,performance:PerformanceReportV1|None=None,account:Mapping|None=None,comparable_baseline_days:int=0)->V5ProductReadModel:
    accepted=bool(acquisition and acquisition.accepted)
    candidates=list(confirmation.candidates if confirmation else morning.candidates if morning else [])
    if not accepted:action="不交易：全市场严格行情未通过质量门槛"
    elif confirmation and confirmation.outcome=="BUY_CANDIDATE":action="尾盘候选已确认：仅可按冻结盘口进入本地模拟"
    elif confirmation:action="保持空仓：尾盘确认没有候选"
    else:action="等待14:50确认；早盘候选不是买入信号"
    attempts=list(acquisition.source_attempts) if acquisition else []
    attempt=(next((row for row in attempts if row.get("snapshot_id")==acquisition.selected_snapshot_id),None) if acquisition and acquisition.selected_snapshot_id else None)
    if attempt is None and attempts:attempt=max(attempts,key=lambda row:float(row.get("coverage",0) or 0))
    attempt=attempt or {}
    source_results=[{"source":row.get("source","").strip(),"coverage":row.get("coverage"),"complete":bool(row.get("complete")),"reasons":list(row.get("reasons",[]) or []),"age_seconds":row.get("age_seconds"),"batch_seconds":row.get("batch_seconds"),"error":row.get("error","")} for row in attempts]
    today={"action":action,"data_quality":"accepted" if accepted else ("rejected" if acquisition else "unavailable"),"coverage":attempt.get("coverage"),"market_scope":"沪深A股（含科创板，暂不含北交所）","data_as_of":acquisition.requested_at if acquisition else None,"snapshot_id":acquisition.selected_snapshot_id if acquisition else "","source":attempt.get("source",""),"source_consensus":[row.get("source","") for row in attempts if row.get("complete")],"source_results":source_results,"morning_pool_id":morning.pool_id if morning else "","confirmation_id":confirmation.confirmation_id if confirmation else "","candidate_count":len(candidates),"market_state":dict(market_state or {})}
    failure_summary="；".join(f"{row['source'] or '未知源'}覆盖{float(row['coverage'])*100:.1f}%" if row.get("coverage") is not None else f"{row['source'] or '未知源'}失败：{row.get('error') or '未知错误'}" for row in source_results)
    candidate_page={"items":candidates,"changes":[dict(x) for x in confirmation.changes] if confirmation else [],"empty_reason":None if candidates else (("行情质量未通过："+failure_summary) if acquisition and not accepted else "行情尚未采集" if not acquisition else "没有标的通过当前漏斗")}
    report=performance.to_dict() if performance else {"cohort":"paper_round_trips","trade_count":0,"comparable_trade_count":0,"conclusion":"INSUFFICIENT_EVIDENCE"}
    account_page={"ledger":dict(account or {}),"performance":report}
    validation={"strict_samples":report["trade_count"],"paper_round_trips":report["trade_count"],"comparable_baseline_days":int(comparable_baseline_days),"strategy_conclusion":report["conclusion"],"model_status":"unpublished","research_locked":True}
    return V5ProductReadModel(today,candidate_page,account_page,validation)
