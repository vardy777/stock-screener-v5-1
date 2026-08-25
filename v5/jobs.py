"""V5 fact production jobs. Shadow-only until live acceptance changes state."""
from __future__ import annotations
from datetime import datetime
import hashlib,json,os
from pathlib import Path
from .core import CHINA_TZ,ContractViolation
from .universe import UniverseV1
from .sina_source import SinaRealtimeSource
from .tencent_source import TencentRealtimeSource
from .data_production import ConsensusAcquirer
from .funnel import CandidateFunnel
from .decision_flow import MorningPoolV5,ConfirmationV5
from .storage import V5FactStore
from .contracts import AcquisitionSessionV1
from .paper_production import load_snapshot,PaperProduction
from .fact_reader import latest
from .ownership import require as require_ownership
from .calendar import TradingCalendar
from .market_state import MarketStateV1
from .factor_research import observations_from_snapshot,analyze as analyze_factors

NATIVE_UNIVERSE_SOURCE = "eastmoney_realtime_market_directory"

def load_universe(root,day,*,as_of=None,require_native=False):
    files=list((Path(root)/"universes"/day).glob("*.json"))
    if not files:raise ContractViolation("V5 universe fact missing")
    rows=[json.loads(path.read_text(encoding="utf-8")) for path in files]
    if as_of is not None:
        if as_of.tzinfo is None:raise ContractViolation("universe as_of timezone required")
        cutoff=as_of.astimezone(CHINA_TZ)
        rows=[row for row in rows if datetime.fromisoformat(row["created_at"]).astimezone(CHINA_TZ)<=cutoff]
        if not rows:raise ContractViolation("causal V5 universe fact missing")
    if require_native:
        rows=[row for row in rows if NATIVE_UNIVERSE_SOURCE in row.get("sources",())]
        if not rows:raise ContractViolation("native V5 universe fact missing")
    selected=max(rows,key=lambda row:(datetime.fromisoformat(row["created_at"]),row["universe_id"]))
    return UniverseV1.from_mapping(selected)
def _latest(root,kind,day):
    return latest(root,kind,day)
def _save_immutable(root,kind,day,prefix,payload):
    raw=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":"));entity_id=prefix+hashlib.sha256(raw.encode()).hexdigest()[:24];path=Path(root)/kind/day/f"{entity_id}.json";path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(f".{os.getpid()}.tmp");tmp.write_text(raw,encoding="utf-8")
    try:os.link(tmp,path)
    except FileExistsError:
        if path.read_text(encoding="utf-8")!=raw:raise ContractViolation(f"{kind} immutable collision")
    finally:tmp.unlink(missing_ok=True)
    return entity_id,path
def produce(root,stage,*,now=None,sources=None):
    if stage != "morning":
        raise ContractViolation("live production is morning-only; confirmation must consume the 14:49 frozen snapshot")
    current=(now or datetime.now(CHINA_TZ)).astimezone(CHINA_TZ);day=current.date().isoformat();universe=load_universe(root,day,as_of=current,require_native=True);sources=sources or (SinaRealtimeSource(),TencentRealtimeSource());result=ConsensusAcquirer(*sources).acquire(universe,stage=stage,now=current)
    _save_immutable(root,"consensus",day,"cons1-",result.report)
    attempts=result.report.get("attempts",[]);session=AcquisitionSessionV1.build(trade_date=day,stage=stage,requested_at=current,expected_codes=len(universe.codes),selected_snapshot_id=result.primary.snapshot_id if result.accepted else "",accepted=result.accepted,source_attempts=attempts);store=V5FactStore(root);store.save_session(session)
    if not result.accepted:raise ContractViolation("V5 dual-source consensus rejected")
    store.save_snapshot(result.primary);market=MarketStateV1.from_snapshot(result.primary);store.save_market_state(market);funnel=CandidateFunnel()
    fact=funnel.run(result.primary,market_state_id=market.market_state_id,market_valid=market.trade_allowed,stage="morning");store.save_funnel(fact)
    observations=observations_from_snapshot(result.primary);diagnostics=analyze_factors(observations)|{"trade_date":day,"snapshot_id":result.primary.snapshot_id,"cohort":"full_eligible_09_25_cross_section","strict_labels_joined":False,"observations":observations};_save_immutable(root,"factor_diagnostics",day,"fac1-",diagnostics)
    completed=datetime.fromisoformat(result.primary.batch_completed_at).astimezone(CHINA_TZ)
    entity=MorningPoolV5.from_funnel(fact,created_at=completed);store.save_pool(entity);return entity.to_dict()

