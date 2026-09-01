"""Immutable V5 product facts: acquisition sessions and candidate funnels."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
import hashlib,json
from types import MappingProxyType
from typing import Any, Mapping
from .core import CHINA_TZ,ContractViolation,is_market_snapshot,strict_bool,strict_int,strict_str,strict_enum

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
    def __post_init__(self):
        strict_str(self.trade_date,"trade_date");strict_enum(self.stage,"stage",{"morning","signal","confirmation","sell"});_aware(self.requested_at,"requested_at")
        strict_int(self.expected_codes,"expected_codes",1);strict_str(self.selected_snapshot_id,"selected_snapshot_id",allow_empty=True);strict_bool(self.accepted,"accepted")
        if self.accepted and not self.selected_snapshot_id.startswith("ms1-"):raise ContractViolation("selected_snapshot_id: required when accepted")
        if type(self.source_attempts) is not tuple or not self.source_attempts or any(not isinstance(x,Mapping) for x in self.source_attempts):raise ContractViolation("source_attempts: non-empty mapping tuple required")
        object.__setattr__(self,"source_attempts",_freeze(self.source_attempts))
    @classmethod
    def build(cls,*,trade_date,stage,requested_at,expected_codes,selected_snapshot_id,accepted,source_attempts):
        strict_str(trade_date,"trade_date");strict_enum(stage,"stage",{"morning","signal","confirmation","sell"});strict_int(expected_codes,"expected_codes",1)
        strict_str(selected_snapshot_id,"selected_snapshot_id",allow_empty=True);strict_bool(accepted,"accepted")
        if type(source_attempts) not in {list,tuple} or not source_attempts or any(not isinstance(x,Mapping) for x in source_attempts):raise ContractViolation("source_attempts: non-empty mappings required")
        return cls(trade_date,stage,_aware(requested_at,"requested_at"),expected_codes,selected_snapshot_id,accepted,tuple(dict(x) for x in source_attempts))
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
    trade_date:str; stage:str; snapshot_id:str; market_state_id:str; accepted:bool; policy_version:str; stages:tuple[dict,...]; candidates:tuple[dict,...]; policy_parameters:dict|None=None; schema_version:str="v5-candidate-funnel-v1"
    def __post_init__(self):
        strict_str(self.trade_date,"trade_date");strict_enum(self.stage,"stage",{"morning","confirmation"});strict_str(self.snapshot_id,"snapshot_id");strict_str(self.market_state_id,"market_state_id");strict_bool(self.accepted,"accepted");strict_str(self.policy_version,"policy_version")
        if type(self.stages) is not tuple or not self.stages or any(not isinstance(x,Mapping) for x in self.stages):raise ContractViolation("funnel stages: non-empty mapping tuple required")
        if type(self.candidates) is not tuple or any(not isinstance(x,Mapping) for x in self.candidates):raise ContractViolation("funnel candidates: mapping tuple required")
        if self.policy_parameters is not None and not isinstance(self.policy_parameters,Mapping):raise ContractViolation("policy_parameters: mapping required")
        object.__setattr__(self,"stages",_freeze(self.stages));object.__setattr__(self,"candidates",_freeze(self.candidates));object.__setattr__(self,"policy_parameters",_freeze(self.policy_parameters or {}))
    @classmethod
    def build(cls,*,snapshot,market_state_id,stage,accepted,policy_version,stages,candidates,policy_parameters=None):
        strict_enum(stage,"stage",{"morning","confirmation"});strict_bool(accepted,"accepted");strict_str(market_state_id,"market_state_id");strict_str(policy_version,"policy_version")
        if not is_market_snapshot(snapshot):raise ContractViolation("funnel snapshot: versioned market snapshot required")
        if not snapshot.snapshot_id.startswith("ms1-") or not market_state_id.startswith("mstate1-"): raise ContractViolation("funnel lineage: snapshot and market state IDs required")
        if not policy_version or not stages: raise ContractViolation("funnel policy/stages: required")
        if type(stages) not in {list,tuple} or not stages or any(not isinstance(x,Mapping) for x in stages):raise ContractViolation("funnel stages: non-empty mappings required")
        if type(candidates) not in {list,tuple} or any(not isinstance(x,Mapping) for x in candidates):raise ContractViolation("funnel candidates: mappings required")
        if policy_parameters is not None and not isinstance(policy_parameters,Mapping):raise ContractViolation("policy_parameters: mapping required")
        codes=[row.get("code","") for row in candidates]
        if any(type(c) is not str for c in codes):raise ContractViolation("funnel candidate code: strict string required")
        if len(codes)!=len(set(codes)) or any(len(c)!=6 or not c.isdigit() for c in codes): raise ContractViolation("funnel candidates: unique six-digit codes required")
        return cls(snapshot.trade_date,stage,snapshot.snapshot_id,market_state_id,accepted,policy_version,tuple(dict(x) for x in stages),tuple(dict(x) for x in candidates),dict(policy_parameters or {}))
    @property
    def funnel_id(self): return _id("funnel1",self.to_dict(include_id=False))
    def to_dict(self,*,include_id=True):
        value={"schema_version":self.schema_version,"trade_date":self.trade_date,"stage":self.stage,
               "snapshot_id":self.snapshot_id,"market_state_id":self.market_state_id,"accepted":self.accepted,
               "policy_version":self.policy_version,"policy_parameters":_thaw(self.policy_parameters),"stages":_thaw(self.stages),"candidates":_thaw(self.candidates)}
        if include_id:value["funnel_id"]=self.funnel_id
        return value
