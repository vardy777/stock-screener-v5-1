"""Persistent, point-in-time A-share identity master separated from daily status."""
from __future__ import annotations
from dataclasses import asdict,dataclass
from datetime import date,datetime
import json
from pathlib import Path
from typing import Iterable
from shared_core.core import CHINA_TZ,ContractViolation,strict_int,strict_str,strict_enum
from . import CONTRACT_VERSION,SYSTEM_VERSION
from .facts import content_id,save_immutable
from .calendar_policy import allowed_master_verification_dates

ALLOWED_EXCHANGES={"SSE","SZSE"};ALLOWED_BOARDS={"MAIN","STAR","CHINEXT"}

def strict_bool(value,field):
    if type(value) is not bool:raise ContractViolation(f"{field}: strict boolean required")
    return value

def aware(value,field):
    try:value=value if isinstance(value,datetime) else datetime.fromisoformat(str(value))
    except (TypeError,ValueError) as exc:raise ContractViolation(f"{field}: invalid datetime") from exc
    if value.tzinfo is None or value.utcoffset() is None:raise ContractViolation(f"{field}: timezone required")
    return value.astimezone(CHINA_TZ)

@dataclass(frozen=True)
class SecurityMasterVersionV1:
    symbol:str;exchange:str;board:str;security_name:str;listing_date:str;delisting_date:str|None
    security_type:str;is_a_share:bool;master_status:str;valid_from:str;valid_to:str|None
    known_at:str;source_family:str;source_record_id:str;system_version:str=SYSTEM_VERSION
    contract_version:str=CONTRACT_VERSION;schema_version:str="v5.1-security-master-version-v1"
    @classmethod
    def build(cls,**row):
        symbol=strict_str(row.get("symbol"),"symbol");exchange=strict_enum(row.get("exchange"),"exchange",ALLOWED_EXCHANGES);board=strict_enum(row.get("board"),"board",ALLOWED_BOARDS);name=strict_str(row.get("security_name"),"security_name").strip()
        if len(symbol)!=6 or not symbol.isdigit() or exchange not in ALLOWED_EXCHANGES or board not in ALLOWED_BOARDS or not name:raise ContractViolation("security master identity invalid")
        listing=date.fromisoformat(str(row["listing_date"]));valid_from=date.fromisoformat(str(row.get("valid_from",listing)))
        delisting=date.fromisoformat(str(row["delisting_date"])) if row.get("delisting_date") else None;valid_to=date.fromisoformat(str(row["valid_to"])) if row.get("valid_to") else None
        if valid_from<listing or (delisting and delisting<listing) or (valid_to and valid_to<valid_from):raise ContractViolation("security master validity invalid")
        known=aware(row.get("known_at"),"known_at");source=strict_str(row.get("source_family"),"source_family").strip();source_record=strict_str(row.get("source_record_id"),"source_record_id").strip()
        if not source or not source_record:raise ContractViolation("security master lineage required")
        status=strict_enum(row.get("master_status","ACTIVE"),"master_status",{"ACTIVE","DELISTED"});security_type=strict_enum(row.get("security_type","EQUITY"),"security_type",{"EQUITY"});is_a=strict_bool(row.get("is_a_share",True),"is_a_share")
        if status not in {"ACTIVE","DELISTED"} or security_type!="EQUITY" or not is_a:raise ContractViolation("unsupported security master scope")
        return cls(symbol,exchange,board,name,listing.isoformat(),delisting.isoformat() if delisting else None,security_type,is_a,status,valid_from.isoformat(),valid_to.isoformat() if valid_to else None,known.isoformat(),source,source_record)
    @property
    def version_id(self):return content_id("smv1",asdict(self))
    def to_dict(self):return {**asdict(self),"version_id":self.version_id}

@dataclass(frozen=True)
class MasterVerificationV1:
    verified_for_trade_date:str;verified_at:str;source_families:tuple[str,...];independent_source_families:tuple[str,...]
    master_version_ids:tuple[str,...];record_count:int;status:str;response_ids:tuple[str,...]=();match_ids:tuple[str,...]=();system_version:str=SYSTEM_VERSION;contract_version:str=CONTRACT_VERSION
    schema_version:str="v5.1-security-master-verification-v1"
    @classmethod
    def build(cls,*,verified_for_trade_date,verified_at,source_families,independent_source_families,master_version_ids,record_count,status="VERIFIED",response_ids=(),match_ids=()):
        day=date.fromisoformat(strict_str(verified_for_trade_date,"verified_for_trade_date")).isoformat();at=aware(verified_at,"verified_at").isoformat()
        for field,values in (("source_families",source_families),("independent_source_families",independent_source_families),("master_version_ids",master_version_ids),("response_ids",response_ids),("match_ids",match_ids)):
            if type(values) not in {list,tuple} or any(type(x) is not str or not x for x in values):raise ContractViolation(f"{field}: strict string sequence required")
        families=tuple(sorted(set(source_families)));independent=tuple(sorted(set(independent_source_families)));versions=tuple(sorted(set(master_version_ids)));strict_int(record_count,"record_count",1)
        if record_count!=len(versions) or not families or not independent or not set(independent)<=set(families) or not versions:raise ContractViolation("master verification lineage invalid")
        strict_enum(status,"status",{"VERIFIED","CONFLICT","FAILED"})
        responses=tuple(sorted(set(response_ids)));matches=tuple(sorted(set(match_ids)))
        if bool(responses)!=bool(matches):raise ContractViolation("master verification evidence lineage incomplete")
        return cls(day,at,families,independent,versions,record_count,status,responses,matches)
    @property
    def verification_id(self):return content_id("smverify1",asdict(self))
    def to_dict(self):return {**asdict(self),"source_families":list(self.source_families),"independent_source_families":list(self.independent_source_families),"master_version_ids":list(self.master_version_ids),"response_ids":list(self.response_ids),"match_ids":list(self.match_ids),"verification_id":self.verification_id}

