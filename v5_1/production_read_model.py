"""Production-grade V5.1 read model built only from immutable saved facts."""
from dataclasses import asdict,dataclass
import json
from pathlib import Path
from datetime import datetime,time
from shared_core.core import CHINA_TZ
from shared_core.calendar import TradingCalendar
from shared_core.core import ContractViolation,strict_bool,strict_int
from . import BASELINE_STRATEGY_VERSION,CLOSESCAN_STRATEGY_VERSION,CONTRACT_VERSION,SYSTEM_VERSION
from .facts import content_id
from .read_model import build,save_projection
from .security_master import aware

@dataclass(frozen=True)
class ProductionRunFactV51:
    trade_date:str;task_name:str;completed_at:str;outcome:str;entity_id:str="";runtime_mode:str="SHADOW";cohort:str="V51_SHADOW";strict_evidence:bool=False;system_version:str=SYSTEM_VERSION;contract_version:str=CONTRACT_VERSION;schema_version:str="v5.1-production-run-v1"
    def __post_init__(self):
        aware(self.completed_at,"completed_at");strict_bool(self.strict_evidence,"strict_evidence")
        if self.outcome not in {"SUCCESS","FAILED"} or not self.task_name:raise ContractViolation("production run outcome/task invalid")
    @property
    def run_id(self):return content_id("v51prodrun1",asdict(self))
    def to_dict(self):return {**asdict(self),"run_id":self.run_id}

@dataclass(frozen=True)
class ProductionFailureFactV51:
    trade_date:str;component:str;occurred_at:str;reason_code:str;runtime_mode:str="SHADOW";cohort:str="V51_SHADOW";strict_evidence:bool=False;system_version:str=SYSTEM_VERSION;contract_version:str=CONTRACT_VERSION;schema_version:str="v5.1-production-failure-v1"
    diagnostic:dict|None=None
    def __post_init__(self):
        aware(self.occurred_at,"occurred_at");strict_bool(self.strict_evidence,"strict_evidence")
        if not self.component or not self.reason_code:raise ContractViolation("production failure identity required")
        if self.diagnostic is not None:
            if type(self.diagnostic) is not dict:raise ContractViolation("production failure diagnostic must be mapping")
            forbidden={"raw_content_b64","token","authorization","secret"}&{str(key).lower() for key in self.diagnostic}
            if forbidden:raise ContractViolation("production failure diagnostic contains forbidden material")
    @property
    def failure_id(self):return content_id("v51failure1",asdict(self))
    def to_dict(self):return {**asdict(self),"failure_id":self.failure_id}

@dataclass(frozen=True)
class ExecutionResultFactV51:
    trade_date:str;strategy_version:str;side:str;observation_id:str;paper_event_id:str;outcome:str;completed_at:str;runtime_mode:str="SHADOW";cohort:str="V51_SHADOW";strict_evidence:bool=False;system_version:str=SYSTEM_VERSION;contract_version:str=CONTRACT_VERSION;schema_version:str="v5.1-execution-result-v1"
    def __post_init__(self):
        aware(self.completed_at,"completed_at");strict_bool(self.strict_evidence,"strict_evidence")
        if self.strategy_version not in {BASELINE_STRATEGY_VERSION,CLOSESCAN_STRATEGY_VERSION} or self.side not in {"BUY","SELL"} or self.outcome not in {"FILLED","REJECTED","UNFILLED"} or not self.observation_id or not self.paper_event_id:raise ContractViolation("execution result contract invalid")
    @property
    def execution_result_id(self):return content_id("v51execresult1",asdict(self))
    def to_dict(self):return {**asdict(self),"execution_result_id":self.execution_result_id}

