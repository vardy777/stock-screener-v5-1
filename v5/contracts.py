"""Immutable V5 product facts: acquisition sessions and candidate funnels."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
import hashlib,json
from types import MappingProxyType
from typing import Any, Mapping
from v4.execution import CHINA_TZ
from v4.market_contracts import ContractViolation, MarketSnapshotV1

def _aware(value: Any, field: str) -> str:
    try: value=value if isinstance(value,datetime) else datetime.fromisoformat(str(value))
    except (TypeError,ValueError) as exc: raise ContractViolation(f"{field}: invalid datetime") from exc
    if value.tzinfo is None or value.utcoffset() is None: raise ContractViolation(f"{field}: timezone is required")
    return value.astimezone(CHINA_TZ).isoformat(timespec="seconds")
def _canonical(value): return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))
def _id(prefix,value): return prefix+"-"+hashlib.sha256(_canonical(value).encode()).hexdigest()[:32]
def _freeze(value):
    if isinstance(value,Mapping): return MappingProxyType({str(k):_freeze(v) for k,v in value.items()})
    if isinstance(value,(list,tuple)): return tuple(_freeze(x) for x in value)
    return value
def _thaw(value):
    if isinstance(value,Mapping): return {str(k):_thaw(v) for k,v in value.items()}
    if isinstance(value,tuple): return [_thaw(x) for x in value]
    return value

@dataclass(frozen=True)
class AcquisitionSessionV1:
    trade_date:str; stage:str; requested_at:str; expected_codes:int; selected_snapshot_id:str; accepted:bool; source_attempts:tuple[dict,...]; schema_version:str="v5-acquisition-session-v1"
    def __post_init__(self): object.__setattr__(self,"source_attempts",_freeze(self.source_attempts))
    @classmethod
    def build(cls,*,trade_date,stage,requested_at,expected_codes,selected_snapshot_id,accepted,source_attempts):
        if stage not in {"morning","signal","confirmation","sell"}: raise ContractViolation("stage: unsupported value")
        if int(expected_codes)<1: raise ContractViolation("expected_codes: positive required")
        if accepted and not str(selected_snapshot_id).startswith("ms1-"): raise ContractViolation("selected_snapshot_id: required when accepted")
        if not source_attempts: raise ContractViolation("source_attempts: non-empty required")
        return cls(str(trade_date),stage,_aware(requested_at,"requested_at"),int(expected_codes),str(selected_snapshot_id),bool(accepted),tuple(dict(x) for x in source_attempts))
    @property
    def session_id(self): return _id("acq1",self.to_dict(include_id=False))
    def to_dict(self,*,include_id=True):
        value={"schema_version":self.schema_version,"trade_date":self.trade_date,"stage":self.stage,
               "requested_at":self.requested_at,"expected_codes":self.expected_codes,
               "selected_snapshot_id":self.selected_snapshot_id,"accepted":self.accepted,
               "source_attempts":_thaw(self.source_attempts)}
        if include_id:value["session_id"]=self.session_id
        return value

@dataclass(frozen=True)
class CandidateFunnelV1:
    trade_date:str; stage:str; snapshot_id:str; market_state_id:str; accepted:bool; policy_version:str; stages:tuple[dict,...]; candidates:tuple[dict,...]; schema_version:str="v5-candidate-funnel-v1"
    def __post_init__(self):
        object.__setattr__(self,"stages",_freeze(self.stages));object.__setattr__(self,"candidates",_freeze(self.candidates))
    @classmethod
    def build(cls,*,snapshot:MarketSnapshotV1,market_state_id,stage,accepted,policy_version,stages,candidates):
        if stage not in {"morning","confirmation"}: raise ContractViolation("funnel stage: unsupported value")
        if not snapshot.snapshot_id.startswith("ms1-") or not str(market_state_id).startswith("mstate1-"): raise ContractViolation("funnel lineage: snapshot and market state IDs required")
        if not policy_version or not stages: raise ContractViolation("funnel policy/stages: required")
        codes=[str(row.get("code","")) for row in candidates]
        if len(codes)!=len(set(codes)) or any(len(c)!=6 or not c.isdigit() for c in codes): raise ContractViolation("funnel candidates: unique six-digit codes required")
        return cls(snapshot.trade_date,stage,snapshot.snapshot_id,str(market_state_id),bool(accepted),str(policy_version),tuple(dict(x) for x in stages),tuple(dict(x) for x in candidates))
    @property
    def funnel_id(self): return _id("funnel1",self.to_dict(include_id=False))
    def to_dict(self,*,include_id=True):
        value={"schema_version":self.schema_version,"trade_date":self.trade_date,"stage":self.stage,
               "snapshot_id":self.snapshot_id,"market_state_id":self.market_state_id,"accepted":self.accepted,
               "policy_version":self.policy_version,"stages":_thaw(self.stages),"candidates":_thaw(self.candidates)}
        if include_id:value["funnel_id"]=self.funnel_id
        return value
