"""V5.1-only dashboard model and immutable projection store."""
from __future__ import annotations
from dataclasses import dataclass
import json
from pathlib import Path
from shared_core.core import ContractViolation
from .facts import content_id,save_immutable

def production_state(*,failed_component=None,traded=False,complete=False,confirmation_outcome=None,execution_outcome=None):
    if failed_component:return "FAIL_CLOSED"
    if not complete:return "WAITING"
    if traded:return "TRADED"
    if execution_outcome in {"NO_STRICT_FILL","EXECUTION_REJECTED","FAIL_CLOSED"}:return execution_outcome
    if confirmation_outcome in {"EMPTY","NO_CANDIDATE"}:return "ACTIVE_FLAT"
    return "WAITING"

@dataclass(frozen=True)
class V51ReadModel:
    trade_date:str;state:str;master:dict;tradability:dict;market:dict;baseline:dict;closescan:dict;comparison:dict;accounts:dict;health:dict
    schema_version:str="v5.1-dashboard-read-model-v1";system_version:str="5.1"
    def to_dict(self):return self.__dict__.copy()

def save_projection(root,model):
    payload=model.to_dict();identity=dict(payload)
    payload["projection_id"]=content_id("v51rm1",identity)
    return save_immutable(Path(root)/"read_models"/model.trade_date/f"{payload['projection_id']}.json",payload)

def load_projection(root,trade_date):
    folder=Path(root)/"read_models"/str(trade_date);paths=sorted(folder.glob("*.json")) if folder.exists() else []
    if not paths:return build(trade_date=trade_date,health={"failed_component":"V5_1_READ_MODEL_MISSING","recovery_state":"WAITING_FOR_IMMUTABLE_PROJECTION"})
    try:
        payload=json.loads(paths[-1].read_text(encoding="utf-8"));claimed=payload.pop("projection_id")
        if payload.get("system_version")!="5.1" or payload.get("schema_version")!="v5.1-dashboard-read-model-v1" or payload.get("trade_date")!=str(trade_date):raise ContractViolation("V5.1 read-model version/date mismatch")
        if content_id("v51rm1",payload)!=claimed:raise ContractViolation("V5.1 read-model content address mismatch")
        fields={name:payload[name] for name in V51ReadModel.__dataclass_fields__ if name in payload}
        return V51ReadModel(**fields)
    except (KeyError,ValueError,TypeError,ContractViolation):
        return build(trade_date=trade_date,health={"failed_component":"V5_1_READ_MODEL_INVALID","recovery_state":"QUARANTINED"})

def build(*,trade_date,master=None,tradability=None,market=None,baseline=None,closescan=None,comparison=None,accounts=None,health=None):
    health=dict(health or {});baseline=dict(baseline or {});closescan=dict(closescan or {});failed=health.get("failed_component");traded=bool(baseline.get("traded") or closescan.get("traded"));complete=bool(health.get("production_complete"));outcome=baseline.get("confirmation_outcome") or health.get("confirmation_outcome");execution_outcome=health.get("execution_outcome")
    baseline.setdefault("state",production_state(failed_component=failed,traded=bool(baseline.get("traded")),complete=complete and bool(baseline.get("complete")),confirmation_outcome=baseline.get("confirmation_outcome")))
    closescan.setdefault("state",production_state(failed_component=failed,traded=bool(closescan.get("traded")),complete=complete and bool(closescan.get("complete")),confirmation_outcome=closescan.get("confirmation_outcome") or closescan.get("selection_outcome")))
    if failed:baseline["state"]=closescan["state"]="FAIL_CLOSED"
    return V51ReadModel(str(trade_date),production_state(failed_component=failed,traded=traded,complete=complete,confirmation_outcome=outcome,execution_outcome=execution_outcome),dict(master or {}),dict(tradability or {}),dict(market or {}),baseline,closescan,dict(comparison or {"cohort":"STRICT","conclusion":"EVIDENCE_INSUFFICIENT"}),dict(accounts or {"baseline":{},"closescan":{}}),health)