@dataclass(frozen=True)
class ExecutionRejectionFactV51:
    trade_date:str;strategy_version:str;side:str;code:str;decision_id:str;source_snapshot_ids:tuple[str,...];reason_code:str;completed_at:str;runtime_mode:str;cohort:str;strict_evidence:bool;system_version:str=SYSTEM_VERSION;contract_version:str=CONTRACT_VERSION;schema_version:str="v5.1-execution-rejection-v1"
    outcome:str="REJECTED"
    def __post_init__(self):
        aware(self.completed_at,"completed_at")
        strict_bool(self.strict_evidence,"strict_evidence")
        if self.strategy_version not in {BASELINE_STRATEGY_VERSION,CLOSESCAN_STRATEGY_VERSION} or self.side not in {"BUY","SELL"} or not self.code or not self.reason_code or self.outcome!="REJECTED":raise ContractViolation("execution rejection contract invalid")
    @property
    def rejection_id(self):return content_id("v51execreject1",self.to_dict(False))
    def to_dict(self,include_id=True):
        row={**asdict(self),"source_snapshot_ids":list(self.source_snapshot_ids)}
        if include_id:row["rejection_id"]=self.rejection_id
        return row

@dataclass(frozen=True)
class ExitDecisionFactV51:
    trade_date:str;strategy_version:str;code:str;position_decision_id:str;buy_observation_id:str;eligible_sell_date:str;decided_at:str;runtime_mode:str;cohort:str;strict_evidence:bool;system_version:str=SYSTEM_VERSION;contract_version:str=CONTRACT_VERSION;schema_version:str="v5.1-exit-decision-v1"
    def __post_init__(self):
        aware(self.decided_at,"decided_at");strict_bool(self.strict_evidence,"strict_evidence")
        if self.strategy_version not in {BASELINE_STRATEGY_VERSION,CLOSESCAN_STRATEGY_VERSION} or not self.buy_observation_id:raise ContractViolation("exit decision lineage invalid")
    @property
    def exit_decision_id(self):return content_id("v51exitdecision1",asdict(self))
    def to_dict(self):return {**asdict(self),"exit_decision_id":self.exit_decision_id}

@dataclass(frozen=True)
class HealthFactV51:
    trade_date:str;completed_at:str;run_ids:tuple[str,...];ledger_reconciliations:dict;pending_orders:int;status:str;system_version:str=SYSTEM_VERSION;contract_version:str=CONTRACT_VERSION;schema_version:str="v5.1-health-v1"
    def __post_init__(self):
        aware(self.completed_at,"completed_at");strict_int(self.pending_orders,"pending_orders",0)
        if self.status!="PASSED" or type(self.ledger_reconciliations) is not dict:raise ContractViolation("health fact contract invalid")
    @property
    def health_id(self):return content_id("v51health1",self.to_dict(False))
    def to_dict(self,include_id=True):
        row={**asdict(self),"run_ids":list(self.run_ids)}
        if include_id:row["health_id"]=self.health_id
        return row

@dataclass(frozen=True)
class AcceptanceFactV51:
    trade_date:str;completed_at:str;run_ids:tuple[str,...];entity_ids:tuple[str,...];pipeline_window_acceptance:str;execution_acceptance:str;next_open_exit_acceptance:str;round_trip_acceptance:str;real_window_acceptance:str;system_version:str=SYSTEM_VERSION;contract_version:str=CONTRACT_VERSION;schema_version:str="v5.1-acceptance-v1"
    def __post_init__(self):
        aware(self.completed_at,"completed_at")
        if self.pipeline_window_acceptance!="PASS" or self.execution_acceptance not in {"PASS","ACTIVE_FLAT","NO_STRICT_FILL","EXECUTION_REJECTED","FAIL_CLOSED"} or self.next_open_exit_acceptance!="PENDING" or self.round_trip_acceptance!="PENDING" or self.real_window_acceptance not in {"PRELIMINARY_ONLY","PENDING_REAL_WINDOW"}:raise ContractViolation("preliminary acceptance contract invalid")
    @property
    def acceptance_id(self):return content_id("v51accept1",self.to_dict(False))
    def to_dict(self,include_id=True):
        row={**asdict(self),"run_ids":list(self.run_ids),"entity_ids":list(self.entity_ids)}
        if include_id:row["acceptance_id"]=self.acceptance_id
        return row

