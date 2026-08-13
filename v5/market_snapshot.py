"""Native immutable V5 market snapshot contracts."""
from __future__ import annotations
from dataclasses import asdict,dataclass
from datetime import date,datetime
import hashlib,json
from math import isfinite
from typing import Iterable,Mapping,Any
from .core import CHINA_TZ,ContractViolation

def _aware(value,field):
    try:value=value if isinstance(value,datetime) else datetime.fromisoformat(str(value))
    except (TypeError,ValueError) as exc:raise ContractViolation(f"{field}: invalid datetime") from exc
    if value.tzinfo is None or value.utcoffset() is None:raise ContractViolation(f"{field}: timezone required")
    return value.astimezone(CHINA_TZ)
def _number(value,field,positive=False):
    try:result=float(value)
    except (TypeError,ValueError) as exc:raise ContractViolation(f"{field}: invalid number") from exc
    if not isfinite(result) or (positive and result<=0):raise ContractViolation(f"{field}: out of range")
    return result
def _integer(value,field):
    try:result=int(value)
    except (TypeError,ValueError) as exc:raise ContractViolation(f"{field}: invalid integer") from exc
    if result<0 or float(value)!=result:raise ContractViolation(f"{field}: out of range")
    return result

@dataclass(frozen=True)
class QuoteV1:
    code:str;name:str;trade_date:str;exchange_time:str;provider_time:str;received_at:str
    last_price:float;previous_close:float;open_price:float;high_price:float;low_price:float
    bid1:float;bid1_volume:int;ask1:float;ask1_volume:int;volume:int;amount:float
    halted:bool;limit_up:bool;limit_down:bool;provider:str;schema_version:str="v5-quote-v1"
    @classmethod
    def from_mapping(cls,row:Mapping[str,Any]):
        code=str(row.get("code",""));name=str(row.get("name","")).strip();provider=str(row.get("provider","")).strip()
        if len(code)!=6 or not code.isdigit() or not name or not provider:raise ContractViolation("quote identity invalid")
        try:declared=date.fromisoformat(str(row["trade_date"]))
        except (KeyError,ValueError) as exc:raise ContractViolation("trade_date invalid") from exc
        exchange=_aware(row.get("exchange_time"),"exchange_time");provider_time=_aware(row.get("provider_time"),"provider_time");received=_aware(row.get("received_at"),"received_at")
        if exchange.date()!=declared or provider_time<exchange or received<provider_time:raise ContractViolation("quote time lineage invalid")
        return cls(code,name,declared.isoformat(),exchange.isoformat(),provider_time.isoformat(),received.isoformat(),
            _number(row.get("last_price"),"last_price",True),_number(row.get("previous_close"),"previous_close",True),
            _number(row.get("open_price"),"open_price",True),_number(row.get("high_price"),"high_price",True),_number(row.get("low_price"),"low_price",True),
            _number(row.get("bid1"),"bid1"),_integer(row.get("bid1_volume"),"bid1_volume"),_number(row.get("ask1"),"ask1"),_integer(row.get("ask1_volume"),"ask1_volume"),
            _integer(row.get("volume"),"volume"),_number(row.get("amount"),"amount"),bool(row.get("halted")),bool(row.get("limit_up")),bool(row.get("limit_down")),provider)
    def to_dict(self):return asdict(self)

@dataclass(frozen=True)
class SnapshotQualityV1:
    expected_codes:int;valid_codes:int;coverage:float;maximum_quote_age_seconds:float;batch_duration_seconds:float;accepted:bool;reasons:tuple[str,...]

@dataclass(frozen=True)
class MarketSnapshotV1:
    trade_date:str;session:str;batch_started_at:str;batch_completed_at:str;quotes:tuple[QuoteV1,...];quality:SnapshotQualityV1;schema_version:str="v5-market-snapshot-v1"
    @classmethod
    def build(cls,*,trade_date,session,batch_started_at,batch_completed_at,quotes:Iterable[QuoteV1],expected_codes,minimum_coverage=.95,maximum_age_seconds=30,maximum_batch_seconds=30):
        started=_aware(batch_started_at,"batch_started_at");completed=_aware(batch_completed_at,"batch_completed_at");items=tuple(quotes);expected=int(expected_codes)
        if completed<started or expected<1 or not all(isinstance(x,QuoteV1) for x in items):raise ContractViolation("snapshot inputs invalid")
        codes=[x.code for x in items];coverage=len(set(codes))/expected;ages=[(completed-datetime.fromisoformat(x.exchange_time)).total_seconds() for x in items]
        reasons=[]
        if not items:reasons.append("empty")
        if len(codes)!=len(set(codes)):reasons.append("duplicate_code")
        if any(x.trade_date!=str(trade_date) for x in items):reasons.append("cross_trade_date")
        if coverage<minimum_coverage:reasons.append("incomplete_coverage")
        duration=(completed-started).total_seconds()
        if duration>maximum_batch_seconds:reasons.append("batch_delay")
        maximum_age=max(ages,default=0.0)
        if any(x<0 for x in ages) or maximum_age>maximum_age_seconds:reasons.append("provider_clock_skew")
        quality=SnapshotQualityV1(expected,len(set(codes)),coverage,maximum_age,duration,not reasons,tuple(reasons or ["ok"]))
        return cls(str(trade_date),str(session),started.isoformat(),completed.isoformat(),items,quality)
    @property
    def snapshot_id(self):
        body={"trade_date":self.trade_date,"session":self.session,"batch_started_at":self.batch_started_at,"batch_completed_at":self.batch_completed_at,"quotes":[x.to_dict() for x in self.quotes],"quality":asdict(self.quality),"schema_version":self.schema_version}
        return "ms1-"+hashlib.sha256(json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
