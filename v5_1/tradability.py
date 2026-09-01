"""Same-day security status and deterministic V5.1 tradability facts."""
from __future__ import annotations
from dataclasses import asdict,dataclass
from datetime import date,datetime
from typing import Iterable
import json
from pathlib import Path
from shared_core.core import ContractViolation,strict_bool as shared_strict_bool,strict_number
from . import CONTRACT_VERSION,SYSTEM_VERSION
from .facts import content_id
from .security_master import MasterVerificationV1,SecurityMasterRepository,SecurityMasterVersionV1,aware,strict_bool
from .facts import save_immutable

@dataclass(frozen=True)
class DailySecurityStatusV1:
    trade_date:str;symbol:str;observed_at:str;known_at:str;is_st:bool;suspended:bool;delisting_period:bool;new_listing:bool
    status_known:bool;conflict:bool;source_families:tuple[str,...];source_snapshot_ids:tuple[str,...]=();system_version:str=SYSTEM_VERSION
    contract_version:str=CONTRACT_VERSION;schema_version:str="v5.1-daily-security-status-v1"
    @classmethod
    def build(cls,**row):
        day=date.fromisoformat(str(row["trade_date"])).isoformat();symbol=str(row["symbol"]);observed=aware(row["observed_at"],"observed_at")
        if len(symbol)!=6 or not symbol.isdigit() or observed.date().isoformat()!=day:raise ContractViolation("daily status identity/time invalid")
        known=aware(row.get("known_at",observed),"known_at");sources=tuple(sorted(set(map(str,row.get("source_families",())))))
        if known<observed:raise ContractViolation("daily status known_at precedes observation")
        if not sources:raise ContractViolation("daily status source required")
        values={name:strict_bool(row.get(name,default),name) for name,default in (("is_st",False),("suspended",False),("delisting_period",False),("new_listing",False),("status_known",True),("conflict",False))}
        snapshots=tuple(sorted(set(map(str,row.get("source_snapshot_ids",())))))
        if values["status_known"] and len(snapshots)!=len(sources):raise ContractViolation("known daily status requires source snapshot per family")
        return cls(day,symbol,observed.isoformat(),known.isoformat(),values["is_st"],values["suspended"],values["delisting_period"],values["new_listing"],values["status_known"],values["conflict"],sources,snapshots)
    @property
    def status_id(self):return content_id("dsstatus1",{**asdict(self),"source_families":list(self.source_families),"source_snapshot_ids":list(self.source_snapshot_ids)})
    def to_dict(self):return {**asdict(self),"source_families":list(self.source_families),"source_snapshot_ids":list(self.source_snapshot_ids),"status_id":self.status_id}

@dataclass(frozen=True)
class DailyTradabilityFactV1:
    trade_date:str;decided_at:str;master_verification_id:str;master_version_ids:tuple[str,...];status_ids:tuple[str,...]
    eligible_symbols:tuple[str,...];rejections:tuple[dict,...];coverage:float;accepted:bool
    system_version:str=SYSTEM_VERSION;contract_version:str=CONTRACT_VERSION;schema_version:str="v5.1-daily-tradability-v1"
    def __post_init__(self):
        aware(self.decided_at,"decided_at");shared_strict_bool(self.accepted,"accepted");strict_number(self.coverage,"coverage")
        if not 0<=self.coverage<=1:raise ContractViolation("tradability coverage out of range")
    @property
    def tradability_id(self):return content_id("tradability1",self.to_dict(include_id=False))
    def to_dict(self,include_id=True):
        value={**asdict(self),"master_version_ids":list(self.master_version_ids),"status_ids":list(self.status_ids),"eligible_symbols":list(self.eligible_symbols),"rejections":list(self.rejections)}
        if include_id:value["tradability_id"]=self.tradability_id
        return value

