"""Independent full-market 14:49 CloseScan challenger."""
from __future__ import annotations
from dataclasses import asdict,dataclass
from datetime import time
from pathlib import Path
from shared_core.core import ContractViolation
from shared_core.funnel import CandidateFunnel,FunnelPolicyV1
from shared_core.paper import PaperLedger
from . import CLOSESCAN_STRATEGY_VERSION,CONTRACT_VERSION,SYSTEM_VERSION
from .decision import DecisionSnapshotRepository,FeatureFreezeV51,_plain,_snapshot_before,_window
from .facts import content_id
from .tradability import DailyTradabilityFactV1

@dataclass(frozen=True)
class CloseScanSelectionV1:
    trade_date:str;decided_at:str;tradability_id:str;decision_snapshot_id:str;market_state_id:str;funnel_id:str;candidates:tuple[dict,...];outcome:str
    strategy_version:str=CLOSESCAN_STRATEGY_VERSION;system_version:str=SYSTEM_VERSION;contract_version:str=CONTRACT_VERSION
    schema_version:str="v5.1-closescan-selection-v1"
    @property
    def selection_id(self):return content_id("closescan1",self.to_dict(False))
    def to_dict(self,include_id=True):
        value={**asdict(self),"candidates":list(self.candidates)}
        if include_id:value["selection_id"]=self.selection_id
        return value

@dataclass(frozen=True)
class CloseScanCandidateFactV1:
    trade_date:str;created_at:str;tradability_id:str;decision_snapshot_id:str;market_state_id:str;funnel_id:str;policy_parameters:dict;stages:tuple[dict,...];candidates:tuple[dict,...]
    strategy_version:str=CLOSESCAN_STRATEGY_VERSION;system_version:str=SYSTEM_VERSION;contract_version:str=CONTRACT_VERSION;schema_version:str="v5.1-closescan-candidate-fact-v1"
    @property
    def candidate_fact_id(self):return content_id("v51cscandidates1",self.to_dict(False))
    def to_dict(self,include_id=True):
        value={**asdict(self),"policy_parameters":_plain(self.policy_parameters),"stages":_plain(self.stages),"candidates":_plain(self.candidates)}
        if include_id:value["candidate_fact_id"]=self.candidate_fact_id
        return value

@dataclass(frozen=True)
class CloseScanRunFactV1:
    trade_date:str;started_at:str;completed_at:str;tradability_id:str;decision_snapshot_id:str;feature_freeze_id:str;candidate_fact_id:str;selection_id:str;outcome:str
    strategy_version:str=CLOSESCAN_STRATEGY_VERSION;system_version:str=SYSTEM_VERSION;contract_version:str=CONTRACT_VERSION;schema_version:str="v5.1-closescan-run-v1"
    @property
    def run_id(self):return content_id("v51csrun1",asdict(self))
    def to_dict(self):return {**asdict(self),"run_id":self.run_id}

@dataclass(frozen=True)
class CloseScanFacts:
    candidates:CloseScanCandidateFactV1;selection:CloseScanSelectionV1;run:CloseScanRunFactV1

def build_facts(snapshot,tradability:DailyTradabilityFactV1,*,freeze:FeatureFreezeV51,snapshot_repository:DecisionSnapshotRepository,decided_at,market_state_id,market_valid,policy=None):
    decision=_window(decided_at,time(14,50),time(14,51,59),"closescan decision");_snapshot_before(snapshot,decision,"signal")
    snapshot_repository.require(freeze,snapshot)
    if not tradability.accepted or tradability.trade_date!=decision.date().isoformat():raise ContractViolation("CloseScan accepted same-day tradability required")
    # Deliberately has no MorningPool argument or dependency.
    funnel=CandidateFunnel(policy or FunnelPolicyV1()).run(snapshot,market_state_id=market_state_id,market_valid=market_valid,stage="morning",allowed_codes=tradability.eligible_symbols)
    candidates=[]
    for raw in funnel.candidates:
        row=_plain(raw);row.update({"strategy_version":CLOSESCAN_STRATEGY_VERSION,"system_version":SYSTEM_VERSION,"candidate_origin":"CLOSESCAN_FULL_MARKET_1449"});candidates.append(row)
    candidate_fact=CloseScanCandidateFactV1(decision.date().isoformat(),decision.isoformat(),tradability.tradability_id,snapshot.snapshot_id,market_state_id,funnel.funnel_id,_plain(funnel.policy_parameters),tuple(_plain(funnel.stages)),tuple(candidates))
    selection=CloseScanSelectionV1(decision.date().isoformat(),decision.isoformat(),tradability.tradability_id,snapshot.snapshot_id,market_state_id,funnel.funnel_id,tuple(candidates),"BUY_CANDIDATE" if candidates else "EMPTY")
    run=CloseScanRunFactV1(decision.date().isoformat(),freeze.frozen_at,decision.isoformat(),tradability.tradability_id,snapshot.snapshot_id,freeze.freeze_id,candidate_fact.candidate_fact_id,selection.selection_id,selection.outcome)
    return CloseScanFacts(candidate_fact,selection,run)

def select(snapshot,tradability:DailyTradabilityFactV1,*,freeze:FeatureFreezeV51,snapshot_repository:DecisionSnapshotRepository,decided_at,market_state_id,market_valid,policy=None):
    return build_facts(snapshot,tradability,freeze=freeze,snapshot_repository=snapshot_repository,decided_at=decided_at,market_state_id=market_state_id,market_valid=market_valid,policy=policy).selection

def isolated_ledgers(root):
    root=Path(root);baseline=PaperLedger(root/"baseline/paper");closescan=PaperLedger(root/"closescan/paper")
    if baseline.root.resolve()==closescan.root.resolve():raise ContractViolation("strategy ledgers must be isolated")
    return baseline,closescan
