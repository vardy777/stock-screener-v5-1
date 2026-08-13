"""Immutable, explainable whole-market state derived from one strict snapshot."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib,json,statistics

@dataclass(frozen=True)
class MarketStateV1:
    trade_date:str;snapshot_id:str;total:int;advancers:int;decliners:int;unchanged:int;limit_up:int;limit_down:int;halted:int;total_amount:float;median_change:float;advance_ratio:float;severe_decline_ratio:float;regime:str;trade_allowed:bool;reasons:tuple[str,...];policy_version:str="v5-market-state-policy-v1";schema_version:str="v5-market-state-v1"
    @classmethod
    def from_snapshot(cls,snapshot):
        changes=[quote.last_price/quote.previous_close-1 for quote in snapshot.quotes if quote.previous_close>0];total=len(changes);adv=sum(value>0 for value in changes);dec=sum(value<0 for value in changes);unchanged=total-adv-dec;advance=adv/max(total,1);severe=sum(value<=-.05 for value in changes)/max(total,1);reasons=[]
        if advance<.25:reasons.append("MARKET_BREADTH_TOO_WEAK")
        if severe>.20:reasons.append("SEVERE_DECLINE_TOO_BROAD")
        regime="RISK_OFF" if reasons else "STRONG" if advance>=.60 else "NEUTRAL"
        return cls(snapshot.trade_date,snapshot.snapshot_id,total,adv,dec,unchanged,sum(q.limit_up for q in snapshot.quotes),sum(q.limit_down for q in snapshot.quotes),sum(q.halted for q in snapshot.quotes),sum(q.amount for q in snapshot.quotes),statistics.median(changes) if changes else 0.0,advance,severe,regime,not reasons,tuple(reasons))
    @property
    def market_state_id(self):return "mstate1-"+hashlib.sha256(json.dumps(self.to_dict(include_id=False),ensure_ascii=False,sort_keys=True,separators=(",",":" )).encode()).hexdigest()[:32]
    def to_dict(self,*,include_id=True):
        value={key:getattr(self,key) for key in ("schema_version","policy_version","trade_date","snapshot_id","total","advancers","decliners","unchanged","limit_up","limit_down","halted","total_amount","median_change","advance_ratio","severe_decline_ratio","regime","trade_allowed")};value.update({"total_amount":float(self.total_amount),"median_change":float(self.median_change),"advance_ratio":float(self.advance_ratio),"severe_decline_ratio":float(self.severe_decline_ratio)});value["reasons"]=list(self.reasons)
        if include_id:value["market_state_id"]=self.market_state_id
        return value
    @classmethod
    def from_mapping(cls,value):
        state=cls(value["trade_date"],value["snapshot_id"],int(value["total"]),int(value["advancers"]),int(value["decliners"]),int(value["unchanged"]),int(value["limit_up"]),int(value["limit_down"]),int(value["halted"]),float(value["total_amount"]),float(value["median_change"]),float(value["advance_ratio"]),float(value["severe_decline_ratio"]),value["regime"],bool(value["trade_allowed"]),tuple(value.get("reasons",[])),value.get("policy_version","v5-market-state-policy-v1"),value.get("schema_version",""))
        if state.schema_version!="v5-market-state-v1" or value.get("market_state_id")!=state.market_state_id:raise ValueError("market state hash invalid")
        return state