class DailySecurityStatusRepository:
    def __init__(self,root):self.root=Path(root)
    def save(self,status):
        if not isinstance(status,DailySecurityStatusV1):raise ContractViolation("daily security status fact required")
        return save_immutable(self.root/"daily_security_statuses"/status.trade_date/status.symbol/f"{status.status_id}.json",status.to_dict())
    def resolve(self,status_id):
        matches=list((self.root/"daily_security_statuses").glob(f"*/*/{status_id}.json")) if (self.root/"daily_security_statuses").exists() else []
        if len(matches)!=1:raise ContractViolation("daily security status missing or ambiguous")
        row=json.loads(matches[0].read_text(encoding="utf-8"));declared=row.pop("status_id","")
        if row.get("system_version")!=SYSTEM_VERSION or row.get("contract_version")!=CONTRACT_VERSION:raise ContractViolation("daily security status contract mismatch")
        fact=DailySecurityStatusV1.build(**row)
        if declared!=fact.status_id or matches[0].stem!=fact.status_id:raise ContractViolation("daily security status content-address mismatch")
        return fact
    def as_of(self,trade_date,symbol,as_of):
        cutoff=aware(as_of,"as_of");folder=self.root/"daily_security_statuses"/str(trade_date)/str(symbol);rows=[]
        for path in folder.glob("*.json") if folder.exists() else ():
            fact=self.resolve(path.stem)
            if aware(fact.known_at,"known_at")<=cutoff:rows.append(fact)
        if len(rows)!=1:raise ContractViolation("daily security status missing or ambiguous as-of")
        return rows[0]

def derive_tradability(master:Iterable[SecurityMasterVersionV1],statuses:Iterable[DailySecurityStatusV1],*,trade_date,decided_at,master_verification:MasterVerificationV1,master_repository:SecurityMasterRepository,status_repository:DailySecurityStatusRepository,calendar):
    day=date.fromisoformat(str(trade_date)).isoformat();at=aware(decided_at,"decided_at");master_items=tuple(master);masters={x.symbol:x for x in master_items};rows={}
    if len(masters)!=len(master_items):raise ContractViolation("ambiguous duplicate master symbol")
    verified=master_repository.require_fresh(day,at,calendar)
    if not isinstance(master_verification,MasterVerificationV1) or verified.verification_id!=master_verification.verification_id:raise ContractViolation("resolved master verification required")
    if any(aware(row.known_at,"master known_at")>at for row in masters.values()):raise ContractViolation("future master version forbidden")
    if set(master_verification.master_version_ids)!=set(x.version_id for x in masters.values()):raise ContractViolation("tradability master versions do not match verification")
    for status in statuses:
        stored=status_repository.resolve(status.status_id)
        if stored!=status:raise ContractViolation("daily security status lineage mismatch")
        if status.trade_date!=day or aware(status.observed_at,"observed_at")>at or aware(status.known_at,"known_at")>at:raise ContractViolation("daily status future/cross-date evidence")
        if status.symbol in rows:raise ContractViolation("ambiguous duplicate daily status")
        rows[status.symbol]=status
    if set(rows)-set(masters):raise ContractViolation("daily status symbol missing from master")
    for symbol,status in rows.items():
        if status_repository.as_of(day,symbol,at).status_id!=status.status_id:raise ContractViolation("daily security status repository selection mismatch")
    coverage=len(set(masters)&set(rows))/max(len(masters),1);eligible=[];rejections=[]
    for symbol in sorted(masters):
        status=rows.get(symbol);reason="MISSING_STATUS" if status is None else "AMBIGUOUS_STATUS" if status.conflict or not status.status_known else "ST" if status.is_st else "SUSPENDED" if status.suspended else "DELISTING_PERIOD" if status.delisting_period else "NEW_LISTING" if status.new_listing else ""
        if reason:rejections.append({"symbol":symbol,"reason":reason})
        else:eligible.append(symbol)
    accepted=coverage==1.0 and not any(x["reason"] in {"MISSING_STATUS","AMBIGUOUS_STATUS"} for x in rejections)
    if not accepted:eligible=[]
    return DailyTradabilityFactV1(day,at.isoformat(),master_verification.verification_id,tuple(sorted(x.version_id for x in masters.values())),tuple(sorted(x.status_id for x in rows.values())),tuple(eligible),tuple(rejections),coverage,accepted)
