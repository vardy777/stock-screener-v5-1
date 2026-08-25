"""Provider-neutral strict V5 acquisition session; no lowered fallback policy."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable,Protocol
from concurrent.futures import ThreadPoolExecutor
from .core import CHINA_TZ,is_market_snapshot
from .contracts import AcquisitionSessionV1
from .universe import UniverseV1
from .market_snapshot import MarketSnapshotV1,QuoteV1

# These describe collection truth for the entire universe.  Per-symbol
# execution states (halt, limit lock, missing book) are intentionally handled
# by the funnel, otherwise one unusable stock closes the whole market.
GLOBAL_STRICT_REASONS={"empty","duplicate_code","incomplete_coverage","batch_delay","provider_clock_skew","cross_trade_date"}

def _provider_lineage_matches(snapshot:object,source_name:str)->bool:
    """A source identity is only independent when every quote carries it."""
    quotes=getattr(snapshot,"quotes",())
    return bool(quotes) and all(getattr(quote,"provider","")==source_name for quote in quotes)

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
                provider_valid=_provider_lineage_matches(snapshot,source.name)
                valid=(snapshot.trade_date==now.date().isoformat() and snapshot.quality.expected_codes==len(universe) and acquisition_accepted(snapshot) and provider_valid)
                attempts.append({"source":source.name,"snapshot_id":snapshot.snapshot_id,"accepted":valid,"coverage":snapshot.quality.coverage,"age_seconds":snapshot.quality.maximum_quote_age_seconds,"batch_seconds":snapshot.quality.batch_duration_seconds,"provider_lineage_valid":provider_valid,"reasons":list(snapshot.quality.reasons)})
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
        if first is second or not getattr(first,"name","") or getattr(first,"name","")==getattr(second,"name",""):
            raise ValueError("consensus requires two distinct source identities")
        self.first=first;self.second=second;self.minimum_match=minimum_match;self.maximum_price_deviation=maximum_price_deviation;self.maximum_time_difference_seconds=maximum_time_difference_seconds
    def acquire(self,universe:UniverseV1,*,stage:str,now:datetime)->ConsensusResult:
        attempts=[];snapshots=[]
        def capture(source):
            try:
                snap=source.capture(list(universe.codes),stage=stage,now=now);provider_valid=is_market_snapshot(snap) and _provider_lineage_matches(snap,source.name);denominator_valid=is_market_snapshot(snap) and snap.quality.expected_codes==len(universe.codes);complete=is_market_snapshot(snap) and snap.trade_date==universe.trade_date and denominator_valid and snap.quality.coverage>=.95 and acquisition_accepted(snap) and provider_valid
                quality=getattr(snap,"quality",None)
                return {"source":source.name,"snapshot_id":getattr(snap,"snapshot_id",""),"coverage":getattr(quality,"coverage",0),"expected_codes":getattr(quality,"expected_codes",0),"age_seconds":getattr(quality,"maximum_quote_age_seconds",None),"batch_seconds":getattr(quality,"batch_duration_seconds",None),"reasons":list(getattr(quality,"reasons",()) or ()),"universe_denominator_valid":denominator_valid,"provider_lineage_valid":provider_valid,"complete":complete},snap if complete else None
            except Exception as exc:return {"source":source.name,"complete":False,"error":f"{type(exc).__name__}: {exc}"},None
        with ThreadPoolExecutor(max_workers=2,thread_name_prefix="v5-source") as executor:
            results=[future.result() for future in [executor.submit(capture,source) for source in (self.first,self.second)]]
        for attempt,snapshot in results:attempts.append(attempt);snapshots.append(snapshot)
        report={"schema_version":"v5-source-consensus-v1","universe_id":universe.universe_id,"attempts":attempts,"accepted":False}
        if None in snapshots:return ConsensusResult(False,None,report)
        left,right=({q.code:q for q in snap.quotes} for snap in snapshots);common=sorted(set(left)&set(right));denominator=len(universe.codes);match=len(common)/denominator
        price_bad=set();time_bad=set();book_bad=set();state_bad=set();execution_books={}
        for code in common:
            a,b=left[code],right[code];base=max(a.last_price,b.last_price)
            if base<=0 or abs(a.last_price-b.last_price)/base>self.maximum_price_deviation:price_bad.add(code)
            if abs((datetime.fromisoformat(a.provider_time)-datetime.fromisoformat(b.provider_time)).total_seconds())>self.maximum_time_difference_seconds:time_bad.add(code)
            if any(datetime.fromisoformat(value).date().isoformat()!=universe.trade_date for value in (a.exchange_time,b.exchange_time,a.provider_time,b.provider_time)):time_bad.add(code)
            if a.halted or b.halted or a.limit_up!=b.limit_up or a.limit_down!=b.limit_down:state_bad.add(code)
            if stage=="buy_execution":
                executable=a.ask1>0 and b.ask1>0 and a.ask1_volume>0 and b.ask1_volume>0
                reference=max(a.ask1,b.ask1)
                if a.limit_up or b.limit_up:state_bad.add(code)
                if not executable or abs(a.ask1-b.ask1)/reference>self.maximum_price_deviation:book_bad.add(code)
                execution_books[code]={"side":"BUY","sources":[{"provider":a.provider,"price":a.ask1,"volume":a.ask1_volume},{"provider":b.provider,"price":b.ask1,"volume":b.ask1_volume}],"consensus_price":max(a.ask1,b.ask1),"consensus_volume":min(a.ask1_volume,b.ask1_volume),"price_rule":"max_ask","depth_rule":"min_depth"}
            elif stage=="sell":
                executable=a.bid1>0 and b.bid1>0 and a.bid1_volume>0 and b.bid1_volume>0
                reference=max(a.bid1,b.bid1)
                if a.limit_down or b.limit_down:state_bad.add(code)
                if not executable or abs(a.bid1-b.bid1)/reference>self.maximum_price_deviation:book_bad.add(code)
                execution_books[code]={"side":"SELL","sources":[{"provider":a.provider,"price":a.bid1,"volume":a.bid1_volume},{"provider":b.provider,"price":b.bid1,"volume":b.bid1_volume}],"consensus_price":min(a.bid1,b.bid1),"consensus_volume":min(a.bid1_volume,b.bid1_volume),"price_rule":"min_bid","depth_rule":"min_depth"}
        conflicts=price_bad|time_bad|book_bad|state_bad
        consistent=(len(common)-len(conflicts))/denominator
        accepted=match>=self.minimum_match and consistent>=self.minimum_match
        report.update({"matched_codes":len(common),"expected_codes":denominator,"match_ratio":match,"price_conflicts":len(price_bad),"time_conflicts":len(time_bad),"execution_book_conflicts":len(book_bad),"state_conflicts":len(state_bad),"conflict_codes":sorted(conflicts),"consistent_codes":sorted(set(common)-conflicts),"consistent_ratio":consistent,"execution_side":"BUY" if stage=="buy_execution" else "SELL" if stage=="sell" else "NONE","execution_books":execution_books,"execution_price_policy":"conservative_max_ask_min_bid","execution_depth_policy":"conservative_minimum_source_depth","accepted":accepted})
        primary=max(snapshots,key=lambda snapshot:(datetime.fromisoformat(snapshot.batch_completed_at),snapshot.snapshot_id))
        if accepted and stage in {"buy_execution","sell"}:
            quotes=[]
            for code in sorted(set(common)-conflicts):
                base=left[code] if datetime.fromisoformat(left[code].provider_time)>=datetime.fromisoformat(right[code].provider_time) else right[code]
                row=base.__dict__.copy();book=execution_books[code];row["provider"]="v5_dual_source_conservative_consensus"
                if stage=="buy_execution":row.update({"ask1":book["consensus_price"],"ask1_volume":book["consensus_volume"]})
                else:row.update({"bid1":book["consensus_price"],"bid1_volume":book["consensus_volume"]})
                quotes.append(QuoteV1.from_mapping(row))
            primary=MarketSnapshotV1.build(trade_date=universe.trade_date,session=stage,batch_started_at=min(x.batch_started_at for x in snapshots),batch_completed_at=max(x.batch_completed_at for x in snapshots),quotes=quotes,expected_codes=denominator)
            report["source_snapshot_ids"]=[snapshot.snapshot_id for snapshot in snapshots]
        report["selected_snapshot_id"]=primary.snapshot_id if accepted else ""
        return ConsensusResult(accepted,primary if accepted else None,report)
