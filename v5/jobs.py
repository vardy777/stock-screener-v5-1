"""V5 fact production jobs. Shadow-only until live acceptance changes state."""
from __future__ import annotations
from datetime import datetime
import hashlib,json,os
from pathlib import Path
from .core import CHINA_TZ,ContractViolation
from .universe import UniverseV1
from .sina_source import SinaRealtimeSource
from .eastmoney_source import EastmoneyRealtimeSource
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
    current=(now or datetime.now(CHINA_TZ)).astimezone(CHINA_TZ);day=current.date().isoformat();universe=load_universe(root,day,as_of=current,require_native=True);sources=sources or (SinaRealtimeSource(),EastmoneyRealtimeSource());result=ConsensusAcquirer(*sources).acquire(universe,stage=stage,now=current)
    _save_immutable(root,"consensus",day,"cons1-",result.report)
    attempts=result.report.get("attempts",[]);session=AcquisitionSessionV1.build(trade_date=day,stage=stage,requested_at=current,expected_codes=len(universe.codes),selected_snapshot_id=result.primary.snapshot_id if result.accepted else "",accepted=result.accepted,source_attempts=attempts);store=V5FactStore(root);store.save_session(session)
    if not result.accepted:raise ContractViolation("V5 dual-source consensus rejected")
    store.save_snapshot(result.primary);market=MarketStateV1.from_snapshot(result.primary);store.save_market_state(market);funnel=CandidateFunnel()
    fact=funnel.run(result.primary,market_state_id=market.market_state_id,market_valid=market.trade_allowed,stage="morning");store.save_funnel(fact)
    entity=MorningPoolV5.from_funnel(fact,created_at=current);store.save_pool(entity);return entity.to_dict()

def confirm_frozen(root,*,now=None):
    current=(now or datetime.now(CHINA_TZ)).astimezone(CHINA_TZ);day=current.date().isoformat();pointer_path=Path(root)/"frozen"/day/"signal.json"
    if not pointer_path.exists():raise ContractViolation("14:49 frozen snapshot missing")
    pointer=json.loads(pointer_path.read_text(encoding="utf-8"));snapshot_id=pointer["snapshot_id"];paths=list((Path(root)/"snapshots"/day).glob(f"{snapshot_id}.json"))
    if len(paths)!=1:raise ContractViolation("frozen snapshot content missing")
    snapshot=load_snapshot(paths[0]);pool_raw=_latest(root,"morning_pools",day);pool=MorningPoolV5(pool_raw["trade_date"],pool_raw["created_at"],pool_raw["funnel_id"],pool_raw["snapshot_id"],pool_raw["market_state_id"],tuple(pool_raw["candidates"]));market=MarketStateV1.from_snapshot(snapshot);store=V5FactStore(root);store.save_market_state(market);funnel=CandidateFunnel().run(snapshot,market_state_id=market.market_state_id,market_valid=market.trade_allowed,stage="confirmation",allowed_codes=[x["code"] for x in pool.candidates],baseline_candidates=pool.candidates);store.save_funnel(funnel);entity=ConfirmationV5.from_funnel(pool,funnel,decided_at=current);store.save_confirmation(entity);return entity.to_dict()

