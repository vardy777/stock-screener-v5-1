"""V5.1 09:35 baseline and 14:50 confirmation facts."""
from __future__ import annotations
from dataclasses import asdict,dataclass
from datetime import datetime,time
from pathlib import Path
from shared_core.core import CHINA_TZ,ContractViolation
from shared_core.funnel import CandidateFunnel,FunnelPolicyV1
from shared_core.market_snapshot import MarketSnapshotV1
from . import BASELINE_STRATEGY_VERSION,CONTRACT_VERSION,SYSTEM_VERSION
from .facts import canonical,content_id,save_immutable
from .security_master import aware
from .tradability import DailyTradabilityFactV1

MORNING_START=time(9,35);MORNING_END=time(9,35,59);CONFIRM_START=time(14,50);CONFIRM_END=time(14,51,59)
MAX_MORNING_SNAPSHOT_AGE_SECONDS=30
FEATURE_FREEZE_START=time(14,49);FEATURE_FREEZE_END=time(14,49,59)

def _plain(value):
    from collections.abc import Mapping
    if isinstance(value,Mapping):return {str(k):_plain(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)):return [_plain(x) for x in value]
    return value

def _window(value,start,end,label):
    current=aware(value,label);clock=current.timetz().replace(tzinfo=None)
    if not start<=clock<=end:raise ContractViolation(f"{label}: outside V5.1 window")
    return current

def _snapshot_before(snapshot,decision,session,*,maximum_decision_age_seconds=None):
    if not isinstance(snapshot,MarketSnapshotV1) or snapshot.session!=session or not snapshot.quality.accepted:raise ContractViolation("V5.1 accepted versioned snapshot required")
    completed=aware(snapshot.batch_completed_at,"snapshot completed")
    if completed>decision:raise ContractViolation("future snapshot forbidden")
    if completed.date()!=decision.date():raise ContractViolation("same-day snapshot required")
    if maximum_decision_age_seconds is not None and (decision-completed).total_seconds()>maximum_decision_age_seconds:raise ContractViolation("snapshot stale at decision time")
    if any(aware(q.provider_time,"quote provider time")>decision for q in snapshot.quotes):raise ContractViolation("future quote forbidden")

def _snapshot_payload(snapshot):
    return {"snapshot_id":snapshot.snapshot_id,"trade_date":snapshot.trade_date,"session":snapshot.session,"batch_started_at":snapshot.batch_started_at,"batch_completed_at":snapshot.batch_completed_at,"quotes":[q.to_dict() for q in snapshot.quotes],"quality":asdict(snapshot.quality),"schema_version":snapshot.schema_version}

@dataclass(frozen=True)
class FeatureFreezeV51:
    trade_date:str;frozen_at:str;decision_snapshot_id:str;system_version:str=SYSTEM_VERSION;contract_version:str=CONTRACT_VERSION;schema_version:str="v5.1-feature-freeze-v1"
    @property
    def freeze_id(self):return content_id("v51freeze1",asdict(self))
    def to_dict(self):return {**asdict(self),"freeze_id":self.freeze_id}

class DecisionSnapshotRepository:
    def __init__(self,root):self.root=Path(root)
    def freeze(self,snapshot,frozen_at):
        at=_window(frozen_at,FEATURE_FREEZE_START,FEATURE_FREEZE_END,"feature freeze");_snapshot_before(snapshot,at,"signal")
        completed=aware(snapshot.batch_completed_at,"snapshot completed");clock=completed.timetz().replace(tzinfo=None)
        if not FEATURE_FREEZE_START<=clock<=FEATURE_FREEZE_END:raise ContractViolation("snapshot outside feature freeze window")
        payload=_snapshot_payload(snapshot);save_immutable(self.root/"decision_snapshots"/snapshot.trade_date/f"{snapshot.snapshot_id}.json",payload)
        fact=FeatureFreezeV51(snapshot.trade_date,at.isoformat(),snapshot.snapshot_id);save_immutable(self.root/"feature_freezes"/snapshot.trade_date/f"{fact.freeze_id}.json",fact.to_dict());return fact
    def require(self,freeze,snapshot):
        if not isinstance(freeze,FeatureFreezeV51) or freeze.decision_snapshot_id!=snapshot.snapshot_id:raise ContractViolation("feature freeze pointer mismatch")
        snapshot_path=self.root/"decision_snapshots"/freeze.trade_date/f"{snapshot.snapshot_id}.json";freeze_path=self.root/"feature_freezes"/freeze.trade_date/f"{freeze.freeze_id}.json"
        if not snapshot_path.exists() or not freeze_path.exists():raise ContractViolation("immutable feature freeze pointer missing")
        if snapshot_path.read_text(encoding="utf-8")!=canonical(_snapshot_payload(snapshot)):raise ContractViolation("immutable decision snapshot mismatch")
        if freeze_path.read_text(encoding="utf-8")!=canonical(freeze.to_dict()):raise ContractViolation("immutable feature freeze pointer mismatch")
        return freeze

