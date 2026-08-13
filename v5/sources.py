"""Read-only V5 fact projection.  Never reads V4 candidate/runtime/dashboard files."""
from __future__ import annotations
from datetime import datetime
import json
from pathlib import Path
from types import SimpleNamespace
from .contracts import AcquisitionSessionV1,CandidateFunnelV1
from .decision_flow import MorningPoolV5,ConfirmationV5
from .performance import report_strict_paper
from .product_read_model import build
from .fact_reader import latest

def _latest(root:Path,kind:str,day:str,*,predicate=None,as_of=None):
    try:return latest(root,kind,day,predicate=predicate,as_of=as_of)
    except Exception:return None

class V5ReadOnlySources:
    def __init__(self,root:Path|str):self.root=Path(root)
    def build(self,trade_date:str,*,as_of=None):
        confirmation_raw=_latest(self.root,"confirmations",trade_date,as_of=as_of)
        stage="signal" if confirmation_raw else "morning"
        acquisition_raw=_latest(self.root,"acquisition",trade_date,predicate=lambda row:row.get("stage")==stage,as_of=as_of)
        pool_raw=_latest(self.root,"morning_pools",trade_date,as_of=as_of)
        acquisition=(AcquisitionSessionV1.build(trade_date=acquisition_raw["trade_date"],stage=acquisition_raw["stage"],requested_at=acquisition_raw["requested_at"],expected_codes=acquisition_raw["expected_codes"],selected_snapshot_id=acquisition_raw["selected_snapshot_id"],accepted=acquisition_raw["accepted"],source_attempts=acquisition_raw["source_attempts"]) if acquisition_raw else None)
        morning=(MorningPoolV5(pool_raw["trade_date"],pool_raw["created_at"],pool_raw["funnel_id"],pool_raw["snapshot_id"],pool_raw["market_state_id"],tuple(pool_raw["candidates"])) if pool_raw else None)
        confirmation=(ConfirmationV5(confirmation_raw["trade_date"],confirmation_raw["decided_at"],confirmation_raw["morning_pool_id"],confirmation_raw["funnel_id"],confirmation_raw["snapshot_id"],confirmation_raw["market_state_id"],tuple(confirmation_raw["candidates"]),tuple(confirmation_raw["changes"]),confirmation_raw["outcome"]) if confirmation_raw else None)
        ledger_path=self.root/"paper"/"round_trips.json"
        trips=json.loads(ledger_path.read_text(encoding="utf-8")).get("round_trips",[]) if ledger_path.exists() else []
        performance=report_strict_paper(trips,baseline_returns=[])
        account_path=self.root/"paper"/"account.json"
        account=json.loads(account_path.read_text(encoding="utf-8")) if account_path.exists() else {"initial_cash":100000,"cash":100000,"positions":[]}
        return build(acquisition=acquisition,morning=morning,confirmation=confirmation,performance=performance,account=account)
