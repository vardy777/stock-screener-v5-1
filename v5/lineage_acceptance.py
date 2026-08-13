"""Fail-closed daily lineage acceptance across V5 facts and projections."""
from __future__ import annotations
import json
from pathlib import Path
from .fact_reader import latest
from .notification import build_payload
from .market_state import MarketStateV1
from .contracts import AcquisitionSessionV1
from .decision_flow import MorningPoolV5,ConfirmationV5
from .paper_production import load_snapshot

def _exists(root,kind,day,entity_id):return (Path(root)/kind/day/f"{entity_id}.json").exists()
def audit(root,day,*,as_of=None):
    root=Path(root);checks={};evidence={}
    try:
        morning_acq=latest(root,"acquisition",day,predicate=lambda row:row.get("stage")=="morning",as_of=as_of)
        signal_acq=latest(root,"acquisition",day,predicate=lambda row:row.get("stage")=="signal",as_of=as_of)
        pool=latest(root,"morning_pools",day,as_of=as_of);confirmation=latest(root,"confirmations",day,as_of=as_of)
        acquisition_entities=[]
        for raw in (morning_acq,signal_acq):
            entity=AcquisitionSessionV1.build(trade_date=raw["trade_date"],stage=raw["stage"],requested_at=raw["requested_at"],expected_codes=raw["expected_codes"],selected_snapshot_id=raw["selected_snapshot_id"],accepted=raw["accepted"],source_attempts=raw["source_attempts"])
            acquisition_entities.append(entity);checks[f"{raw['stage']}_acquisition_hash_matches"]=raw.get("session_id")==entity.session_id
        pool_entity=MorningPoolV5(pool["trade_date"],pool["created_at"],pool["funnel_id"],pool["snapshot_id"],pool["market_state_id"],tuple(pool["candidates"]));checks["morning_pool_hash_matches"]=pool.get("pool_id")==pool_entity.pool_id
        confirmation_entity=ConfirmationV5(confirmation["trade_date"],confirmation["decided_at"],confirmation["morning_pool_id"],confirmation["funnel_id"],confirmation["snapshot_id"],confirmation["market_state_id"],tuple(confirmation["candidates"]),tuple(confirmation["changes"]),confirmation["outcome"]);checks["confirmation_hash_matches"]=confirmation.get("confirmation_id")==confirmation_entity.confirmation_id
        pointer=json.loads((root/"frozen"/day/"signal.json").read_text(encoding="utf-8"))
        morning_snapshot=load_snapshot(root/"snapshots"/day/f"{morning_acq['selected_snapshot_id']}.json");signal_snapshot=load_snapshot(root/"snapshots"/day/f"{signal_acq['selected_snapshot_id']}.json")
        checks["morning_snapshot_exists"]=morning_snapshot.snapshot_id==morning_acq["selected_snapshot_id"]
        checks["pool_uses_morning_snapshot"]=pool["snapshot_id"]==morning_acq["selected_snapshot_id"]
        checks["signal_snapshot_exists"]=signal_snapshot.snapshot_id==signal_acq["selected_snapshot_id"]
        checks["freeze_uses_signal_snapshot"]=pointer["snapshot_id"]==signal_acq["selected_snapshot_id"]
        checks["freeze_uses_signal_acquisition"]=pointer.get("acquisition_session_id")==signal_acq["session_id"]
        checks["confirmation_uses_frozen_snapshot"]=confirmation["snapshot_id"]==pointer["snapshot_id"]
        checks["confirmation_uses_morning_pool"]=confirmation["morning_pool_id"]==pool["pool_id"]
        checks["confirmation_is_mother_pool_subset"]={x["code"] for x in confirmation.get("candidates",[])}<={x["code"] for x in pool.get("candidates",[])}
        for label,entity in (("morning",pool),("confirmation",confirmation)):
            state_path=root/"market_states"/day/f"{entity['market_state_id']}.json";state=MarketStateV1.from_mapping(json.loads(state_path.read_text(encoding="utf-8")));checks[f"{label}_market_state_id_matches"]=state.market_state_id==entity["market_state_id"];checks[f"{label}_market_state_snapshot_matches"]=state.snapshot_id==entity["snapshot_id"]
        for stage,entity_id in (("morning",pool["pool_id"]),("confirmation",confirmation["confirmation_id"])):
            payload=build_payload(root,day,stage,as_of=as_of);receipt=root/"notifications"/day/f"{stage}.json"
            checks[f"{stage}_payload_parent_matches"]=payload["parent_entity_id"]==entity_id
            if receipt.exists():
                row=json.loads(receipt.read_text(encoding="utf-8"));checks[f"{stage}_receipt_accepted"]=row.get("outcome")=="ACCEPTED" and row.get("response_code")==200;checks[f"{stage}_receipt_lineage_matches"]=row.get("parent_entity_id")==entity_id and row.get("payload_sha256")==payload["payload_sha256"]
            else:checks[f"{stage}_receipt_accepted"]=False;checks[f"{stage}_receipt_lineage_matches"]=False
        evidence={"morning_pool_id":pool["pool_id"],"confirmation_id":confirmation["confirmation_id"],"morning_snapshot_id":morning_acq["selected_snapshot_id"],"signal_snapshot_id":signal_acq["selected_snapshot_id"]}
    except Exception as exc:
        checks["audit_completed"]=False;evidence["error"]=f"{type(exc).__name__}: {exc}"
    return {"schema_version":"v5-daily-lineage-acceptance-v1","trade_date":day,"checks":checks,"evidence":evidence,"passed":bool(checks) and all(checks.values())}