def confirm_frozen(root,*,now=None):
    current=(now or datetime.now(CHINA_TZ)).astimezone(CHINA_TZ);day=current.date().isoformat();pointer_path=Path(root)/"frozen"/day/"signal.json"
    if not pointer_path.exists():raise ContractViolation("14:49 frozen snapshot missing")
    pointer=json.loads(pointer_path.read_text(encoding="utf-8"));snapshot_id=pointer["snapshot_id"];paths=list((Path(root)/"snapshots"/day).glob(f"{snapshot_id}.json"))
    if len(paths)!=1:raise ContractViolation("frozen snapshot content missing")
    snapshot=load_snapshot(paths[0]);pool_raw=_latest(root,"morning_pools",day);pool=MorningPoolV5(pool_raw["trade_date"],pool_raw["created_at"],pool_raw["funnel_id"],pool_raw["snapshot_id"],pool_raw["market_state_id"],tuple(pool_raw["candidates"]));market=MarketStateV1.from_snapshot(snapshot);store=V5FactStore(root);store.save_market_state(market);funnel=CandidateFunnel().run(snapshot,market_state_id=market.market_state_id,market_valid=market.trade_allowed,stage="confirmation",allowed_codes=[x["code"] for x in pool.candidates],baseline_candidates=pool.candidates);store.save_funnel(funnel);entity=ConfirmationV5.from_funnel(pool,funnel,decided_at=current);store.save_confirmation(entity);return entity.to_dict()

def freeze(root,*,now=None,sources=None):
    current=(now or datetime.now(CHINA_TZ)).astimezone(CHINA_TZ);day=current.date().isoformat();universe=load_universe(root,day,as_of=current,require_native=True);sources=sources or (SinaRealtimeSource(),TencentRealtimeSource());result=ConsensusAcquirer(*sources).acquire(universe,stage="signal",now=current);_save_immutable(root,"consensus",day,"cons1-",result.report)
    attempts=result.report.get("attempts",[]);session=AcquisitionSessionV1.build(trade_date=day,stage="signal",requested_at=current,expected_codes=len(universe.codes),selected_snapshot_id=result.primary.snapshot_id if result.accepted else "",accepted=result.accepted,source_attempts=attempts);store=V5FactStore(root);store.save_session(session)
    if not result.accepted:raise ContractViolation("V5 feature freeze consensus rejected")
    store.save_snapshot(result.primary);market=MarketStateV1.from_snapshot(result.primary);store.save_market_state(market);pointer=Path(root)/"frozen"/day/"signal.json";pointer.parent.mkdir(parents=True,exist_ok=True);completed=datetime.fromisoformat(result.primary.batch_completed_at).astimezone(CHINA_TZ);pointer_value={"snapshot_id":result.primary.snapshot_id,"frozen_at":completed.isoformat(),"acquisition_session_id":session.session_id};raw=json.dumps(pointer_value,sort_keys=True,separators=(",",":"));tmp=pointer.with_suffix(f".{os.getpid()}.tmp");tmp.write_text(raw,encoding="utf-8")
    try:os.link(tmp,pointer)
    except FileExistsError:
        if pointer.read_text(encoding="utf-8")!=raw:raise ContractViolation("14:49 frozen pointer immutable collision")
    finally:tmp.unlink(missing_ok=True)
    return pointer_value

def paper_buy(root,*,now=None,sources=None):
    root=Path(root);require_ownership(root/"ownership.json","paper_writer");current=(now or datetime.now(CHINA_TZ)).astimezone(CHINA_TZ);day=current.date().isoformat();confirmation=_latest(root,"confirmations",day);pointer=json.loads((root/"frozen"/day/"signal.json").read_text(encoding="utf-8"))
    validated=ConfirmationV5(confirmation["trade_date"],confirmation["decided_at"],confirmation["morning_pool_id"],confirmation["funnel_id"],confirmation["snapshot_id"],confirmation["market_state_id"],tuple(confirmation["candidates"]),tuple(confirmation["changes"]),confirmation["outcome"])
    if confirmation.get("confirmation_id")!=validated.confirmation_id:raise ContractViolation("V5 paper buy confirmation hash mismatch")
    if confirmation.get("snapshot_id")!=pointer.get("snapshot_id"):raise ContractViolation("V5 paper buy frozen lineage mismatch")
    if confirmation.get("outcome")=="EMPTY" and not confirmation.get("candidates"):
        return {"outcome":"NO_CANDIDATE","confirmation_id":confirmation.get("confirmation_id", ""),"events":[]}
    codes={confirmation["candidates"][0]["code"]}
    challenger_dir=root/"challengers"/"volume_price_v1"/"confirmations"/day
    for path in challenger_dir.glob("*.json") if challenger_dir.exists() else ():
        row=json.loads(path.read_text(encoding="utf-8"));candidates=row.get("candidates",[])
        if candidates:codes.add(candidates[0]["code"])
    sources=sources or (SinaRealtimeSource(),TencentRealtimeSource());universe=UniverseV1.build(trade_date=day,created_at=current,codes=sorted(codes),sources=["v5_final_execution_symbols"]);result=ConsensusAcquirer(*sources).acquire(universe,stage="buy_execution",now=current)
    consensus_path=_save_immutable(root,"consensus",day,"cons1-",result.report)
    if not result.accepted or set(result.report.get("consistent_codes",()))!=codes:raise ContractViolation("V5 final-symbol buy consensus rejected")
    store=V5FactStore(root);store.save_snapshot(result.primary);executed_at=datetime.fromisoformat(result.primary.batch_completed_at).astimezone(CHINA_TZ)
    event=PaperProduction(root).buy(confirmation,result.primary,at=executed_at,eligible_sell_date=TradingCalendar().next_open(current.date()).isoformat())
    context={"schema_version":"v5-paper-execution-context-v1","side":"BUY","trade_date":day,"recorded_at":executed_at.isoformat(),"decision_id":confirmation["confirmation_id"],"decision_snapshot_id":confirmation["snapshot_id"],"execution_snapshot_id":result.primary.snapshot_id,"consensus_fact":str(consensus_path.relative_to(root)),"consistent_codes":sorted(codes),"order_id":event.order_id}
    context_path=_save_immutable(root,"execution_contexts",day,"exec1-",context)
    return event.__dict__|{"execution_snapshot_id":result.primary.snapshot_id,"decision_snapshot_id":confirmation["snapshot_id"],"execution_context":str(context_path.relative_to(root))}