def freeze(root,*,now=None,sources=None):
    current=(now or datetime.now(CHINA_TZ)).astimezone(CHINA_TZ);day=current.date().isoformat();universe=load_universe(root,day,as_of=current,require_native=True);sources=sources or (SinaRealtimeSource(),EastmoneyRealtimeSource());result=ConsensusAcquirer(*sources).acquire(universe,stage="signal",now=current);_save_immutable(root,"consensus",day,"cons1-",result.report)
    attempts=result.report.get("attempts",[]);session=AcquisitionSessionV1.build(trade_date=day,stage="signal",requested_at=current,expected_codes=len(universe.codes),selected_snapshot_id=result.primary.snapshot_id if result.accepted else "",accepted=result.accepted,source_attempts=attempts);store=V5FactStore(root);store.save_session(session)
    if not result.accepted:raise ContractViolation("V5 feature freeze consensus rejected")
    store.save_snapshot(result.primary);pointer=Path(root)/"frozen"/day/"signal.json";pointer.parent.mkdir(parents=True,exist_ok=True);pointer_value={"snapshot_id":result.primary.snapshot_id,"frozen_at":current.isoformat(),"acquisition_session_id":session.session_id};raw=json.dumps(pointer_value,sort_keys=True,separators=(",",":"));tmp=pointer.with_suffix(f".{os.getpid()}.tmp");tmp.write_text(raw,encoding="utf-8")
    try:os.link(tmp,pointer)
    except FileExistsError:
        if pointer.read_text(encoding="utf-8")!=raw:raise ContractViolation("14:49 frozen pointer immutable collision")
    finally:tmp.unlink(missing_ok=True)
    return pointer_value

def paper_buy(root,*,now=None):
    root=Path(root);require_ownership(root/"ownership.json","paper_writer");current=(now or datetime.now(CHINA_TZ)).astimezone(CHINA_TZ);day=current.date().isoformat();confirmation=_latest(root,"confirmations",day);pointer=json.loads((root/"frozen"/day/"signal.json").read_text(encoding="utf-8"));snapshot_path=root/"snapshots"/day/f"{pointer['snapshot_id']}.json"
    if confirmation.get("snapshot_id")!=pointer.get("snapshot_id"):raise ContractViolation("V5 paper buy frozen lineage mismatch")
    event=PaperProduction(root).buy(confirmation,load_snapshot(snapshot_path),at=current,eligible_sell_date=TradingCalendar().next_open(current.date()).isoformat());return event.__dict__

def paper_sell(root,*,now=None,sources=None):
    root=Path(root);require_ownership(root/"ownership.json","paper_writer");current=(now or datetime.now(CHINA_TZ)).astimezone(CHINA_TZ);day=current.date().isoformat();positions=PaperProduction(root).ledger.state()["positions"]
    confirmations=[]
    for path in (root/"confirmations").glob("*/*.json") if (root/"confirmations").exists() else []:
        row=json.loads(path.read_text(encoding="utf-8"))
        if TradingCalendar().next_open(datetime.fromisoformat(row["decided_at"]).date())==current.date():confirmations.append(row)
    codes=sorted({row["code"] for row in positions}|{candidate["code"] for confirmation in confirmations for candidate in confirmation.get("candidates",[])})
    if not codes:return {"events":[],"baselines":[],"snapshot_id":"","outcome":"NO_POSITIONS_OR_BASELINE"}
    sources=sources or (SinaRealtimeSource(),EastmoneyRealtimeSource());universe=UniverseV1.build(trade_date=day,created_at=current,codes=codes,sources=["v5_open_positions_and_baseline"]);result=ConsensusAcquirer(*sources).acquire(universe,stage="sell",now=current)
    if not result.accepted:raise ContractViolation("V5 paper sell consensus rejected")
    V5FactStore(root).save_snapshot(result.primary);production=PaperProduction(root);events=production.sell_all(result.primary,at=current)
    if len(events)!=len(positions):raise ContractViolation("V5 paper sell missing executable bid")
    baselines=[]
    for confirmation in confirmations:
        buy_snapshot=load_snapshot(root/"snapshots"/confirmation["trade_date"]/f"{confirmation['snapshot_id']}.json");baselines.append(production.save_baseline(confirmation,buy_snapshot,result.primary,at=current))
    outcomes=[event.outcome for event in events]
    return {"events":[event.__dict__ for event in events],"baselines":baselines,"snapshot_id":result.primary.snapshot_id,"outcome":"FILLED" if outcomes and all(value=="FILLED" for value in outcomes) else "PARTIALLY_FILLED" if "FILLED" in outcomes else "UNFILLED"}
