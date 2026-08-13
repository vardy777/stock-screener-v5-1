"""Explainable deterministic candidate funnel over a single immutable snapshot."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable
from .contracts import CandidateFunnelV1
from .data_production import acquisition_accepted
@dataclass(frozen=True)
class FunnelPolicyV1:
    min_amount:float=5_000_000.0;max_candidates:int=20;maximum_intraday_change:float=.095;maximum_range:float=.15;version:str="v5-funnel-policy-v2"
class CandidateFunnel:
    def __init__(self,policy:FunnelPolicyV1|None=None):self.policy=policy or FunnelPolicyV1()
    def run(self,snapshot,*,market_state_id:str,market_valid:bool,stage:str,allowed_codes:Iterable[str]|None=None)->CandidateFunnelV1:
        allowed=None if allowed_codes is None else {str(x).zfill(6) for x in allowed_codes};raw=list(snapshot.quotes)
        stages=[{"name":"universe","input_count":len(raw),"passed_count":len(raw),"rejected":{}}]
        tradeable=[];rejected={}
        for q in raw:
            upper_name=q.name.upper();reason="special_treatment" if "ST" in upper_name or "退" in q.name else "halted" if q.halted else "limit_locked" if q.limit_up or q.limit_down else "missing_buy_book" if stage=="confirmation" and (q.ask1<=0 or q.ask1_volume<=0) else ""
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
        features=[];risk_rejected={}
        for q in rows:
            change=q.last_price/q.previous_close-1;day_range=(q.high_price-q.low_price)/q.previous_close;close_location=(q.last_price-q.low_price)/max(q.high_price-q.low_price,.000001)
            if change>self.policy.maximum_intraday_change:risk_rejected["late_chase_risk"]=risk_rejected.get("late_chase_risk",0)+1;continue
            if day_range>self.policy.maximum_range:risk_rejected["excessive_intraday_range"]=risk_rejected.get("excessive_intraday_range",0)+1;continue
            features.append({"quote":q,"change":change,"range":day_range,"close_location":close_location})
        stages.append({"name":"risk_filter","input_count":len(rows),"passed_count":len(features),"rejected":risk_rejected})
        def percentiles(key):
            ordered=sorted(features,key=lambda x:(x[key],x["quote"].code));n=max(len(ordered)-1,1);return {x["quote"].code:i/n for i,x in enumerate(ordered)}
        momentum=percentiles("change");location=percentiles("close_location");amount_order=sorted(features,key=lambda x:(x["quote"].amount,x["quote"].code));n=max(len(amount_order)-1,1);liquidity={x["quote"].code:i/n for i,x in enumerate(amount_order)}
        ranked=[]
        for item in features:
            q=item["quote"];contrib={"momentum":round(momentum[q.code]*.45,6),"liquidity":round(liquidity[q.code]*.30,6),"close_location":round(location[q.code]*.25,6)};score=sum(contrib.values());ranked.append((score,q.code,item,contrib))
        ranked.sort(reverse=True);selected=[];total=max(len(ranked),1)
        for rank,(score,code,item,contrib) in enumerate(ranked[:self.policy.max_candidates],1):
            q=item["quote"];risks=[]
            if item["change"]>.07:risks.append("接近追高区间")
            if item["close_location"]<.45:risks.append("尾盘位置偏弱")
            selected.append({"code":q.code,"name":q.name,"rank":rank,"change_pct":round(item["change"]*100,4),"amount":q.amount,"last_price":q.last_price,"bid1":q.bid1,"ask1":q.ask1,"quote_time":q.exchange_time,"provider":q.provider,"score":round(score,6),"score_percentile":round((total-rank+1)/total,6),"factor_values":{"intraday_change":round(item["change"],6),"amount":q.amount,"day_range":round(item["range"],6),"close_location":round(item["close_location"],6)},"factor_contributions":contrib,"rank_basis":"frozen_v5_rule_factors_v2","input_snapshot_id":snapshot.snapshot_id,"reasons":["可交易","流动性通过","市场门禁通过"],"risks":risks or ["隔夜跳空与市场反转风险"],"v5_candidate_origin":"V5"})
        stages.append({"name":"ranked","input_count":len(features),"passed_count":len(selected),"rejected":{"below_top_n":max(0,len(features)-len(selected))}})
        return CandidateFunnelV1.build(snapshot=snapshot,market_state_id=market_state_id,stage=stage,accepted=bool(market_valid and acquisition_accepted(snapshot)),policy_version=self.policy.version,stages=stages,candidates=selected)