def paper_sell(root,*,now=None,sources=None):
    root=Path(root);require_ownership(root/"ownership.json","paper_writer");current=(now or datetime.now(CHINA_TZ)).astimezone(CHINA_TZ);day=current.date().isoformat();positions=PaperProduction(root).ledger.state()["positions"]
    confirmations=[]
    for path in (root/"confirmations").glob("*/*.json") if (root/"confirmations").exists() else []:
        row=json.loads(path.read_text(encoding="utf-8"))
        if TradingCalendar().next_open(datetime.fromisoformat(row["decided_at"]).date())==current.date():confirmations.append(row)
    # One sell-window capture serves the production baseline and all isolated
    # shadow positions.  This avoids a second market request and preserves a
    # directly comparable execution timestamp.
    from .challenger import position_codes as challenger_position_codes
    shadow_codes=challenger_position_codes(root)
    codes=sorted({row["code"] for row in positions}|shadow_codes|{candidate["code"] for confirmation in confirmations for candidate in confirmation.get("candidates",[])})
    if not codes:return {"events":[],"baselines":[],"snapshot_id":"","outcome":"NO_POSITIONS_OR_BASELINE"}
    sources=sources or (SinaRealtimeSource(),TencentRealtimeSource());universe=UniverseV1.build(trade_date=day,created_at=current,codes=codes,sources=["v5_open_positions_and_baseline"]);result=ConsensusAcquirer(*sources).acquire(universe,stage="sell",now=current)
    _save_immutable(root,"consensus",day,"cons1-",result.report);attempts=result.report.get("attempts",[]);session=AcquisitionSessionV1.build(trade_date=day,stage="sell",requested_at=current,expected_codes=len(universe.codes),selected_snapshot_id=result.primary.snapshot_id if result.accepted else "",accepted=result.accepted,source_attempts=attempts);store=V5FactStore(root);store.save_session(session)
    if not result.accepted or set(result.report.get("consistent_codes",()))!=set(codes):raise ContractViolation("V5 final-symbol sell consensus rejected")
    store.save_snapshot(result.primary);executed_at=datetime.fromisoformat(result.primary.batch_completed_at).astimezone(CHINA_TZ);production=PaperProduction(root);events=production.sell_all(result.primary,at=executed_at)
    if len(events)!=len(positions):raise ContractViolation("V5 paper sell missing executable bid")
    outcomes=[event.outcome for event in events]
    baselines=[]
    if outcomes and all(value=="FILLED" for value in outcomes):
        for confirmation in confirmations:
            contexts=[]
            for path in (root/"execution_contexts"/confirmation["trade_date"]).glob("*.json") if (root/"execution_contexts"/confirmation["trade_date"]).exists() else ():
                value=json.loads(path.read_text(encoding="utf-8"))
                if value.get("decision_id")==confirmation["confirmation_id"] and value.get("side")=="BUY":contexts.append(value)
            if not contexts:raise ContractViolation("V5 baseline buy execution context missing")
            context=max(contexts,key=lambda value:value["recorded_at"]);buy_snapshot=load_snapshot(root/"snapshots"/confirmation["trade_date"]/f"{context['execution_snapshot_id']}.json");baselines.append(production.save_baseline(confirmation,buy_snapshot,result.primary,at=executed_at,decision_snapshot_id=context["decision_snapshot_id"]))
    return {"events":[event.__dict__ for event in events],"baselines":baselines,"snapshot_id":result.primary.snapshot_id,"outcome":"FILLED" if outcomes and all(value=="FILLED" for value in outcomes) else "PARTIALLY_FILLED" if "FILLED" in outcomes else "UNFILLED"}
