"""Provider-neutral strict V5 acquisition session; no lowered fallback policy."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable,Protocol
from .core import CHINA_TZ,is_market_snapshot
from .contracts import AcquisitionSessionV1
from .universe import UniverseV1

# These describe collection truth for the entire universe.  Per-symbol
# execution states (halt, limit lock, missing book) are intentionally handled
# by the funnel, otherwise one unusable stock closes the whole market.
GLOBAL_STRICT_REASONS={"empty","duplicate_code","incomplete_coverage","batch_delay","provider_clock_skew","cross_trade_date"}

def acquisition_accepted(snapshot:MarketSnapshotV1)->bool:
    return not any(reason in GLOBAL_STRICT_REASONS for reason in snapshot.quality.reasons)

class SnapshotSource(Protocol):
    name:str
    def capture(self,codes:list[str],*,stage:str,now:datetime): ...
@dataclass(frozen=True)
class AcquisitionResult:
    session:AcquisitionSessionV1; snapshot:object|None
class MultiSourceAcquirer:
    def __init__(self,sources:Iterable[SnapshotSource]):
        self.sources=tuple(sources)
        if not self.sources:raise ValueError("at least one source is required")
    def acquire(self,codes:Iterable[str],*,stage:str,now:datetime)->AcquisitionResult:
        if now.tzinfo is None or now.utcoffset() is None:raise ValueError("now: timezone-aware required")
        now=now.astimezone(CHINA_TZ);universe=sorted({str(x).zfill(6) for x in codes if str(x)})
        if not universe:raise ValueError("codes: non-empty required")
        attempts=[];selected=None
        for source in self.sources:
            try:
                snapshot=source.capture(universe,stage=stage,now=now)
                if not is_market_snapshot(snapshot):raise TypeError("source did not return a versioned market snapshot")
                valid=(snapshot.trade_date==now.date().isoformat() and snapshot.quality.expected_codes==len(universe) and acquisition_accepted(snapshot))
                attempts.append({"source":source.name,"snapshot_id":snapshot.snapshot_id,"accepted":valid,"coverage":snapshot.quality.coverage,"age_seconds":snapshot.quality.maximum_quote_age_seconds,"batch_seconds":snapshot.quality.batch_duration_seconds,"reasons":list(snapshot.quality.reasons)})
                if valid:selected=snapshot;break
            except Exception as exc:attempts.append({"source":source.name,"accepted":False,"error":f"{type(exc).__name__}: {exc}"})
        session=AcquisitionSessionV1.build(trade_date=now.date().isoformat(),stage=stage,requested_at=now,expected_codes=len(universe),selected_snapshot_id=selected.snapshot_id if selected else "",accepted=selected is not None,source_attempts=attempts)
        return AcquisitionResult(session,selected)

@dataclass(frozen=True)
class ConsensusResult:
    accepted:bool;primary:object|None;report:dict

class ConsensusAcquirer:
    """Require two independently complete snapshots and compare common symbols."""
    def __init__(self,first:SnapshotSource,second:SnapshotSource,*,minimum_match=.95,maximum_price_deviation=.005,maximum_time_difference_seconds=15):
        self.first=first;self.second=second;self.minimum_match=minimum_match;self.maximum_price_deviation=maximum_price_deviation;self.maximum_time_difference_seconds=maximum_time_difference_seconds
    def acquire(self,universe:UniverseV1,*,stage:str,now:datetime)->ConsensusResult:
        attempts=[];snapshots=[]
        for source in (self.first,self.second):
            try:
                snap=source.capture(list(universe.codes),stage=stage,now=now);complete=is_market_snapshot(snap) and snap.trade_date==universe.trade_date and snap.quality.coverage>=.95 and acquisition_accepted(snap)
                attempts.append({"source":source.name,"snapshot_id":getattr(snap,"snapshot_id",""),"coverage":getattr(getattr(snap,"quality",None),"coverage",0),"complete":complete});snapshots.append(snap if complete else None)
            except Exception as exc:attempts.append({"source":source.name,"complete":False,"error":f"{type(exc).__name__}: {exc}"});snapshots.append(None)
        report={"schema_version":"v5-source-consensus-v1","universe_id":universe.universe_id,"attempts":attempts,"accepted":False}
        if None in snapshots:return ConsensusResult(False,None,report)
        left,right=({q.code:q for q in snap.quotes} for snap in snapshots);common=sorted(set(left)&set(right));denominator=len(universe.codes);match=len(common)/denominator
        price_bad=0;time_bad=0
        for code in common:
            a,b=left[code],right[code];base=max(a.last_price,b.last_price)
            if base<=0 or abs(a.last_price-b.last_price)/base>self.maximum_price_deviation:price_bad+=1
            if abs((datetime.fromisoformat(a.exchange_time)-datetime.fromisoformat(b.exchange_time)).total_seconds())>self.maximum_time_difference_seconds:time_bad+=1
        consistent=(len(common)-price_bad-time_bad)/denominator
        accepted=match>=self.minimum_match and consistent>=self.minimum_match
        report.update({"matched_codes":len(common),"expected_codes":denominator,"match_ratio":match,"price_conflicts":price_bad,"time_conflicts":time_bad,"consistent_ratio":consistent,"accepted":accepted})
        return ConsensusResult(accepted,snapshots[0] if accepted else None,report)
