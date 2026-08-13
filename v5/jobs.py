"""V5 fact production jobs. Shadow-only until live acceptance changes state."""
from __future__ import annotations
from datetime import datetime
import json
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
from .paper_production import load_snapshot
from .fact_reader import latest

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
def produce(root,stage,*,now=None,sources=None):
    if stage != "morning":
        raise ContractViolation("live production is morning-only; confirmation must consume the 14:49 frozen snapshot")
    current=(now or datetime.now(CHINA_TZ)).astimezone(CHINA_TZ);day=current.date().isoformat();universe=load_universe(root,day,as_of=current,require_native=True);sources=sources or (SinaRealtimeSource(),EastmoneyRealtimeSource());result=ConsensusAcquirer(*sources).acquire(universe,stage=stage,now=current)
    report_path=Path(root)/"consensus"/day/f"{stage}.json";report_path.parent.mkdir(parents=True,exist_ok=True);report_path.write_text(json.dumps(result.report,ensure_ascii=False,sort_keys=True,separators=(",",":")),encoding="utf-8")
    attempts=result.report.get("attempts",[]);session=AcquisitionSessionV1.build(trade_date=day,stage=stage,requested_at=current,expected_codes=len(universe.codes),selected_snapshot_id=result.primary.snapshot_id if result.accepted else "",accepted=result.accepted,source_attempts=attempts);store=V5FactStore(root);store.save_session(session)
    if not result.accepted:raise ContractViolation("V5 dual-source consensus rejected")
    store.save_snapshot(result.primary);funnel=CandidateFunnel()
    fact=funnel.run(result.primary,market_state_id="mstate1-"+result.primary.snapshot_id[4:28],market_valid=True,stage="morning");store.save_funnel(fact);entity=MorningPoolV5.from_funnel(fact,created_at=current);store.save_pool(entity);return entity.to_dict()

def confirm_frozen(root,*,now=None):
    current=(now or datetime.now(CHINA_TZ)).astimezone(CHINA_TZ);day=current.date().isoformat();pointer_path=Path(root)/"frozen"/day/"signal.json"
    if not pointer_path.exists():raise ContractViolation("14:49 frozen snapshot missing")
    pointer=json.loads(pointer_path.read_text(encoding="utf-8"));snapshot_id=pointer["snapshot_id"];paths=list((Path(root)/"snapshots"/day).glob(f"{snapshot_id}.json"))
    if len(paths)!=1:raise ContractViolation("frozen snapshot content missing")
    snapshot=load_snapshot(paths[0]);pool_raw=_latest(root,"morning_pools",day);pool=MorningPoolV5(pool_raw["trade_date"],pool_raw["created_at"],pool_raw["funnel_id"],pool_raw["snapshot_id"],pool_raw["market_state_id"],tuple(pool_raw["candidates"]));funnel=CandidateFunnel().run(snapshot,market_state_id="mstate1-"+snapshot.snapshot_id[4:28],market_valid=True,stage="confirmation",allowed_codes=[x["code"] for x in pool.candidates]);store=V5FactStore(root);store.save_funnel(funnel);entity=ConfirmationV5.from_funnel(pool,funnel,decided_at=current);store.save_confirmation(entity);return entity.to_dict()

def freeze(root,*,now=None,sources=None):
    current=(now or datetime.now(CHINA_TZ)).astimezone(CHINA_TZ);day=current.date().isoformat();universe=load_universe(root,day,as_of=current,require_native=True);sources=sources or (SinaRealtimeSource(),EastmoneyRealtimeSource());result=ConsensusAcquirer(*sources).acquire(universe,stage="signal",now=current);path=Path(root)/"consensus"/day/"feature_freeze.json";path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(result.report,ensure_ascii=False,sort_keys=True,separators=(",",":")),encoding="utf-8")
    attempts=result.report.get("attempts",[]);session=AcquisitionSessionV1.build(trade_date=day,stage="signal",requested_at=current,expected_codes=len(universe.codes),selected_snapshot_id=result.primary.snapshot_id if result.accepted else "",accepted=result.accepted,source_attempts=attempts);store=V5FactStore(root);store.save_session(session)
    if not result.accepted:raise ContractViolation("V5 feature freeze consensus rejected")
    store.save_snapshot(result.primary);pointer=Path(root)/"frozen"/day/"signal.json";pointer.parent.mkdir(parents=True,exist_ok=True);pointer.write_text(json.dumps({"snapshot_id":result.primary.snapshot_id,"frozen_at":current.isoformat(),"acquisition_session_id":session.session_id},sort_keys=True),encoding="utf-8");return {"snapshot_id":result.primary.snapshot_id,"frozen_at":current.isoformat(),"acquisition_session_id":session.session_id}