class SecurityMasterRepository:
    def __init__(self,root):self.root=Path(root)
    def append(self,version):
        if not isinstance(version,SecurityMasterVersionV1):raise ContractViolation("master version required")
        path=self.root/"security_master/versions"/version.symbol/f"{version.version_id}.json";return save_immutable(path,version.to_dict())
    def _validate_verification(self,fact):
        if not isinstance(fact,MasterVerificationV1):raise ContractViolation("master verification fact required")
        versions={row.version_id:row for row in self.versions()};missing=set(fact.master_version_ids)-set(versions)
        if missing:raise ContractViolation("master verification references missing master version")
        verified=aware(fact.verified_at,"verified_at");selected=[versions[x] for x in fact.master_version_ids]
        if any(aware(row.known_at,"master known_at")>verified for row in selected):raise ContractViolation("master verification references future master version")
        selected_sources={row.source_family for row in selected}
        if not selected_sources<=set(fact.source_families) or not set(fact.independent_source_families)<=selected_sources:raise ContractViolation("master verification source lineage invalid")
        day=date.fromisoformat(fact.verified_for_trade_date)
        if any(date.fromisoformat(row.valid_from)>day or (row.valid_to and date.fromisoformat(row.valid_to)<day) for row in selected):raise ContractViolation("master verification version validity mismatch")
        if fact.response_ids:
            from .master_evidence import MasterEvidenceRepository
            MasterEvidenceRepository(self.root).resolve(fact.response_ids,fact.match_ids,selected)
        return fact
    def verify(self,fact):
        self._validate_verification(fact)
        return save_immutable(self.root/"security_master/verifications"/fact.verified_for_trade_date/f"{fact.verification_id}.json",fact.to_dict())
    def versions(self):
        rows=[]
        for path in (self.root/"security_master/versions").glob("*/*.json") if (self.root/"security_master/versions").exists() else ():
            row=json.loads(path.read_text(encoding="utf-8"));declared=row.pop("version_id","")
            if row.get("system_version")!=SYSTEM_VERSION or row.get("contract_version")!=CONTRACT_VERSION:raise ContractViolation("security master version contract mismatch")
            obj=SecurityMasterVersionV1.build(**row)
            if declared!=obj.version_id or path.stem!=obj.version_id:raise ContractViolation("security master content-address mismatch")
            rows.append(obj)
        return rows
    def as_of(self,effective_date,known_at):
        effective=date.fromisoformat(str(effective_date));known=aware(known_at,"known_at");selected={}
        for row in self.versions():
            if aware(row.known_at,"known_at")>known:continue
            if date.fromisoformat(row.valid_from)>effective or (row.valid_to and date.fromisoformat(row.valid_to)<effective):continue
            current=selected.get(row.symbol)
            if current is None or (row.valid_from,row.known_at,row.version_id)>(current.valid_from,current.known_at,current.version_id):selected[row.symbol]=row
        return tuple(sorted((x for x in selected.values() if x.master_status=="ACTIVE"),key=lambda x:x.symbol))
    def require_fresh(self,trade_date,as_of,calendar):
        day=date.fromisoformat(str(trade_date)).isoformat();cutoff=aware(as_of,"as_of");allowed=allowed_master_verification_dates(day,calendar)
        directory=self.root/"security_master/verifications";facts=[]
        for path in directory.glob("*/*.json") if directory.exists() else ():
            row=json.loads(path.read_text(encoding="utf-8"));declared=row.pop("verification_id","")
            if row.get("system_version")!=SYSTEM_VERSION or row.get("contract_version")!=CONTRACT_VERSION:raise ContractViolation("master verification contract mismatch")
            fact=MasterVerificationV1.build(verified_for_trade_date=row["verified_for_trade_date"],verified_at=row["verified_at"],source_families=row["source_families"],independent_source_families=row["independent_source_families"],master_version_ids=row["master_version_ids"],record_count=row["record_count"],status=row["status"],response_ids=row.get("response_ids",()),match_ids=row.get("match_ids",()))
            if declared!=fact.verification_id or path.stem!=fact.verification_id:raise ContractViolation("master verification content-address mismatch")
            self._validate_verification(fact)
            if fact.status=="VERIFIED" and fact.verified_for_trade_date in allowed and aware(fact.verified_at,"verified_at")<=cutoff:facts.append(fact)
        if not facts:raise ContractViolation("security master stale: current or previous completed verification cycle required")
        return max(facts,key=lambda x:(x.verified_for_trade_date,x.verified_at,x.verification_id))

def reconcile_provider_records(provider_records:dict[str,Iterable[SecurityMasterVersionV1]],independent_families:Iterable[str]):
    families={str(k):tuple(v) for k,v in provider_records.items()};independent=set(map(str,independent_families))
    if not independent or not independent<=set(families):raise ContractViolation("independent security master provider required")
    by_symbol={}
    for family,rows in families.items():
        for row in rows:by_symbol.setdefault(row.symbol,[]).append((family,row))
    accepted=[]
    for symbol,rows in sorted(by_symbol.items()):
        independent_rows=[r for family,r in rows if family in independent]
        if not independent_rows:continue
        signatures={(r.exchange,r.board,r.security_name,r.listing_date,r.delisting_date,r.master_status) for r in independent_rows}
        if len(signatures)!=1:raise ContractViolation(f"security master independent source conflict: {symbol}")
        accepted.append(sorted(independent_rows,key=lambda r:(r.known_at,r.version_id))[-1])
    if not accepted:raise ContractViolation("security master reconciliation empty")
    return tuple(accepted)
