"""Explainable deterministic candidate funnel over a single immutable snapshot."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable
from v4.market_contracts import MarketSnapshotV1
from .contracts import CandidateFunnelV1
from .data_production import acquisition_accepted
@dataclass(frozen=True)
class FunnelPolicyV1:
    min_amount:float=5_000_000.0;max_candidates:int=20;version:str="v5-funnel-policy-v1"
class CandidateFunnel:
    def __init__(self,policy:FunnelPolicyV1|None=None):self.policy=policy or FunnelPolicyV1()
    def run(self,snapshot:MarketSnapshotV1,*,market_state_id:str,market_valid:bool,stage:str,allowed_codes:Iterable[str]|None=None)->CandidateFunnelV1:
        allowed=None if allowed_codes is None else {str(x).zfill(6) for x in allowed_codes};raw=list(snapshot.quotes)
        stages=[{"name":"universe","input_count":len(raw),"passed_count":len(raw),"rejected":{}}]
        tradeable=[];rejected={}
        for q in raw:
            reason="halted" if q.halted else "limit_locked" if q.limit_up or q.limit_down else "missing_buy_book" if q.ask1<=0 or q.ask1_volume<=0 else ""
            if reason:rejected[reason]=rejected.get(reason,0)+1
            else:tradeable.append(q)
        stages.append({"name":"tradeable","input_count":len(raw),"passed_count":len(tradeable),"rejected":rejected})
        liquid=[];rejected={}
        for q in tradeable:
            if q.amount<self.policy.min_amount:rejected["insufficient_amount"]=rejected.get("insufficient_amount",0)+1
            else:liquid.append(q)
        stages.append({"name":"liquidity","input_count":len(tradeable),"passed_count":len(liquid),"rejected":rejected})
        if not market_valid or not acquisition_accepted(snapshot):
            rows=[];stages.append({"name":"market_gate","input_count":len(liquid),"passed_count":0,"rejected":{"market_data_invalid":len(liquid)}})
        else:
            rows=[q for q in liquid if allowed is None or q.code in allowed];missing=len(liquid)-len(rows)
            stages.append({"name":"mother_pool" if allowed is not None else "market_gate","input_count":len(liquid),"passed_count":len(rows),"rejected":({"outside_morning_pool":missing} if missing else {})})
        ranked=sorted(((q.last_price/q.previous_close-1.0,q.amount,q) for q in rows),key=lambda x:(x[0],x[1],x[2].code),reverse=True);selected=[];total=max(len(ranked),1)
        for rank,(change,amount,q) in enumerate(ranked[:self.policy.max_candidates],1):selected.append({"code":q.code,"name":q.name,"rank":rank,"change_pct":round(change*100,4),"amount":q.amount,"score_percentile":round((total-rank+1)/total,6),"rank_basis":"intraday_change_then_amount","input_snapshot_id":snapshot.snapshot_id,"reasons":["tradeable","liquid","market_gate"],"v5_candidate_origin":"V5"})
        stages.append({"name":"ranked","input_count":len(rows),"passed_count":len(selected),"rejected":{"below_top_n":max(0,len(rows)-len(selected))}})
        return CandidateFunnelV1.build(snapshot=snapshot,market_state_id=market_state_id,stage=stage,accepted=bool(market_valid and acquisition_accepted(snapshot)),policy_version=self.policy.version,stages=stages,candidates=selected)
