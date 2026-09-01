"""Strict-only paired Baseline versus CloseScan research projection."""
from __future__ import annotations
from math import prod
from statistics import mean,median
from shared_core.core import ContractViolation
from .facts import content_id
from . import BASELINE_STRATEGY_VERSION,CLOSESCAN_STRATEGY_VERSION

def _metrics(rows):
    returns=[float(x["net_return"]) for x in rows];equity=[];value=1.0;peak=1.0;drawdown=0.0
    for result in returns:value*=1+result;peak=max(peak,value);drawdown=min(drawdown,value/peak-1);equity.append(value)
    return {"strict_round_trips":len(rows),"win_rate":sum(x>0 for x in returns)/len(returns) if returns else None,"mean_net_return":mean(returns) if returns else None,"median_net_return":median(returns) if returns else None,"cumulative_return":value-1 if returns else 0.0,"net_pnl":sum(float(x.get("net_pnl",0)) for x in rows),"max_drawdown":drawdown,"flat_rate":sum(x==0 for x in returns)/len(returns) if returns else None,"average_slippage":mean(float(x.get("slippage",0)) for x in rows) if rows else None,"turnover":sum(float(x.get("turnover",0)) for x in rows),"equity_curve":equity}

def compare(baseline_rows,closescan_rows):
    def strict_only(rows):
        selected=[]
        for row in rows:
            if row.get("cohort")=="PROXY":continue
            if row.get("cohort")!="STRICT" or row.get("system_version")!="5.1":raise ContractViolation("only V5.1 STRICT evidence may enter comparison")
            selected.append(row)
        return selected
    baseline_rows=strict_only(baseline_rows);closescan_rows=strict_only(closescan_rows)
    if any(row.get("strategy_version")!=BASELINE_STRATEGY_VERSION for row in baseline_rows):raise ContractViolation("baseline strategy identity mismatch")
    if any(row.get("strategy_version")!=CLOSESCAN_STRATEGY_VERSION for row in closescan_rows):raise ContractViolation("CloseScan strategy identity mismatch")
    def unique(rows,label):
        result={}
        for row in rows:
            day=str(row["trade_date"])
            if day in result:raise ContractViolation(f"duplicate STRICT session: {label} {day}")
            result[day]=row
        return result
    b=unique(baseline_rows,"baseline");c=unique(closescan_rows,"closescan");days=sorted(set(b)|set(c));paired=[];states={"both_traded":0,"baseline_only":0,"closescan_only":0,"both_flat":0};agreements=0;comparable=0
    for day in days:
        br=b.get(day);cr=c.get(day);bt=bool(br and br.get("traded"));ct=bool(cr and cr.get("traded"));states["both_traded" if bt and ct else "baseline_only" if bt else "closescan_only" if ct else "both_flat"]+=1
        if br is not None and cr is not None:
            comparable+=1;same=br.get("selected_code")==cr.get("selected_code");agreements+=int(same);paired.append({"trade_date":day,"baseline_return":float(br.get("net_return",0)),"closescan_return":float(cr.get("net_return",0)),"relative_improvement":float(cr.get("net_return",0))-float(br.get("net_return",0)),"same_selection":same})
    bm=_metrics(list(b.values()));cm=_metrics(list(c.values()));relative=mean(x["relative_improvement"] for x in paired) if paired else None
    result={"schema_version":"v5.1-strategy-comparison-v1","system_version":"5.1","contract_version":"v5.1-contract-v1","trade_date":days[-1] if days else "NO_STRICT_SESSION","cohort":"STRICT","baseline":bm,"closescan":cm,"paired_sessions":len(paired),"paired":paired,"relative_improvement":relative,"selection_agreement_rate":agreements/comparable if comparable else None,"session_states":states,"conclusion":"EVIDENCE_INSUFFICIENT"}
    result["comparison_id"]=content_id("v51cmp1",result)
    return result