@dataclass(frozen=True)
class RoundTripAcceptanceFactV51:
    trade_date:str;exit_trade_date:str;completed_at:str;preliminary_acceptance_id:str;day_mode:str;trade_count:int
    strategy_versions:tuple[str,...];round_trip_ids:tuple[str,...];buy_event_ids:tuple[str,...];sell_event_ids:tuple[str,...]
    net_pnl:str;status:str;runtime_mode:str;cohort:str;strict_evidence:bool;system_version:str=SYSTEM_VERSION
    contract_version:str=CONTRACT_VERSION;schema_version:str="v5.1-round-trip-acceptance-v1"
    def __post_init__(self):
        aware(self.completed_at,"completed_at")
        if self.day_mode not in {"TRADED","ACTIVE_FLAT"} or self.status not in {"PASS","FAIL"}:raise ContractViolation("round-trip acceptance enum invalid")
        if type(self.strict_evidence) is not bool or type(self.trade_count) is not int or self.trade_count<0:raise ContractViolation("round-trip acceptance strict type invalid")
        if not self.preliminary_acceptance_id.startswith("v51accept1-"):raise ContractViolation("round-trip preliminary lineage invalid")
        if self.day_mode=="ACTIVE_FLAT" and (self.trade_count or self.round_trip_ids or self.buy_event_ids or self.sell_event_ids):raise ContractViolation("ACTIVE_FLAT cannot contain trades")
        if self.day_mode=="TRADED" and (self.trade_count<1 or not (len(self.round_trip_ids)==len(self.buy_event_ids)==len(self.sell_event_ids)==self.trade_count)):raise ContractViolation("round-trip lineage cardinality invalid")
    @property
    def round_trip_acceptance_id(self):return content_id("v51roundaccept1",self.to_dict(False))
    def to_dict(self,include_id=True):
        row={**asdict(self),"strategy_versions":list(self.strategy_versions),"round_trip_ids":list(self.round_trip_ids),"buy_event_ids":list(self.buy_event_ids),"sell_event_ids":list(self.sell_event_ids)}
        if include_id:row["round_trip_acceptance_id"]=self.round_trip_acceptance_id
        return row

@dataclass(frozen=True)
class StageOutcomeFactV51:
    trade_date:str;stage:str;outcome:str;strategy_versions:tuple[str,...];recorded_at:str;runtime_mode:str;cohort:str;strict_evidence:bool;intent_count:int=0;result_count:int=0;rejection_count:int=0;intent_ids:tuple[str,...]=();audit_entity_ids:tuple[str,...]=();system_version:str=SYSTEM_VERSION;contract_version:str=CONTRACT_VERSION;schema_version:str="v5.1-stage-outcome-v2"
    def __post_init__(self):
        aware(self.recorded_at,"recorded_at");strict_bool(self.strict_evidence,"strict_evidence")
        if self.outcome not in {"ACTIVE_FLAT","NO_POSITIONS","ALL_FILLED","PARTIAL_FILL","NO_STRICT_FILL","EXECUTION_REJECTED","FAIL_CLOSED"}:raise ContractViolation("stage outcome invalid")
        for field in ("intent_count","result_count","rejection_count"):strict_int(getattr(self,field),field,0)
        if min(self.intent_count,self.result_count,self.rejection_count)<0 or self.result_count+self.rejection_count!=self.intent_count:raise ContractViolation("stage outcome counts invalid")
    @property
    def stage_outcome_id(self):return content_id("v51stageoutcome1",self.to_dict(False))
    def to_dict(self,include_id=True):
        row={**asdict(self),"strategy_versions":list(self.strategy_versions),"intent_ids":list(self.intent_ids),"audit_entity_ids":list(self.audit_entity_ids)}
        if include_id:row["stage_outcome_id"]=self.stage_outcome_id
        return row

KIND_IDS={"production_runs":("run_id","v51prodrun1"),"production_failures":("failure_id","v51failure1"),"confirmations":("confirmation_id","v51confirm1"),"closescan_selections":("selection_id","closescan1"),"execution_observations":("observation_id","v51execobs1"),"execution_results":("execution_result_id","v51execresult1"),"execution_rejections":("rejection_id","v51execreject1"),"exit_decisions":("exit_decision_id","v51exitdecision1"),"health_facts":("health_id","v51health1"),"acceptance_facts":("acceptance_id","v51accept1"),"round_trip_acceptances":("round_trip_acceptance_id","v51roundaccept1"),"stage_outcomes":("stage_outcome_id","v51stageoutcome1")}

