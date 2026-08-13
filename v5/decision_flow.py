"""V5 morning-to-confirmation facts, always linked to the same-day mother pool."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
import hashlib,json
from typing import Any
from .core import CHINA_TZ,ContractViolation
from .contracts import CandidateFunnelV1

def _time(value:Any,field:str)->str:
    try:value=value if isinstance(value,datetime) else datetime.fromisoformat(str(value))
    except (TypeError,ValueError) as exc:raise ContractViolation(f"{field}: invalid datetime") from exc
    if value.tzinfo is None or value.utcoffset() is None:raise ContractViolation(f"{field}: timezone required")
    return value.astimezone(CHINA_TZ).isoformat(timespec="seconds")
def _id(prefix,value):return prefix+"-"+hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()[:32]
@dataclass(frozen=True)
class MorningPoolV5:
    trade_date:str;created_at:str;funnel_id:str;snapshot_id:str;market_state_id:str;candidates:tuple[dict,...];schema_version:str="v5-morning-pool-v1"
    @classmethod
    def from_funnel(cls,funnel:CandidateFunnelV1,*,created_at:Any):
        if funnel.stage!="morning" or not funnel.accepted:raise ContractViolation("morning funnel: accepted required")
        return cls(funnel.trade_date,_time(created_at,"created_at"),funnel.funnel_id,funnel.snapshot_id,funnel.market_state_id,tuple(dict(x) for x in funnel.candidates))
    @property
    def pool_id(self):return _id("v5mp1",self.to_dict(include_id=False))
    def to_dict(self,*,include_id=True):
        data={"schema_version":self.schema_version,"trade_date":self.trade_date,"created_at":self.created_at,"funnel_id":self.funnel_id,"snapshot_id":self.snapshot_id,"market_state_id":self.market_state_id,"candidates":[dict(x) for x in self.candidates]}
        if include_id:data["pool_id"]=self.pool_id
        return data
@dataclass(frozen=True)
class ConfirmationV5:
    trade_date:str;decided_at:str;morning_pool_id:str;funnel_id:str;snapshot_id:str;market_state_id:str;candidates:tuple[dict,...];changes:tuple[dict,...];outcome:str;schema_version:str="v5-confirmation-v1"
    @classmethod
    def from_funnel(cls,pool:MorningPoolV5,funnel:CandidateFunnelV1,*,decided_at:Any):
        if funnel.stage!="confirmation" or funnel.trade_date!=pool.trade_date:raise ContractViolation("confirmation: same-day funnel required")
        allowed={x["code"] for x in pool.candidates};outside=[x["code"] for x in funnel.candidates if x["code"] not in allowed]
        if outside:raise ContractViolation("confirmation: outside morning pool")
        morning={x["code"]:x for x in pool.candidates};changes=[]
        for row in funnel.candidates:
            prior=morning[row["code"]];changes.append({"code":row["code"],"morning_rank":prior["rank"],"confirmation_rank":row["rank"],"change_pct_delta":round(row["change_pct"]-prior["change_pct"],4),"amount_delta":row["amount"]-prior["amount"]})
        outcome="BUY_CANDIDATE" if funnel.candidates else "EMPTY"
        return cls(pool.trade_date,_time(decided_at,"decided_at"),pool.pool_id,funnel.funnel_id,funnel.snapshot_id,funnel.market_state_id,tuple(dict(x) for x in funnel.candidates),tuple(changes),outcome)
    @property
    def confirmation_id(self):return _id("v5cd1",self.to_dict(include_id=False))
    def to_dict(self,*,include_id=True):
        data={"schema_version":self.schema_version,"trade_date":self.trade_date,"decided_at":self.decided_at,"morning_pool_id":self.morning_pool_id,"funnel_id":self.funnel_id,"snapshot_id":self.snapshot_id,"market_state_id":self.market_state_id,"candidates":[dict(x) for x in self.candidates],"changes":[dict(x) for x in self.changes],"outcome":self.outcome}
        if include_id:data["confirmation_id"]=self.confirmation_id
        return data
