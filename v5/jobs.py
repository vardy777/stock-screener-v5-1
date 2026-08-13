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

def load_universe(root,day):
    files=sorted((Path(root)/"universes"/day).glob("*.json"))
    if not files:raise ContractViolation("V5 universe fact missing")
    return UniverseV1.from_mapping(json.loads(files[-1].read_text(encoding="utf-8")))
def _latest(root,kind,day):
    files=sorted((Path(root)/kind/day).glob("*.json"))
    if not files:raise ContractViolation(f"V5 {kind} fact missing")
    return json.loads(files[-1].read_text(encoding="utf-8"))
def produce(root,stage,*,now=None,sources=None):
    current=(now or datetime.now(CHINA_TZ)).astimezone(CHINA_TZ);day=current.date().isoformat();universe=load_universe(root,day);sources=sources or (SinaRealtimeSource(),EastmoneyRealtimeSource());result=ConsensusAcquirer(*sources).acquire(universe,stage=stage,now=current)
    report_path=Path(root)/"consensus"/day/f"{stage}.json";report_path.parent.mkdir(parents=True,exist_ok=True);report_path.write_text(json.dumps(result.report,ensure_ascii=False,sort_keys=True,separators=(",",":")),encoding="utf-8")
    attempts=result.report.get("attempts",[]);session=AcquisitionSessionV1.build(trade_date=day,stage=stage,requested_at=current,expected_codes=len(universe.codes),selected_snapshot_id=result.primary.snapshot_id if result.accepted else "",accepted=result.accepted,source_attempts=attempts);store=V5FactStore(root);store.save_session(session)
    if not result.accepted:raise ContractViolation("V5 dual-source consensus rejected")
    store.save_snapshot(result.primary);funnel=CandidateFunnel()
    if stage=="morning":
        fact=funnel.run(result.primary,market_state_id="mstate1-"+result.primary.snapshot_id[4:28],market_valid=True,stage="morning");store.save_funnel(fact);entity=MorningPoolV5.from_funnel(fact,created_at=current);store.save_pool(entity);return entity.to_dict()
    pool_raw=_latest(root,"morning_pools",day);pool=MorningPoolV5(pool_raw["trade_date"],pool_raw["created_at"],pool_raw["funnel_id"],pool_raw["snapshot_id"],pool_raw["market_state_id"],tuple(pool_raw["candidates"]));fact=funnel.run(result.primary,market_state_id="mstate1-"+result.primary.snapshot_id[4:28],market_valid=True,stage="confirmation",allowed_codes=[x["code"] for x in pool.candidates]);store.save_funnel(fact);entity=ConfirmationV5.from_funnel(pool,fact,decided_at=current);store.save_confirmation(entity);return entity.to_dict()

def freeze(root,*,now=None,sources=None):
    current=(now or datetime.now(CHINA_TZ)).astimezone(CHINA_TZ);day=current.date().isoformat();universe=load_universe(root,day);sources=sources or (SinaRealtimeSource(),EastmoneyRealtimeSource());result=ConsensusAcquirer(*sources).acquire(universe,stage="signal",now=current);path=Path(root)/"consensus"/day/"feature_freeze.json";path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(result.report,ensure_ascii=False,sort_keys=True,separators=(",",":")),encoding="utf-8")
    if not result.accepted:raise ContractViolation("V5 feature freeze consensus rejected")
    V5FactStore(root).save_snapshot(result.primary);pointer=Path(root)/"frozen"/day/"signal.json";pointer.parent.mkdir(parents=True,exist_ok=True);pointer.write_text(json.dumps({"snapshot_id":result.primary.snapshot_id,"frozen_at":current.isoformat()},sort_keys=True),encoding="utf-8");return {"snapshot_id":result.primary.snapshot_id,"frozen_at":current.isoformat()}