class ImmutableReadModelBuilder:
    def __init__(self,root):self.root=Path(root)
    def _rows(self,kind,trade_date):
        folder=self.root/kind/str(trade_date);rows=[];id_field,prefix=KIND_IDS[kind]
        for path in sorted(folder.glob("*.json")) if folder.exists() else ():
            row=json.loads(path.read_text(encoding="utf-8"));claimed=row.pop(id_field,"")
            from .decision import BaselineConfirmationV51
            from .closescan import CloseScanSelectionV1
            from .execution import ExecutionObservationV51
            classes={"production_runs":ProductionRunFactV51,"production_failures":ProductionFailureFactV51,"confirmations":BaselineConfirmationV51,"closescan_selections":CloseScanSelectionV1,"execution_observations":ExecutionObservationV51,"execution_results":ExecutionResultFactV51,"execution_rejections":ExecutionRejectionFactV51,"exit_decisions":ExitDecisionFactV51,"health_facts":HealthFactV51,"acceptance_facts":AcceptanceFactV51,"round_trip_acceptances":RoundTripAcceptanceFactV51,"stage_outcomes":StageOutcomeFactV51}
            expected=set(classes[kind].__dataclass_fields__)
            if set(row)!=expected:raise ContractViolation(f"{kind} persisted keys invalid")
            if "strict_evidence" in row:strict_bool(row["strict_evidence"],"strict_evidence")
            for field in ("intent_count","result_count","rejection_count","trade_count","pending_orders"):
                if field in row:strict_int(row[field],field,0)
            for field in ("run_ids","entity_ids","source_snapshot_ids","strategy_versions","round_trip_ids","buy_event_ids","sell_event_ids","intent_ids","audit_entity_ids"):
                if field in row and type(row[field]) is not list:raise ContractViolation(f"{field}: persisted list required")
            if row.get("system_version")!=SYSTEM_VERSION or row.get("contract_version")!=CONTRACT_VERSION or row.get("trade_date")!=str(trade_date):raise ContractViolation(f"{kind} version/date mismatch")
            if claimed!=content_id(prefix,row) or path.stem!=claimed:raise ContractViolation(f"{kind} content-address mismatch")
            row[id_field]=claimed;rows.append(row)
        return rows
    def build(self,trade_date,as_of=None):
        day=str(trade_date)
        try:
            runs=self._rows("production_runs",day);failures=self._rows("production_failures",day);confirmations=self._rows("confirmations",day);selections=self._rows("closescan_selections",day);observations=self._rows("execution_observations",day);results=self._rows("execution_results",day);stage_outcomes=[x for x in self._rows("stage_outcomes",day) if x.get("stage")=="execution"]
            if len(stage_outcomes)>1:raise ContractViolation("ambiguous execution stage outcome")
            if len(confirmations)>1 or len(selections)>1:raise ContractViolation("ambiguous final strategy fact")
            observation_ids={row["observation_id"] for row in observations}
            if any(row["observation_id"] not in observation_ids for row in results):raise ContractViolation("execution result references missing observation")
            current=(as_of or datetime.now(CHINA_TZ)).astimezone(CHINA_TZ)
            no_evidence=not any((runs,failures,confirmations,selections,observations,results))
            missed=no_evidence and current.date().isoformat()==day and TradingCalendar().is_open(current.date()) and current.timetz().replace(tzinfo=None)>time(9,35,59)
            attempts=[]
            attempts.extend((row["occurred_at"],row["component"],"FAILED") for row in failures)
            attempts.extend((row["completed_at"],row["task_name"],row["outcome"]) for row in runs)
            latest_by_component={}
            for item in sorted(attempts):latest_by_component[item[1]]=item
            failed=("MISSED_0935_MORNING_WINDOW" if missed else next((name for _,name,outcome in latest_by_component.values() if outcome=="FAILED"),None))
            acceptances=self._rows("acceptance_facts",day)
            complete=bool(acceptances) and any(row["task_name"]=="acceptance" and row["outcome"]=="SUCCESS" and row.get("entity_id")==acceptances[-1]["acceptance_id"] for row in runs)
            confirmation=confirmations[0] if confirmations else {};selection=selections[0] if selections else {}
            baseline_results=[row for row in results if row["strategy_version"]==BASELINE_STRATEGY_VERSION];close_results=[row for row in results if row["strategy_version"]==CLOSESCAN_STRATEGY_VERSION]
            baseline={"complete":complete,"confirmation_outcome":confirmation.get("outcome"),"candidates":confirmation.get("candidates",[]),"decision_snapshot_id":confirmation.get("decision_snapshot_id"),"traded":any(row["side"]=="BUY" and row["outcome"]=="FILLED" for row in baseline_results)}
            closescan={"complete":complete,"selection_outcome":selection.get("outcome"),"candidates":selection.get("candidates",[]),"decision_snapshot_id":selection.get("decision_snapshot_id"),"traded":any(row["side"]=="BUY" and row["outcome"]=="FILLED" for row in close_results)}
            lineage="NO_EVIDENCE" if no_evidence else "VERIFIED" if complete and not failed else "PARTIAL"
            successful={row["task_name"]:row for row in runs if row["outcome"]=="SUCCESS"}
            master={"status":"MISSING","failure_reason":"NO_VERIFIED_MASTER"}
            try:
                from .security_master import SecurityMasterRepository
                verification=SecurityMasterRepository(self.root).require_fresh(day,current,TradingCalendar())
                versions=SecurityMasterRepository(self.root).as_of(day,current)
                master={"status":"VERIFIED","count":len(versions),"version":verification.verification_id,"last_verified_at":verification.verified_at,"freshness":"CURRENT_OR_PREVIOUS_OPEN_DAY","independent_sources":list(verification.independent_source_families),"sse_status":"VERIFIED" if "sse" in verification.independent_source_families else "MISSING","szse_status":"VERIFIED" if "szse" in verification.independent_source_families else "MISSING"}
            except ContractViolation as exc:master["failure_reason"]=str(exc)
            tradability={"status":"VERIFIED" if "morning_observation" in successful else "MISSING"}
            market={"open_status":"VERIFIED" if "morning_observation" in successful else "WAITING","freeze_status":"VERIFIED" if "feature_freeze" in successful else "WAITING"}
            baseline.update({"morning_status":"VERIFIED" if "morning_pool" in successful else "WAITING","confirmation_status":"VERIFIED" if confirmation else "WAITING","execution_status":"VERIFIED" if baseline_results else "WAITING","exit_status":"VERIFIED" if any(x["side"]=="SELL" for x in baseline_results) else "WAITING"})
            closescan.update({"confirmation_status":"VERIFIED" if selection else "WAITING","execution_status":"VERIFIED" if close_results else "WAITING","exit_status":"VERIFIED" if any(x["side"]=="SELL" for x in close_results) else "WAITING"})
            health={"production_complete":complete,"failed_component":failed,"confirmation_outcome":confirmation.get("outcome"),"execution_outcome":stage_outcomes[0]["outcome"] if stage_outcomes else None,"immutable_run_count":len(runs),"immutable_failure_count":len(failures),"immutable_execution_count":len(results),"lineage":lineage,"master_failure_reason":master.get("failure_reason")}
            return build(trade_date=day,master=master,tradability=tradability,market=market,baseline=baseline,closescan=closescan,health=health)
        except (OSError,ValueError,TypeError,KeyError,ContractViolation) as exc:
            return build(trade_date=day,health={"failed_component":"V5_1_IMMUTABLE_FACT_INVALID","first_failure":str(exc),"lineage":"QUARANTINED"})
    def build_and_save(self,trade_date):
        model=self.build(trade_date);save_projection(self.root,model);return model
