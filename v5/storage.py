"""Content-addressed immutable V5 fact store; separate from V4 production data."""
from __future__ import annotations
import json,os
from pathlib import Path
from .contracts import AcquisitionSessionV1,CandidateFunnelV1
from .decision_flow import MorningPoolV5,ConfirmationV5

class V5FactStore:
    def __init__(self,root:Path|str):self.root=Path(root)
    def _path(self,kind,trade_date,entity_id):return self.root/kind/trade_date/f"{entity_id}.json"
    def save_session(self,session:AcquisitionSessionV1)->Path:return self._save("acquisition",session.trade_date,session.session_id,session.to_dict())
    def save_funnel(self,funnel:CandidateFunnelV1)->Path:return self._save("funnels",funnel.trade_date,funnel.funnel_id,funnel.to_dict())
    def save_pool(self,pool:MorningPoolV5)->Path:return self._save("morning_pools",pool.trade_date,pool.pool_id,pool.to_dict())
    def save_confirmation(self,confirmation:ConfirmationV5)->Path:return self._save("confirmations",confirmation.trade_date,confirmation.confirmation_id,confirmation.to_dict())
    def save_snapshot(self,snapshot)->Path:return self._save("snapshots",snapshot.trade_date,snapshot.snapshot_id,{"schema_version":snapshot.schema_version,"snapshot_id":snapshot.snapshot_id,"trade_date":snapshot.trade_date,"session":snapshot.session,"batch_started_at":snapshot.batch_started_at,"batch_completed_at":snapshot.batch_completed_at,"quality":snapshot.quality.__dict__,"quotes":[x.to_dict() for x in snapshot.quotes]})
    def _save(self,kind,day,entity_id,payload):
        path=self._path(kind,day,entity_id);raw=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":"))
        if path.exists():
            if path.read_text(encoding="utf-8")!=raw:raise ValueError("immutable fact collision")
            return path
        path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(f".{os.getpid()}.tmp");tmp.write_text(raw,encoding="utf-8")
        try:os.link(tmp,path)
        except FileExistsError:
            if path.read_text(encoding="utf-8")!=raw:raise ValueError("immutable fact collision")
        finally:tmp.unlink(missing_ok=True)
        return path
