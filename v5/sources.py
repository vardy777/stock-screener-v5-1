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
from .market_state import MarketStateV1
from .core import ContractViolation

def _latest(root:Path,kind:str,day:str,*,predicate=None,as_of=None):
    try:return latest(root,kind,day,predicate=predicate,as_of=as_of)
    except ContractViolation as exc:
        if str(exc).endswith("fact missing"):return None
        raise

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
        active=confirmation or morning
        if active and (acquisition is None or not acquisition.accepted or acquisition.selected_snapshot_id!=active.snapshot_id):
            raise ValueError("dashboard acquisition snapshot lineage mismatch")
        if confirmation and (morning is None or confirmation.morning_pool_id!=morning.pool_id):
            raise ValueError("dashboard confirmation mother-pool lineage mismatch")
        state_id=confirmation.market_state_id if confirmation else morning.market_state_id if morning else "";market_state=None
        if state_id:
            state_path=self.root/"market_states"/trade_date/f"{state_id}.json"
            if not state_path.exists():raise ValueError("dashboard market state missing")
            validated=MarketStateV1.from_mapping(json.loads(state_path.read_text(encoding="utf-8")))
            if validated.market_state_id!=state_id:raise ValueError("dashboard market state id mismatch")
            expected_snapshot=confirmation.snapshot_id if confirmation else morning.snapshot_id
            if validated.snapshot_id!=expected_snapshot:raise ValueError("dashboard market state snapshot mismatch")
            market_state=validated.to_dict()
        from .paper import PaperLedger
        ledger=PaperLedger(self.root/"paper");trips=ledger.round_trips(as_of=as_of)
        baselines={}
        for path in (self.root/"paper"/"baselines").glob("*.json") if (self.root/"paper"/"baselines").exists() else []:
            row=json.loads(path.read_text(encoding="utf-8"))
            if row.get("baseline_name")=="top1_execution_equivalent_next_open" and row.get("net_return") is not None and (as_of is None or row.get("sell_trade_date","")<=as_of.date().isoformat()):baselines[row["confirmation_id"]]=float(row["net_return"])
        paired=[row for row in trips if row.get("decision_id") in baselines];baseline_rows=[baselines[row["decision_id"]] for row in paired]
        performance=report_strict_paper(trips,baseline_returns=baseline_rows,comparison_returns=[row["net_return"] for row in paired],baseline_name="top1_execution_equivalent_next_open")
        account=ledger.state(as_of=as_of)
        return build(acquisition=acquisition,morning=morning,confirmation=confirmation,market_state=market_state,performance=performance,account=account,comparable_baseline_days=len(paired))