@dataclass(frozen=True)
class MorningPoolV51:
    trade_date:str;decided_at:str;tradability_id:str;snapshot_id:str;market_state_id:str;funnel_id:str;candidates:tuple[dict,...]
    strategy_version:str=BASELINE_STRATEGY_VERSION;system_version:str=SYSTEM_VERSION;contract_version:str=CONTRACT_VERSION
    schema_version:str="v5.1-morning-pool-v1"
    @property
    def pool_id(self):return content_id("v51mp1",self.to_dict(False))
    def to_dict(self,include_id=True):
        value={"trade_date":self.trade_date,"decided_at":self.decided_at,"tradability_id":self.tradability_id,"snapshot_id":self.snapshot_id,"market_state_id":self.market_state_id,"funnel_id":self.funnel_id,"candidates":_plain(self.candidates),"strategy_version":self.strategy_version,"system_version":self.system_version,"contract_version":self.contract_version,"schema_version":self.schema_version}
        if include_id:value["pool_id"]=self.pool_id
        return value

@dataclass(frozen=True)
class BaselineConfirmationV51:
    trade_date:str;decided_at:str;morning_pool_id:str;decision_snapshot_id:str;market_state_id:str;funnel_id:str;candidates:tuple[dict,...];changes:tuple[dict,...];outcome:str
    strategy_version:str=BASELINE_STRATEGY_VERSION;system_version:str=SYSTEM_VERSION;contract_version:str=CONTRACT_VERSION
    schema_version:str="v5.1-baseline-confirmation-v1"
    @property
    def confirmation_id(self):return content_id("v51confirm1",self.to_dict(False))
    def to_dict(self,include_id=True):
        value={"trade_date":self.trade_date,"decided_at":self.decided_at,"morning_pool_id":self.morning_pool_id,"decision_snapshot_id":self.decision_snapshot_id,"market_state_id":self.market_state_id,"funnel_id":self.funnel_id,"candidates":_plain(self.candidates),"changes":_plain(self.changes),"outcome":self.outcome,"strategy_version":self.strategy_version,"system_version":self.system_version,"contract_version":self.contract_version,"schema_version":self.schema_version}
        if include_id:value["confirmation_id"]=self.confirmation_id
        return value

def build_morning_pool(snapshot,tradability:DailyTradabilityFactV1,*,decided_at,market_state_id,market_valid,policy=None):
    decision=_window(decided_at,MORNING_START,MORNING_END,"morning decision");_snapshot_before(snapshot,decision,"morning_0935",maximum_decision_age_seconds=MAX_MORNING_SNAPSHOT_AGE_SECONDS)
    if tradability.trade_date!=decision.date().isoformat() or not tradability.accepted:raise ContractViolation("accepted same-day tradability required")
    funnel=CandidateFunnel(policy or FunnelPolicyV1()).run(snapshot,market_state_id=market_state_id,market_valid=market_valid,stage="morning",allowed_codes=tradability.eligible_symbols)
    candidates=[]
    for row in funnel.candidates:
        value=_plain(row);value.update({"strategy_version":BASELINE_STRATEGY_VERSION,"system_version":SYSTEM_VERSION,"candidate_origin":"V5.1_BASELINE_0935"});candidates.append(value)
    return MorningPoolV51(decision.date().isoformat(),decision.isoformat(),tradability.tradability_id,snapshot.snapshot_id,market_state_id,funnel.funnel_id,tuple(candidates))

def build_confirmation(pool:MorningPoolV51,snapshot,*,freeze:FeatureFreezeV51,snapshot_repository:DecisionSnapshotRepository,decided_at,market_state_id,market_valid,policy=None):
    decision=_window(decided_at,CONFIRM_START,CONFIRM_END,"confirmation decision");_snapshot_before(snapshot,decision,"signal")
    snapshot_repository.require(freeze,snapshot)
    if pool.trade_date!=decision.date().isoformat():raise ContractViolation("same-day V5.1 morning pool required")
    allowed=[x["code"] for x in pool.candidates]
    # Existing frozen weights/risk thresholds are reused; only the 09:35
    # evidence version changes.  Confirmation can remove, never add.
    baseline=[{k:v for k,v in x.items() if k not in {"strategy_version","system_version","candidate_origin"}} for x in pool.candidates]
    funnel=CandidateFunnel(policy or FunnelPolicyV1()).run(snapshot,market_state_id=market_state_id,market_valid=market_valid,stage="confirmation",allowed_codes=allowed,baseline_candidates=baseline)
    candidates=[];morning={x["code"]:x for x in pool.candidates};changes=[]
    for raw in funnel.candidates:
        row=_plain(raw);row.update({"strategy_version":BASELINE_STRATEGY_VERSION,"system_version":SYSTEM_VERSION,"candidate_origin":"V5.1_BASELINE_0935"});candidates.append(row);prior=morning[row["code"]]
        changes.append({"code":row["code"],"morning_rank":prior["rank"],"morning_score":prior["score"],"change_pct_delta":round(row["change_pct"]-prior["change_pct"],4),"amount_delta":row["amount"]-prior["amount"],"close_location_delta":round(row["factor_values"]["close_location"]-prior["factor_values"]["close_location"],6),"status":"CONFIRMED"})
    confirmed={x["code"] for x in candidates}
    for prior in pool.candidates:
        if prior["code"] not in confirmed:changes.append({"code":prior["code"],"morning_rank":prior["rank"],"morning_score":prior["score"],"status":"REJECTED","reason":"TAIL_CONFIRMATION_FILTER"})
    return BaselineConfirmationV51(pool.trade_date,decision.isoformat(),pool.pool_id,snapshot.snapshot_id,market_state_id,funnel.funnel_id,tuple(candidates),tuple(changes),"BUY_CANDIDATE" if candidates else "EMPTY")
